import re

from rest_framework import serializers

from app.models import Loja


class LojaSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    responsavel_nome = serializers.CharField(
        source="responsavel.first_name",
        read_only=True,
    )

    class Meta:
        model = Loja
        fields = [
            "id",
            "nome_loja",
            "tipo",
            "cidade",
            "endereco",
            "responsavel",
            "responsavel_nome",
            "ativo",
            "telefone_whatsapp",
            "email",
        ]

    def validate_telefone_whatsapp(self, value):
        if not value:
            return None
        # Normaliza para apenas digitos (aceita +55 (83) 99999-8888).
        digitos = re.sub(r"\D", "", value)
        if len(digitos) < 10:
            raise serializers.ValidationError(
                "Informe o numero com DDD (minimo 10 digitos)."
            )
        return digitos

    def get_fields(self):
        fields = super().get_fields()
        fields["responsavel"].required = False
        fields["responsavel"].allow_null = True
        return fields
