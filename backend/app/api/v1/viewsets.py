from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated,AllowAny
from rest_framework.exceptions import PermissionDenied
from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle
from rest_framework.response import Response
from rest_framework import status
from datetime import datetime, time
from django.utils.timezone import make_aware


from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core import signing
from django.core.exceptions import ValidationError
from django.db.models import F, Q

from app.models import (
    Pedido, ItemPedido, Produto, Loja, Estoque, MovimentacaoEstoque,
    Notificacao, PreferenciaNotificacao,
)
from app.notifications.tasks import (
    enviar_email_definir_senha,
    validar_token_confirmacao,
)
from app.notifications.tokens import validar_token_senha
from .mixins import ResponsavelOuAdminMixin, UserOuAdminMixin
from .serializers import (
    EstoqueBaixoSerializer,
    EstoqueCreateSerializer,
    PedidoSerializer,
    PedidoCreateSerializer,
    PedidoUpdateSerializer,
    ItemPedidoSerializer,
    MovimentacaoEstoqueSerializer,
    PreferenciaNotificacaoSerializer,
    ProdutoSerializer,
    UsuarioSerializer,
    LojaSerializer,
    EstoqueSerializer,
    EstoqueUpdateSerializer,
    NotificacaoSerializer,
    VendaCreateSerializer,
)
from app.permissions import IsGerenteOrAdministrador, IsGerenteOrAdministradorOrResponsavel
from app.notifications import notificar_estoques_baixos_do_pedido, notificar_estoque_baixo
from rest_framework.decorators import action

def somar_itens_no_estoque(pedido):
    """Soma os itens do pedido no estoque da loja (pedido ENTREGUE).

    Funcao de modulo para ser reusada pelo site (atualizar_status) e pelo
    bot de WhatsApp (confirmacao de recebimento).
    """
    for item in pedido.itens.select_related('produto').all():
        estoque, _ = Estoque.objects.get_or_create(
            loja=pedido.loja,
            produto=item.produto,
            defaults={
                'quantidade_atual': 0,
                'quantidade_minima': item.produto.estoque_minimo_sugerido,
            }
        )
        estoque.quantidade_atual += item.quantidade
        estoque.save(update_fields=['quantidade_atual', 'updated_at'])
        MovimentacaoEstoque.objects.create(
            tipo=MovimentacaoEstoque.Tipo.ENTRADA,
            produto=item.produto,
            loja_destino=pedido.loja,
            quantidade=item.quantidade,
            usuario=pedido.responsavel,
        )
        notificar_estoque_baixo(estoque)


class RegistroRateThrottle(AnonRateThrottle):
    """Limita o cadastro publico (anonimo) usando a taxa 'registro'.

    Herda de AnonRateThrottle: usuarios autenticados (ex: admin criando
    gerentes) nao sao limitados por esta regra.
    """

    scope = "registro"


class SenhaRateThrottle(SimpleRateThrottle):
    """Limita o pedido de link de senha pelo email ALVO, nao por quem pede.

    Herdar de AnonRateThrottle nao servia: o get_cache_key dele devolve None
    para requisicao autenticada, ou seja, qualquer conta logada podia inundar
    a caixa de qualquer loja com links de redefinicao. Chavear pelo alvo poe o
    teto onde o dano acontece e vale para anonimo e logado igualmente.
    """

    scope = "senha"

    def get_cache_key(self, request, view):
        email = request.data.get("email")
        if isinstance(email, str) and email.strip():
            ident = email.strip().lower()
        else:
            # Sem email nao ha o que enviar; limita pela origem so para a rota
            # nao ficar sem teto nenhum.
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


# 🔹 Helper
def is_gerente_ou_admin(user):
    return (
        user.is_superuser
        or user.groups.filter(name='Admin').exists()
        or user.groups.filter(name='Gerente').exists()
    )


def get_user_group_name(user):
    if user.is_superuser or user.groups.filter(name='Admin').exists():
        return 'Admin'

    group = user.groups.first()
    return group.name if group else None

    
# 🔹 LOJA
class LojaViewSet(viewsets.ModelViewSet):
    queryset = Loja.objects.all().order_by('id')
    serializer_class = LojaSerializer
    lookup_field = 'public_id'

    def get_permissions(self):
        if self.action == 'list':
            # Dados de loja (endereco, responsavel) nao sao publicos.
            return [IsAuthenticated()]
        if self.action == 'create':
            # Criar loja e coisa de gerente/admin.
            return [IsAuthenticated(), IsGerenteOrAdministrador()]
        # Editar/apagar: gerente/admin, ou o responsavel na propria loja.
        return [IsAuthenticated(), IsGerenteOrAdministradorOrResponsavel()]


