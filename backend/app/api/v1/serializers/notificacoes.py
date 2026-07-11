from rest_framework import serializers

from app.models import Notificacao


class NotificacaoSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    pedido = serializers.UUIDField(source="pedido.public_id", read_only=True)
    loja_id = serializers.UUIDField(source="loja.public_id", read_only=True)
    loja_nome = serializers.CharField(source="loja.nome_loja", read_only=True)
    criada_em = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = Notificacao
        fields = ["id", "pedido", "loja_id", "loja_nome", "tipo", "titulo", "mensagem", "lida", "criada_em"]
