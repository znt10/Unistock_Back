"""Canais de envio de notificacao.

Camada plugavel: hoje email; WhatsApp entra na fase 2 pela mesma interface.
O dispatcher (`despachar`) decide os canais do usuario — quando o model
PreferenciaNotificacao existir, a resolucao passa a ler as preferencias.
"""

from django.conf import settings
from django.core.mail import send_mail


class NotificationChannel:
    """Interface de canal: implementar `send` e retornar True se enviou."""

    def send(self, destinatario, titulo, mensagem, contexto=None):
        raise NotImplementedError


class EmailChannel(NotificationChannel):
    def send(self, destinatario, titulo, mensagem, contexto=None):
        if not destinatario.email:
            return False
        send_mail(
            titulo,
            mensagem,
            settings.DEFAULT_FROM_EMAIL,
            [destinatario.email],
            fail_silently=False,
        )
        return True


class WhatsAppChannel(NotificationChannel):
    """Stub da fase 2: sera implementado com a WhatsApp Cloud API (Meta),
    exigindo template aprovado. A interface ja esta pronta para plugar."""

    def send(self, destinatario, titulo, mensagem, contexto=None):
        raise NotImplementedError("WhatsAppChannel sera implementado na fase 2.")


def canais_do_usuario(usuario):
    # ponytail: email para todos por enquanto; trocar pela leitura de
    # PreferenciaNotificacao (email_ativo/whatsapp_ativo) quando o model existir.
    return [EmailChannel()]


def despachar(usuario, titulo, mensagem, contexto=None):
    """Envia pelos canais do usuario. Retorna quantos canais enviaram."""
    enviados = 0
    for canal in canais_do_usuario(usuario):
        try:
            if canal.send(usuario, titulo, mensagem, contexto):
                enviados += 1
        except NotImplementedError:
            continue
    return enviados
