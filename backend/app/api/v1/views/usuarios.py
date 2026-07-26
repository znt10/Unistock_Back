from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core import signing
from django.core.exceptions import ValidationError
from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from app.models import Loja
from app.notifications.tasks import (
    enviar_email_definir_senha,
    validar_token_confirmacao,
)
from app.notifications.tokens import validar_token_senha
from app.permissions import get_user_group_name, is_admin, is_gerente
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
            lojas_do_gerente = Loja.objects.filter(gerente=user)
            return User.objects.filter(
                Q(id=user.id) | Q(id__in=lojas_do_gerente.values("responsavel_id"))
            )

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

        serializer = self.get_serializer(data=data)
        if serializer.is_valid():
            user = serializer.save()

            from django.contrib.auth.models import Group
            user.groups.add(Group.objects.get(name='Gerente'))

            corpo = dict(serializer.data)
            corpo['detail'] = 'Conta criada.'
            return Response(corpo, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'], url_path='estrutura')
    def estrutura(self, request):
        """GET /api/v1/user/estrutura/ — arvore Gerente -> Lojas, so Admin.

        Existe para o dashboard nao montar essa arvore com N chamadas
        soltas (uma por gerente) no front.
        """
        if not is_admin(request.user):
            return Response(
                {"error": "Apenas admin acessa a estrutura."},
                status=status.HTTP_403_FORBIDDEN,
            )

        gerentes = (
            User.objects.filter(groups__name="Gerente")
            .distinct()
            .prefetch_related("lojas_gerenciadas__responsavel")
            .order_by("first_name", "email")
        )

        data = [
            {
                "id": gerente.id,
                "nome": gerente.first_name or gerente.email or gerente.username,
                "email": gerente.email,
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
                    for loja in gerente.lojas_gerenciadas.all()
                ],
            }
            for gerente in gerentes
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