# 🔹 ESTOQUE
# Nao usa ResponsavelOuAdminMixin: o escopo de Estoque e por loja
# (loja__responsavel), nao por campo responsavel proprio, e todos os
# metodos relevantes ja sao definidos localmente abaixo.
class EstoqueViewSet(viewsets.ModelViewSet):
    queryset = Estoque.objects.all()
    serializer_class = EstoqueSerializer
    permission_classes = [IsAuthenticated, IsGerenteOrAdministradorOrResponsavel]
    lookup_field = 'public_id'

    def get_serializer_class(self):
        if self.action == 'create':
            return EstoqueCreateSerializer
        if self.action in ['update', 'partial_update']:
            return EstoqueUpdateSerializer
        return EstoqueSerializer

    def get_queryset(self):
        user = self.request.user
        queryset = Estoque.objects.all()

        if is_gerente_ou_admin(user):
            return queryset

        return queryset.filter(loja__responsavel=user)

    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @action(detail=False, methods=['get'], url_path='baixos')
    def baixos(self, request):
        """Produtos no/abaixo do minimo, no escopo do usuario.

        Gerente/admin ve todas as lojas (visao centralizada); responsavel ve
        so as dele — o escopo ja vem do get_queryset.
        """
        estoques = self.get_queryset().baixos()
        return Response(EstoqueBaixoSerializer(estoques, many=True).data)

    def _validar_loja_do_responsavel(self, user, loja):
        if is_gerente_ou_admin(user):
            return

        if not loja or loja.responsavel_id != user.id:
            raise PermissionDenied("Voce so pode editar o estoque da sua loja.")

    def perform_create(self, serializer):
        self._validar_loja_do_responsavel(
            self.request.user,
            serializer.validated_data.get('loja')
        )
        serializer.save()

    def perform_update(self, serializer):
        loja = serializer.validated_data.get('loja', serializer.instance.loja)
        self._validar_loja_do_responsavel(self.request.user, loja)
        serializer.save()

    def perform_destroy(self, instance):
        self._validar_loja_do_responsavel(self.request.user, instance.loja)
        instance.delete()


# 🔹 MOVIMENTACAO DE ESTOQUE (historico auditavel, somente leitura)
class MovimentacaoEstoqueViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = MovimentacaoEstoqueSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'public_id'
    queryset = MovimentacaoEstoque.objects.none()  # so via get_queryset

    def get_queryset(self):
        qs = (
            MovimentacaoEstoque.objects
            .select_related('produto', 'loja_origem', 'loja_destino', 'usuario')
            .order_by('-created_at')
        )

        user = self.request.user
        if not is_gerente_ou_admin(user):
            minhas = Loja.objects.filter(responsavel=user)
            qs = qs.filter(Q(loja_origem__in=minhas) | Q(loja_destino__in=minhas))

        tipo = self.request.query_params.get('tipo')
        if tipo:
            qs = qs.filter(tipo=tipo)
        return qs


# 🔹 PRODUTO
class ProdutoViewSet(viewsets.ModelViewSet):
    queryset = Produto.objects.all().order_by('nome_produto')
    serializer_class = ProdutoSerializer
    lookup_field = 'public_id'

    def get_permissions(self):
        if self.action == 'list':
            # Catalogo interno; leitura exige login.
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsGerenteOrAdministrador()]


