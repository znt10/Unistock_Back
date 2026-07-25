import re

from rest_framework import serializers

from app.models import PreferenciaNotificacao


class PreferenciaNotificacaoSerializer(serializers.ModelSerializer):
    """Preferencias de canal do usuario.

    Os campos de digest sairam: o resumo diario deixou de ser por usuario e
    passou a ser por loja (email da loja, 7h) — nao ha o que configurar aqui.
    """

    class Meta:
        model = PreferenciaNotificacao
        fields = [
            "email_ativo",
            "whatsapp_ativo",
            "telefone_whatsapp",
        ]

    def validate_telefone_whatsapp(self, valor):
        return re.sub(r"\D", "", str(valor or ""))
