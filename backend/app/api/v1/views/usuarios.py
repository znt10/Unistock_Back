from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core import signing
from django.core.exceptions import ValidationError
from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from app.models import Conta, Loja, PerfilUsuario
from app.notifications.tasks import (
    enviar_email_definir_senha,
    validar_token_confirmacao,
)
from app.notifications.tokens import ContaInexistente, validar_token_senha
from app.permissions import (
    get_conta_do_usuario,
    get_user_group_name,
    is_admin,
    is_gerente,
    tipo_da_loja_para_interface,
)
from ..serializers import UsuarioSerializer
from ..throttles import RegistroRateThrottle, SenhaRateThrottle


# 🔹 USUÁRIO
class UsuarioViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UsuarioSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        if is_admin(user):
            return User.objects.all()

        if is_gerente(user):
            conta = get_conta_do_usuario(user)
            if not conta:
                return User.objects.filter(id=user.id)

            # Os colegas de empresa (o outro gerente inclusive) e os acessos
            # das lojas dela. Antes so aparecia ele mesmo e os responsaveis
            # das lojas atribuidas a ele — dois gerentes da mesma empresa nao
            # se enxergavam.
            return User.objects.filter(
                Q(perfil__conta=conta)
                | Q(id__in=conta.lojas.values("responsavel_id"))
            ).distinct()

        return User.objects.filter(id=user.id)

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
                    "nome": loja_vinculada.nome_loja,
                    "tipo": tipo_da_loja_para_interface(loja_vinculada),
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
        """POST /api/v1/user/registrar/ — cria gerente. So ADMIN usa.

        Nao existe mais cadastro publico. Responsavel nao se cria a mao: cada
        loja ganha o proprio login ao ser cadastrada, a partir do email dela.
        O endpoint segue AllowAny para responder 403 com explicacao em vez do
        401 seco do IsAuthenticated.

        Antes desta mudanca, qualquer gerente tambem podia criar outro
        gerente (is_gerente_ou_admin). Agora e exclusivo do Admin: gerente
        deixou de ter privilegio de administracao do sistema, so das
        proprias lojas.
        """
        data = request.data
        tipo_usuario = data.get('tipo_usuario')

        requester_is_admin = bool(
            request.user
            and request.user.is_authenticated
            and is_admin(request.user)
        )

        if not requester_is_admin:
            return Response(
                {"error": "Apenas um admin autenticado pode cadastrar usuarios."},
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

        # Gerente sem empresa nao enxerga nada depois da camada de Conta —
        # criar um assim seria entregar um login inutil e um suporte a mais.
        # try/except e nao so o filter: um public_id malformado estoura
        # ValueError no conversor do UUIDField antes de virar consulta, e isso
        # sairia como 500 no lugar de um 400 explicando o campo.
        try:
            conta = Conta.objects.filter(public_id=data.get("conta")).first()
        except (ValidationError, ValueError, TypeError):
            conta = None

        if not conta:
            return Response(
                {"conta": "Informe a empresa (conta) a que este gerente pertence."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(data=data)
        if serializer.is_valid():
            user = serializer.save()

            from django.contrib.auth.models import Group
            user.groups.add(Group.objects.get(name='Gerente'))
            PerfilUsuario.objects.create(user=user, conta=conta)

            corpo = dict(serializer.data)
            corpo['conta'] = str(conta.public_id)
            corpo['detail'] = 'Conta criada.'
            return Response(corpo, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'], url_path='estrutura')
    def estrutura(self, request):
        """GET /api/v1/user/estrutura/ — arvore Conta -> {membros, lojas}, so Admin.

        Existe para o dashboard nao montar essa arvore com N chamadas
        soltas no front.

        Era Gerente -> Lojas. Com a empresa no meio, uma conta com dois
        gerentes aparecia duas vezes na tela, cada uma com um pedaco das
        lojas — e as lojas sem gerente nao apareciam em lugar nenhum.
        """
        if not is_admin(request.user):
            return Response(
                {"error": "Apenas admin acessa a estrutura."},
                status=status.HTTP_403_FORBIDDEN,
            )

        contas = Conta.objects.prefetch_related(
            "membros__user", "lojas__responsavel"
        ).order_by("nome")

        data = [
            {
                "id": str(conta.public_id),
                "nome": conta.nome,
                "ativo": conta.ativo,
                "membros": [
                    {
                        "id": membro.user_id,
                        "nome": (
                            membro.user.first_name
                            or membro.user.email
                            or membro.user.username
                        ),
                        "email": membro.user.email,
                    }
                    for membro in conta.membros.all()
                ],
                "lojas": [
                    {
                        "id": str(loja.public_id),
                        "nome_loja": loja.nome_loja,
                        "responsavel": (
                            {
                                "id": loja.responsavel_id,
                                "email": loja.responsavel.email,
                            }
                            if loja.responsavel_id
                            else None
                        ),
                    }
                    for loja in conta.lojas.all()
                ],
            }
            for conta in contas
        ]

        return Response(data)

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
        except ContaInexistente:
            # Nao e o mesmo problema que "ja utilizado", e nao tem a mesma
            # saida: nao adianta pedir "esqueci a senha" para uma conta que
            # nao existe. O acesso da loja volta quando o gerente salva o
            # cadastro dela (ver serializers/lojas.py).
            return Response(
                {"error": (
                    "Esta conta nao existe mais. Peca ao gerente para abrir a "
                    "loja em Editar e salvar: o acesso e recriado e um novo "
                    "link chega por email."
                )},
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
