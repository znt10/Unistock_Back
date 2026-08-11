"""Envio de mensagens de texto via Evolution API (self-hosted, nao-oficial)."""

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def enviar_mensagem(telefone, texto):
    """Manda um texto simples pro numero informado.

    Nao levanta em caso de falha de rede/API — o bot nao deve derrubar o
    webhook por causa de indisponibilidade da Evolution API, so loga e segue.
    """
    if not settings.EVOLUTION_API_URL or not settings.EVOLUTION_API_KEY:
        logger.warning("Evolution API nao configurada; mensagem nao enviada.")
        return False

    url = f"{settings.EVOLUTION_API_URL}/message/sendText/{settings.EVOLUTION_INSTANCE}"
    try:
        resposta = requests.post(
            url,
            json={"number": telefone, "text": texto},
            headers={"apikey": settings.EVOLUTION_API_KEY},
            timeout=10,
        )
        resposta.raise_for_status()
        return True
    except requests.RequestException:
        logger.exception("Falha ao enviar mensagem via Evolution API para %s", telefone)
        return False
