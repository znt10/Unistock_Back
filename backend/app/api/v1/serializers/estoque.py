from rest_framework import serializers

from app.models import Estoque, Loja, MovimentacaoEstoque, Notificacao, Produto
from app.notifications import notificar_estoque_baixo


class EstoqueSerializer(serializers.ModelSerializer):
    """Serializer de leitura de estoque."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    produto = serializers.SlugRelatedField(slug_field="public_id", read_only=True)
    loja = serializers.SlugRelatedField(slug_field="public_id", read_only=True)
    atualizado_em = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = Estoque
        fields = [
            "id",
            "produto",
            "loja",
            "quantidade_atual",
            "quantidade_minima",
            "estado",
            "atualizado_em",
        ]


class EstoqueWriteSerializer(EstoqueSerializer):
    """Base para criacao/atualizacao de estoque."""

    produto = serializers.SlugRelatedField(
        slug_field="public_id",
        queryset=Produto.objects.all(),
    )
    loja = serializers.SlugRelatedField(
        slug_field="public_id",
        queryset=Loja.objects.all(),
    )


class EstoqueCreateSerializer(EstoqueWriteSerializer):
    """Serializer para criacao de estoque."""

    def create(self, validated_data):
        estoque = super().create(validated_data)
        request = self.context.get("request")
        notificar_estoque_baixo(
            estoque,
            usuario_editor=getattr(request, "user", None),
        )
        return estoque


class EstoqueUpdateSerializer(EstoqueWriteSerializer):
    """Serializer para atualizacao de estoque."""

    def update(self, instance, validated_data):
        quantidade_anterior = instance.quantidade_atual
        estoque = super().update(instance, validated_data)
        request = self.context.get("request")

        delta = estoque.quantidade_atual - quantidade_anterior
        if delta != 0:
            MovimentacaoEstoque.objects.create(
                tipo=MovimentacaoEstoque.Tipo.AJUSTE,
                produto=estoque.produto,
                loja_origem=estoque.loja,
                quantidade=delta,
                usuario=getattr(request, "user", None),
            )

        if estoque.quantidade_minima > 0 and estoque.quantidade_atual > estoque.quantidade_minima:
            chave_mensagem = (
                f"{estoque.produto.nome_produto} esta com estoque baixo na loja "
                f"{estoque.loja.nome_loja}."
            )
            # Fim do episodio de estoque baixo: apaga lidas e nao lidas, para
            # que uma proxima queda gere notificacao nova (dedup por episodio).
            Notificacao.objects.filter(
                tipo="estoque_baixo",
                mensagem__startswith=chave_mensagem,
            ).delete()
        else:
            notificar_estoque_baixo(
                estoque,
                usuario_editor=getattr(request, "user", None),
            )

        return estoque
