from rest_framework import serializers

from app.models import MovimentacaoEstoque


class MovimentacaoEstoqueSerializer(serializers.ModelSerializer):
    """Leitura do historico de movimentacoes (auditoria)."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    produto_nome = serializers.CharField(source="produto.nome_produto", read_only=True)
    loja_origem_nome = serializers.SerializerMethodField()
    loja_destino_nome = serializers.SerializerMethodField()
    usuario_nome = serializers.SerializerMethodField()
    data = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = MovimentacaoEstoque
        fields = [
            "id",
            "tipo",
            "produto_nome",
            "loja_origem_nome",
            "loja_destino_nome",
            "quantidade",
            "usuario_nome",
            "data",
        ]

    def get_loja_origem_nome(self, obj):
        return obj.loja_origem.nome_loja if obj.loja_origem else None

    def get_loja_destino_nome(self, obj):
        return obj.loja_destino.nome_loja if obj.loja_destino else None

    def get_usuario_nome(self, obj):
        if not obj.usuario:
            return None
        return obj.usuario.first_name or obj.usuario.username
