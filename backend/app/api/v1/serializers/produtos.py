from rest_framework import serializers

from app.models import Categoria, Produto


class ProdutoSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
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
            "categoria",
            "categoria_nome",
            "gerente",
        ]
        extra_kwargs = {"gerente": {"required": False}}

    def validate_gerente(self, value):
        # Mesma regra de Loja/Categoria: quem PODE mexer e checado na view
        # (perform_update); aqui e so a regra de negocio.
        if value is not None and not value.groups.filter(name="Gerente").exists():
            raise serializers.ValidationError("Este usuario nao e um gerente.")
        return value

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

        return data
