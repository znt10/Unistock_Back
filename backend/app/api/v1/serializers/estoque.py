from rest_framework import serializers

from app.models import Estoque, Loja, MovimentacaoEstoque, Notificacao, Produto
from app.notifications import notificar_estoque_baixo, notificar_estoque_excedido


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
            "quantidade_maxima",
            "estado",
            "atualizado_em",
        ]


class EstoqueBaixoSerializer(serializers.ModelSerializer):
    """Leitura enxuta para o painel de estoque baixo (nomes ja resolvidos)."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    loja_id = serializers.UUIDField(source="loja.public_id", read_only=True)
    loja_nome = serializers.CharField(source="loja.nome_loja", read_only=True)
    produto_nome = serializers.CharField(source="produto.nome_produto", read_only=True)
    unidade_medida = serializers.CharField(
        source="produto.unidade_medida", read_only=True
    )

    class Meta:
        model = Estoque
        fields = [
            "id",
            "loja_id",
            "loja_nome",
            "produto_nome",
            "unidade_medida",
            "quantidade_atual",
            "quantidade_minima",
            "quantidade_maxima",
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

    def validate(self, data):
        """Teto sempre acima do minimo.

        O banco tambem garante isto (CheckConstraint), mas so a partir daqui
        sai um 400 explicando o campo em vez de um 500 do driver. As duas
        pontas existem de proposito: o bot e o /admin nao passam por aqui.
        """
        minima = data.get(
            "quantidade_minima", getattr(self.instance, "quantidade_minima", 0)
        )
        maxima = data.get(
            "quantidade_maxima", getattr(self.instance, "quantidade_maxima", None)
        )

        if maxima is None:
            raise serializers.ValidationError(
                {"quantidade_maxima": "Informe o maximo deste produto nesta loja."}
            )

        if maxima <= minima:
            raise serializers.ValidationError(
                {
                    "quantidade_maxima": (
                        f"O maximo ({maxima}) precisa ser maior que o minimo "
                        f"({minima})."
                    )
                }
            )

        return super().validate(data)


class EstoqueCreateSerializer(EstoqueWriteSerializer):
    """Serializer para criacao de estoque."""

    def create(self, validated_data):
        estoque = super().create(validated_data)
        request = self.context.get("request")
        editor = getattr(request, "user", None)
        notificar_estoque_baixo(estoque, usuario_editor=editor)
        notificar_estoque_excedido(estoque, usuario_editor=editor)
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

        editor = getattr(request, "user", None)

        if estoque.quantidade_minima > 0 and estoque.quantidade_atual > estoque.quantidade_minima:
            # Fim do episodio de estoque baixo: apaga lidas e nao lidas, para
            # que uma proxima queda gere notificacao nova (dedup por episodio).
            Notificacao.objects.filter(
                tipo="estoque_baixo",
                estoque=estoque,
            ).delete()
        else:
            notificar_estoque_baixo(estoque, usuario_editor=editor)

        # O excesso cuida do proprio ciclo (cria e apaga) dentro da funcao,
        # entao nao precisa do if/else acima.
        notificar_estoque_excedido(estoque, usuario_editor=editor)

        return estoque
