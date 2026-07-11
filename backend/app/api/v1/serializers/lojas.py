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
        ]

    def get_fields(self):
        fields = super().get_fields()
        fields["responsavel"].required = False
        fields["responsavel"].allow_null = True
        return fields
