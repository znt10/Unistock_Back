from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView
from django.http import HttpRequest, HttpResponse

from app.models import Loja
from app.relatorios.pedidos_pdf import gerar_relatorio_pedidos_pdf

User = get_user_model()

permission_classes = [IsAuthenticated]


def get_user_group_name(user):
    if user.is_superuser or user.groups.filter(name="Admin").exists():
        return "Admin"

    group = user.groups.first()
    return group.name if group else None


def relatorio_pdf(request: HttpRequest,) -> HttpResponse:
    periodo = request.GET.get("periodo", "dia")
 
    if periodo not in ("dia", "semana", "mes"):
        periodo = "dia"
 
    return gerar_relatorio_pedidos_pdf(periodo)
 
 

class CookieTokenRefreshView(TokenRefreshView):
    def post(self, request, *args, **kwargs):
        refresh_token = request.COOKIES.get("refresh_token") or request.data.get("refresh")

        if not refresh_token:
            return Response(
                {"detail": "Refresh token nao encontrado no cookie."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            serializer = TokenRefreshSerializer(data={"refresh": refresh_token})
            serializer.is_valid(raise_exception=True)
        except TokenError as exc:
            raise InvalidToken(exc.args[0])

        # Token renovado vai apenas no cookie HTTP-only, nunca no corpo.
        response = Response(
            {"detail": "Token atualizado."},
            status=status.HTTP_200_OK,
        )

        access_token = serializer.validated_data.get("access")
        if access_token:
            response.set_cookie(
                key="access_token",
                value=access_token,
                httponly=True,
                secure=not settings.DEBUG,
                samesite="Lax",
                path="/",
                max_age=int(api_settings.ACCESS_TOKEN_LIFETIME.total_seconds()),
            )

        return response


class LoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        email = request.data.get("email")
        password = request.data.get("password")

        user = authenticate(username=email, password=password)

        if not user:
            return Response(
                {"error": "Credenciais invalidas"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        refresh = RefreshToken.for_user(user)
        access = refresh.access_token
        role = get_user_group_name(user)

        if role is None:
            return Response(
                {
                    "error": (
                        "Usuario sem grupo. Adicione o usuario ao grupo "
                        "Gerente ou Responsavel."
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        loja_vinculada = Loja.objects.filter(responsavel=user).first()

        # Tokens vao apenas nos cookies HTTP-only abaixo — nunca no corpo,
        # para nao ficarem acessiveis ao JavaScript (roubo via XSS).
        response = Response(
            {
                "message": "Login realizado com sucesso",
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "first_name": user.first_name,
                    "group": role,
                    "loja": {
                        "id": loja_vinculada.public_id,
                        "nome": loja_vinculada.nome_loja,
                    }
                    if loja_vinculada
                    else None,
                },
            }
        )

        cookie_args = {
            "httponly": True,
            "secure": not settings.DEBUG,
            "samesite": "Lax",
            "path": "/",
        }

        response.set_cookie(
            key="access_token",
            value=str(access),
            max_age=int(access.lifetime.total_seconds()),
            **cookie_args,
        )
        response.set_cookie(
            key="refresh_token",
            value=str(refresh),
            max_age=int(refresh.lifetime.total_seconds()),
            **cookie_args,
        )
        response.set_cookie(
            key="role",
            value=role,
            max_age=int(refresh.lifetime.total_seconds()),
            **cookie_args,
        )

        return response


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @method_decorator(csrf_exempt)
    def post(self, request):
        response = Response({"message": "Logout realizado com sucesso"})

        response.delete_cookie("access_token", path="/", samesite="Lax")
        response.delete_cookie("refresh_token", path="/", samesite="Lax")
        response.delete_cookie("role", path="/", samesite="Lax")

        return response