# 🔹 NOTIFICACAO
class NotificacaoViewSet(viewsets.ModelViewSet):
    serializer_class = NotificacaoSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'public_id'

    def get_queryset(self):
        return Notificacao.objects.filter(
            usuario=self.request.user
        ).order_by('-created_at')

    def create(self, request, *args, **kwargs):
        return Response(
            {"detail": "Notificações são criadas automaticamente pelo sistema."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED
        )

    @action(detail=True, methods=['patch'], url_path='marcar-lida')
    def marcar_lida(self, request, public_id=None):
        notificacao = self.get_object()
        notificacao.lida = True
        notificacao.save(update_fields=['lida', 'updated_at'])
        return Response({"ok": True})

    @action(detail=False, methods=['patch'], url_path='todas-lidas')
    def todas_lidas(self, request):
        self.get_queryset().update(lida=True)
        return Response({"ok": True})

    @action(detail=False, methods=['delete'], url_path='limpar')
    def limpar(self, request):
        self.get_queryset().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# 🔹 ITEM PEDIDO 
class ItemPedidoViewSet(ResponsavelOuAdminMixin,viewsets.ModelViewSet):
    queryset = ItemPedido.objects.all()
    serializer_class = ItemPedidoSerializer
    permission_classes = [IsAuthenticated,IsGerenteOrAdministradorOrResponsavel]
    lookup_field = 'public_id'

    def get_queryset(self):
        user = self.request.user

        if is_gerente_ou_admin(user):
            return ItemPedido.objects.all()

        # Mesma regra de tenancy do PedidoViewSet: escopo pela loja do usuario
        return ItemPedido.objects.filter(pedido__loja__responsavel=user)



# 🔹 PEDIDO 
class PedidoViewSet( viewsets.ModelViewSet):
    queryset = Pedido.objects.all().order_by('-data_pedido')
    serializer_class = PedidoSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'public_id'

    def get_serializer_class(self):
        if self.action == 'create':
            return PedidoCreateSerializer
        if self.action in ['update', 'partial_update']:
            return PedidoUpdateSerializer
        return PedidoSerializer

    def get_queryset(self):
        user = self.request.user
        queryset = Pedido.objects.all().order_by('-data_pedido')
        

        if not is_gerente_ou_admin(user):
            queryset = queryset.filter(loja__in=user.loja_set.all())

        status = self.request.query_params.get('status')
        data = self.request.query_params.get('data')
        loja = self.request.query_params.get('loja')

        if status:
            queryset = queryset.filter(status=status)

        if loja:
            queryset = queryset.filter(loja__public_id=loja)

        if data:
            data_inicio = make_aware(
                datetime.combine(
                    datetime.strptime(data, "%Y-%m-%d").date(),
                    time.min
                )
            )

            data_fim = make_aware(
                datetime.combine(
                    datetime.strptime(data, "%Y-%m-%d").date(),
                    time.max
                )
            )

            queryset = queryset.filter(
                data_pedido__range=(data_inicio, data_fim)
            )

        return queryset

    @action(detail=True, methods=['patch'], url_path='status')
    def atualizar_status(self, request, public_id=None):
        pedido = self.get_object()
        status_novo = request.data.get('status')

        status_validos = [choice[0] for choice in Pedido.Status.choices]
        if status_novo not in status_validos:
            return Response(
                {"status": f"Status inválido. Use: {', '.join(status_validos)}."},
                status=status.HTTP_400_BAD_REQUEST
            )

        status_anterior = pedido.status

        if status_anterior == Pedido.Status.ENTREGUE and status_novo == Pedido.Status.ENTREGUE:
            serializer = self.get_serializer(pedido)
            return Response(serializer.data)

        pedido.status = status_novo
        pedido.save(update_fields=['status', 'updated_at'])

        if status_novo == Pedido.Status.ENTREGUE and status_anterior != Pedido.Status.ENTREGUE:
            somar_itens_no_estoque(pedido)

        notificar_estoques_baixos_do_pedido(pedido, usuario_editor=request.user)

        serializer = self.get_serializer(pedido)
        return Response(serializer.data)


class VendaViewSet(viewsets.GenericViewSet):
    queryset = Pedido.objects.all().order_by('-data_pedido')
    serializer_class = VendaCreateSerializer
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pedido = serializer.save()

        return Response(
            {
                "detail": "Venda finalizada com sucesso.",
                "pedido": PedidoSerializer(pedido).data,
            },
            status=status.HTTP_201_CREATED,
        )

# 🔹 PREFERENCIAS DE NOTIFICACAO
class PreferenciaNotificacaoViewSet(viewsets.GenericViewSet):
    """GET/PATCH /api/v1/preferencias-notificacao/me/ — sempre do proprio usuario."""

    serializer_class = PreferenciaNotificacaoSerializer
    permission_classes = [IsAuthenticated]
    queryset = PreferenciaNotificacao.objects.none()  # rota so via action `me`

    @action(detail=False, methods=['get', 'patch'], url_path='me')
    def me(self, request):
        prefs, _ = PreferenciaNotificacao.objects.get_or_create(usuario=request.user)

        if request.method.lower() == 'patch':
            serializer = self.get_serializer(prefs, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)

        return Response(self.get_serializer(prefs).data)


# 🔹 USUÁRIO
class UsuarioViewSet(UserOuAdminMixin, viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UsuarioSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'], url_path='me')
    def me(self, request):
            user = request.user
            
            group = get_user_group_name(user)

            # Busca a loja vinculada (ajuste o filtro conforme seu banco)
            loja_vinculada = Loja.objects.filter(responsavel=user).first()

            return Response({
                "id": user.id,
                "first_name": user.first_name,
                "email": user.email,
                "group": group,
                "loja": {
                    "id": loja_vinculada.public_id,
                    "nome": loja_vinculada.nome_loja
                } if loja_vinculada else None
            })
    
    def create(self, request, *args, **kwargs):
        return Response(
            {"detail": "Use /users/registrar/ para criar usuários."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED
        )

    @action(
        detail=False,
        methods=['post'],
        permission_classes=[AllowAny],
        throttle_classes=[RegistroRateThrottle],
    )
    def registrar(self, request):
        """POST /api/v1/user/registrar/ — cria gerente. So gerente/admin usa.

        Nao existe mais cadastro publico. Responsavel nao se cria a mao: cada
        loja ganha o proprio login ao ser cadastrada, a partir do email dela.
        O endpoint segue AllowAny para responder 403 com explicacao em vez do
        401 seco do IsAuthenticated.
        """
        data = request.data
        tipo_usuario = data.get('tipo_usuario')

        requester_is_admin = bool(
            request.user
            and request.user.is_authenticated
            and is_gerente_ou_admin(request.user)
        )

        if not requester_is_admin:
            return Response(
                {"error": "Apenas um gerente/admin autenticado pode cadastrar usuarios."},
                status=status.HTTP_403_FORBIDDEN
            )

        if tipo_usuario != 'gerente':
            return Response(
                {"error": (
                    "So e possivel cadastrar gerente aqui. Cada loja recebe o "
                    "proprio acesso quando e cadastrada, usando o e-mail dela."
                )},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = self.get_serializer(data=data)
        if serializer.is_valid():
            user = serializer.save()

            from django.contrib.auth.models import Group
            user.groups.add(Group.objects.get(name='Gerente'))

            corpo = dict(serializer.data)
            corpo['detail'] = 'Conta criada.'
            return Response(corpo, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(
        detail=False,
        methods=['get'],
        url_path=r'confirmar/(?P<token>[^/]+)',
        permission_classes=[AllowAny],
    )
    def confirmar(self, request, token=None):
        """GET /api/v1/user/confirmar/<token>/ — ativa a conta do email."""
        try:
            user_id = validar_token_confirmacao(token)
        except signing.SignatureExpired:
            return Response(
                {"error": "Link de confirmacao expirado. Cadastre-se novamente."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except signing.BadSignature:
            return Response(
                {"error": "Link de confirmacao invalido."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = User.objects.filter(id=user_id).first()
        if not user:
            return Response(
                {"error": "Usuario nao encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not user.is_active:
            user.is_active = True
            user.save(update_fields=['is_active'])

        return Response({"detail": "Conta confirmada. Voce ja pode fazer login."})

    @action(
        detail=False,
        methods=['post'],
        url_path=r'definir-senha/(?P<token>[^/]+)',
        permission_classes=[AllowAny],
    )
    def definir_senha(self, request, token=None):
        """POST /api/v1/user/definir-senha/<token>/ — define a senha e ativa."""
        try:
            user_id = validar_token_senha(token)
        except signing.SignatureExpired:
            return Response(
                {"error": "Link expirado. Peca um novo em 'Esqueci a senha'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except signing.BadSignature:
            return Response(
                {"error": "Link invalido ou ja utilizado."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        senha = request.data.get('password')
        if not isinstance(senha, str):
            # JSON aceita numero/lista/objeto; os validators do Django chamam
            # .lower() e estouram AttributeError (500) num endpoint aberto.
            return Response(
                {"password": ["Informe a senha como texto."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = User.objects.filter(id=user_id).first()
        if not user:
            return Response(
                {"error": "Link invalido."}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            validate_password(senha, user)
        except ValidationError as erro:
            return Response(
                {"password": list(erro.messages)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(senha)
        user.is_active = True
        user.save(update_fields=['password', 'is_active'])
        return Response({"detail": "Senha definida. Voce ja pode entrar."})

    @action(
        detail=False,
        methods=['post'],
        url_path='esqueci-senha',
        permission_classes=[AllowAny],
        throttle_classes=[SenhaRateThrottle],
    )
    def esqueci_senha(self, request):
        """POST /api/v1/user/esqueci-senha/ — manda o link de definir senha.

        Responde 200 exista ou nao o email: responder 404 revelaria quais
        emails estao cadastrados.
        """
        email = request.data.get('email')
        if email is not None and not isinstance(email, str):
            # JSON aceita numero/lista/objeto; .strip() estouraria 500 aqui.
            return Response(
                {"email": ["Informe o e-mail como texto."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if email:
            user = User.objects.filter(email__iexact=email.strip()).first()
            # Conta inativa que nunca definiu senha e uma loja recem-criada cujo
            # link expirou: sem isso ela ficaria travada, sem como pedir outro.
            # Ja uma conta desativada de proposito tem senha utilizavel, entao
            # continua bloqueada.
            if user and (user.is_active or not user.has_usable_password()):
                enviar_email_definir_senha.delay(user.id)

        return Response(
            {"detail": "Se este email estiver cadastrado, enviamos o link."}
        )
