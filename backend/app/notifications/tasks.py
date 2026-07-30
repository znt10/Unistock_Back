"""Tasks Celery de notificacao (rodam no worker; sincronas nos testes)."""

import logging

from celery import shared_task
from django.conf import settings
from django.contrib.auth.models import User
from django.core import signing

from .channels import despachar

logger = logging.getLogger(__name__)

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
def enviar_email_definir_senha(user_id):
    """Manda o link de definir senha (1o acesso da loja ou 'esqueci a senha')."""
    from django.core.mail import send_mail

    from .tokens import gerar_token_senha

    usuario = User.objects.filter(id=user_id).first()
    if not usuario or not usuario.email:
        return False

    link = f"{settings.FRONTEND_URL}/redefinir-senha/{gerar_token_senha(usuario)}"
    mensagem = (
        "Ola!\n\n"
        "Para acessar o Unistock, defina a senha desta conta pelo link:\n"
        f"{link}\n\n"
        "O link vale por 3 dias e pode ser usado uma unica vez.\n"
        "Se voce nao pediu isso, ignore este email."
    )
    send_mail(
        "Defina a senha da sua conta no Unistock",
        mensagem,
        settings.DEFAULT_FROM_EMAIL,
        [usuario.email],
        fail_silently=False,
    )
    return True


def _enviar_pdf(destinatarios, assunto, corpo, nome_arquivo, pdf):
    """Um email com o PDF anexado. Envio direto: o destinatario e a loja/gerente,
    nao ha preferencia por usuario a respeitar aqui."""
    from django.core.mail import EmailMessage

    email = EmailMessage(
        assunto, corpo, settings.DEFAULT_FROM_EMAIL, list(destinatarios)
    )
    email.attach(nome_arquivo, pdf, "application/pdf")
    email.send(fail_silently=False)


@shared_task
def enviar_digest_lojas():
    """Resumo diario das 7h: um email por loja + um combinado pro gerente.

    Vai para o email DA LOJA (quem esta no turno le a caixa da loja), com o PDF
    do que esta abaixo do minimo. Gerentes/admins recebem um unico PDF com
    todas as lojas juntas. PDFs sao gerados em sequencia: o WeasyPrint consome
    bastante memoria e varios saem juntos as 7h.
    """
    from django.utils import timezone as dj_tz

    from app.models import Estoque
    from app.relatorios.estoque_baixo_pdf import gerar_estoque_baixo_pdf

    baixos = list(Estoque.objects.baixos())
    if not baixos:
        return 0

    hoje = dj_tz.localtime(dj_tz.now()).date()
    data_br = hoje.strftime("%d/%m/%Y")
    sufixo_arquivo = hoje.isoformat()
    enviados = 0

    # Um email por loja, para o email da propria loja.
    por_loja = {}
    for estoque in baixos:
        por_loja.setdefault(estoque.loja, []).append(estoque)

    for loja, itens in por_loja.items():
        if not loja.email:
            continue  # sem email cadastrado: entra so no combinado do gerente
        # Um SMTP recusado nao pode derrubar o digest do dia inteiro: sem isso,
        # a primeira loja com problema cancelava as seguintes e todos os
        # gerentes.
        try:
            pdf = gerar_estoque_baixo_pdf(
                itens, titulo=loja.nome_loja, subtitulo=f"Resumo de {data_br}"
            )
            _enviar_pdf(
                [loja.email],
                f"Estoque baixo — {loja.nome_loja} ({data_br})",
                (
                    f"Bom dia!\n\nSegue em anexo a lista de produtos abaixo do "
                    f"estoque minimo na loja {loja.nome_loja}.\n\n"
                    "Acesse o Unistock para repor."
                ),
                f"estoque_baixo_{sufixo_arquivo}.pdf",
                pdf,
            )
            enviados += 1
        except Exception:
            logger.exception("Falha no digest da loja %s", loja.nome_loja)

    # Um PDF combinado (todas as lojas) para cada gerente/admin. Aqui o
    # destinatario e uma pessoa, entao vale a preferencia de email dela.
    gerentes = list(
        User.objects.filter(
            groups__name__in=["Gerente", "Admin"], is_active=True
        )
        .exclude(email="")
        .exclude(preferencia_notificacao__email_ativo=False)
        .distinct()
    )
    if gerentes:
        pdf_geral = gerar_estoque_baixo_pdf(
            baixos, titulo="Todas as lojas", subtitulo=f"Resumo de {data_br}"
        )
        for gerente in gerentes:
            try:
                _enviar_pdf(
                    [gerente.email],
                    f"Estoque baixo — todas as lojas ({data_br})",
                    (
                        "Bom dia!\n\nSegue em anexo a lista de produtos abaixo do "
                        "estoque minimo em todas as lojas.\n\n"
                        "Acesse o Unistock para repor."
                    ),
                    f"estoque_baixo_todas_lojas_{sufixo_arquivo}.pdf",
                    pdf_geral,
                )
                enviados += 1
            except Exception:
                logger.exception("Falha no digest do gerente %s", gerente.email)

    return enviados
