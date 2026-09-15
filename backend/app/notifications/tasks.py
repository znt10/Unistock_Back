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
    do que esta abaixo do minimo E do que passou do maximo — falta e sobra sao
    a mesma conversa na hora de decidir o pedido do dia. Gerentes/admins recebem um unico PDF com
    todas as lojas juntas. PDFs sao gerados em sequencia: o WeasyPrint consome
    bastante memoria e varios saem juntos as 7h.
    """
    from django.utils import timezone as dj_tz

    from app.models import Estoque
    from app.relatorios.estoque_baixo_pdf import gerar_estoque_baixo_pdf

    baixos = list(Estoque.objects.baixos())
    excedidos = list(Estoque.objects.excedidos())
    if not baixos and not excedidos:
        return 0

    excedidos_por_loja = {}
    for estoque in excedidos:
        excedidos_por_loja.setdefault(estoque.loja_id, []).append(estoque)

    hoje = dj_tz.localtime(dj_tz.now()).date()
    data_br = hoje.strftime("%d/%m/%Y")
    sufixo_arquivo = hoje.isoformat()
    enviados = 0

    # Um email por loja, para o email da propria loja.
    por_loja = {}
    for estoque in baixos:
        por_loja.setdefault(estoque.loja, []).append(estoque)

    # Loja que so tem sobra (nada faltando) tambem precisa receber o email:
    # sem isto, o unico aviso de produto perto de estragar seria o sininho.
    for loja_excedida in excedidos:
        por_loja.setdefault(loja_excedida.loja, [])

    for loja, itens in por_loja.items():
        if not loja.email:
            continue  # sem email cadastrado: entra so no combinado do gerente
        # Um SMTP recusado nao pode derrubar o digest do dia inteiro: sem isso,
        # a primeira loja com problema cancelava as seguintes e todos os
        # gerentes.
        try:
            pdf = gerar_estoque_baixo_pdf(
                itens,
                titulo=loja.nome_loja,
                subtitulo=f"Resumo de {data_br}",
                excedidos=excedidos_por_loja.get(loja.id, []),
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

    # Um PDF combinado para cada gerente/admin, com as lojas DA EMPRESA dele.
    # Aqui o destinatario e uma pessoa, entao vale a preferencia de email dela.
    # Antes da camada de Conta este PDF trazia todas as lojas do banco, ou
    # seja: o gerente de uma empresa recebia o estoque das outras por email.
    destinatarios = list(
        User.objects.filter(
            groups__name__in=["Gerente", "Admin"], is_active=True
        )
        .exclude(email="")
        .exclude(preferencia_notificacao__email_ativo=False)
        .select_related("perfil__conta")
        .distinct()
    )
    if not destinatarios:
        return enviados

    por_conta = {}
    for estoque in baixos:
        por_conta.setdefault(estoque.loja.conta_id, []).append(estoque)

    excedidos_por_conta = {}
    for estoque in excedidos:
        excedidos_por_conta.setdefault(estoque.loja.conta_id, []).append(estoque)

    # Um PDF por recorte, e nao um por pessoa: duas pessoas da mesma empresa
    # recebem o mesmo anexo, e o WeasyPrint e caro demais para gerar duas
    # vezes o mesmo documento as 7h.
    pdfs = {}

    def pdf_do_recorte(conta_id, titulo, itens, sobras):
        if conta_id not in pdfs:
            pdfs[conta_id] = gerar_estoque_baixo_pdf(
                itens,
                titulo=titulo,
                subtitulo=f"Resumo de {data_br}",
                excedidos=sobras,
            )
        return pdfs[conta_id]

    for destinatario in destinatarios:
        perfil = getattr(destinatario, "perfil", None)
        if perfil:
            itens = por_conta.get(perfil.conta_id, [])
            sobras = excedidos_por_conta.get(perfil.conta_id, [])
            if not itens and not sobras:
                continue  # empresa sem falta e sem sobra hoje
            titulo = perfil.conta.nome
            chave = perfil.conta_id
        else:
            # Sem perfil e no grupo de gerencia = dono da plataforma: ve tudo.
            itens, sobras, titulo, chave = baixos, excedidos, "Todas as lojas", None

        try:
            _enviar_pdf(
                [destinatario.email],
                f"Estoque baixo — {titulo} ({data_br})",
                (
                    "Bom dia!\n\nSegue em anexo a lista de produtos abaixo do "
                    f"estoque minimo em {titulo}.\n\n"
                    "Acesse o Unistock para repor."
                ),
                f"estoque_baixo_{sufixo_arquivo}.pdf",
                pdf_do_recorte(chave, titulo, itens, sobras),
            )
            enviados += 1
        except Exception:
            logger.exception("Falha no digest de %s", destinatario.email)

    return enviados
