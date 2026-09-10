from rest_framework import serializers

from app.models import Categoria, Produto


class ProdutoSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    # Somente leitura: a empresa do produto e a de quem cria, nunca um id
    # escolhido no corpo do request (ver views/conta.py).
    conta = serializers.SlugRelatedField(slug_field="nome", read_only=True)
    categoria = serializers.SlugRelatedField(
        slug_field="public_id",
        queryset=Categoria.objects.all(),
    )
    categoria_nome = serializers.ReadOnlyField(source="categoria.nome")

    class Meta:
        model = Produto
        fields = [
            "id",
            "nome_produto",
            "unidade_medida",
            "quantidade_por_embalagem",
            "estoque_minimo_sugerido",
            "estoque_maximo_sugerido",
            "categoria",
            "categoria_nome",
            "conta",
        ]

    def validate(self, data):
        unidade = data.get(
            "unidade_medida",
            getattr(self.instance, "unidade_medida", Produto.UnidadeMedida.UNIDADE),
        )
        quantidade_por_embalagem = data.get(
            "quantidade_por_embalagem",
            getattr(self.instance, "quantidade_por_embalagem", None),
        )

        if unidade not in (
            Produto.UnidadeMedida.CAIXA,
            Produto.UnidadeMedida.PACOTE,
        ):
            data["quantidade_por_embalagem"] = None
        elif quantidade_por_embalagem is not None and quantidade_por_embalagem <= 0:
            raise serializers.ValidationError(
                {"quantidade_por_embalagem": "Informe um valor maior que zero."}
            )

        estoque_minimo = data.get("estoque_minimo_sugerido")
        if estoque_minimo is not None and estoque_minimo < 0:
            raise serializers.ValidationError(
                {"estoque_minimo_sugerido": "O estoque minimo deve ser maior ou igual a zero."}
            )

        estoque_maximo = data.get(
            "estoque_maximo_sugerido",
            getattr(self.instance, "estoque_maximo_sugerido", None),
        )
        minimo_efetivo = (
            estoque_minimo
            if estoque_minimo is not None
            else getattr(self.instance, "estoque_minimo_sugerido", 0)
        )
        # Mesma regra do teto por loja, aplicada na sugestao: e dela que a
        # linha de estoque nasce quando um pedido chega com produto que a loja
        # ainda nao tinha. Sugestao invalida geraria linha invalida.
        if estoque_maximo is not None and estoque_maximo <= (minimo_efetivo or 0):
            raise serializers.ValidationError(
                {
                    "estoque_maximo_sugerido": (
                        "O maximo sugerido precisa ser maior que o minimo."
                    )
                }
            )

        return data
