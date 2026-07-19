"""Tasks Celery de notificacao (rodam no worker; sincronas nos testes)."""

from celery import shared_task
from django.conf import settings
from django.contrib.auth.models import User
from django.core import signing

from .channels import despachar

SALT_CONFIRMACAO = "unistock-confirmacao-conta"
VALIDADE_TOKEN_SEGUNDOS = 60 * 60 * 24 * 3  # 3 dias


def gerar_token_confirmacao(user_id):
    return signing.dumps({"user_id": user_id}, salt=SALT_CONFIRMACAO)


def validar_token_confirmacao(token):
    """Retorna o user_id do token, ou levanta signing.BadSignature/SignatureExpired."""
    dados = signing.loads(
        token, salt=SALT_CONFIRMACAO, max_age=VALIDADE_TOKEN_SEGUNDOS
    )
    return dados["user_id"]


@shared_task
def enviar_email_confirmacao(user_id):
    usuario = User.objects.filter(id=user_id).first()
    if not usuario or usuario.is_active:
        return False

    link = f"{settings.FRONTEND_URL}/confirmar-conta/{gerar_token_confirmacao(usuario.id)}"
    nome = usuario.first_name or usuario.username
    mensagem = (
        f"Ola, {nome}!\n\n"
        f"Confirme sua conta no Unistock clicando no link:\n{link}\n\n"
        "O link vale por 3 dias. Se voce nao criou esta conta, ignore este email."
    )
    return despachar(usuario, "Confirme sua conta no Unistock", mensagem) > 0


@shared_task
def enviar_alerta_estoque_baixo(estoque_id, usuario_ids):
    from app.models import Estoque

    estoque = (
        Estoque.objects.select_related("produto", "loja")
        .filter(id=estoque_id)
        .first()
    )
    if not estoque:
        return 0

    mensagem = (
        f"{estoque.produto.nome_produto} esta com estoque baixo na loja "
        f"{estoque.loja.nome_loja}. Atual: {estoque.quantidade_atual}. "
        f"Minimo: {estoque.quantidade_minima}."
    )
    enviados = 0
    for usuario in User.objects.filter(id__in=usuario_ids):
        enviados += despachar(usuario, "Estoque baixo — Unistock", mensagem)
    return enviados
