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
def disparar_digests():
    """Roda no beat (a cada 15 min): dispara o digest de quem esta na hora.

    Envia quando: digest ativo, dia da semana marcado, horario escolhido ja
    passou e ainda nao houve digest hoje (ultimo_digest_em). Assim nao duplica
    no mesmo dia e recupera atraso se o beat ficar um tempo fora.
    """
    from django.utils import timezone as dj_tz

    from app.models import PreferenciaNotificacao

    agora = dj_tz.localtime(dj_tz.now())
    hoje = agora.date()
    dia_iso = str(agora.isoweekday())  # 1=segunda ... 7=domingo

    pendentes = PreferenciaNotificacao.objects.filter(
        digest_ativo=True,
        digest_horario__lte=agora.time(),
    ).exclude(ultimo_digest_em=hoje)

    disparados = 0
    for prefs in pendentes:
        if dia_iso not in prefs.digest_dias_semana.split(","):
            continue
        prefs.ultimo_digest_em = hoje
        prefs.save(update_fields=["ultimo_digest_em", "updated_at"])
        enviar_digest.delay(prefs.usuario_id)
        disparados += 1
    return disparados


@shared_task
def enviar_digest(user_id):
    """Um email com os produtos abaixo do minimo nas lojas do usuario."""
    from django.db.models import F

    from app.models import Estoque

    usuario = User.objects.filter(id=user_id).first()
    if not usuario:
        return False

    baixos = (
        Estoque.objects.filter(
            loja__responsavel=usuario,
            loja__ativo=True,
            quantidade_minima__gt=0,
            quantidade_atual__lte=F("quantidade_minima"),
        )
        .select_related("produto", "loja")
        .order_by("loja__nome_loja", "produto__nome_produto")
    )
    if not baixos:
        return False  # nada baixo, nada de email

    linhas = [
        f"- {e.produto.nome_produto} ({e.loja.nome_loja}): "
        f"{e.quantidade_atual} em estoque, minimo {e.quantidade_minima}"
        for e in baixos
    ]
    nome = usuario.first_name or usuario.username
    mensagem = (
        f"Ola, {nome}!\n\n"
        "Resumo do dia — produtos abaixo do estoque minimo:\n\n"
        + "\n".join(linhas)
        + "\n\nAcesse o Unistock para repor."
    )
    return despachar(usuario, "Resumo diario de estoque — Unistock", mensagem) > 0


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
