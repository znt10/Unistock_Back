import re

from rest_framework import serializers

from app.models import PreferenciaNotificacao


class PreferenciaNotificacaoSerializer(serializers.ModelSerializer):
    class Meta:
        model = PreferenciaNotificacao
        fields = [
            "email_ativo",
            "whatsapp_ativo",
            "telefone_whatsapp",
            "digest_ativo",
            "digest_horario",
            "digest_dias_semana",
        ]

    def validate_telefone_whatsapp(self, valor):
        return re.sub(r"\D", "", str(valor or ""))

    def validate_digest_dias_semana(self, valor):
        dias = [d for d in str(valor or "").split(",") if d.strip()]
        if not all(d.strip() in {"1", "2", "3", "4", "5", "6", "7"} for d in dias):
            raise serializers.ValidationError(
                "Use dias de 1 (segunda) a 7 (domingo), separados por virgula."
            )
        return ",".join(sorted({d.strip() for d in dias}))
