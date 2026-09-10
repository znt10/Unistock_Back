from rest_framework import serializers

from app.models import Categoria


class CategoriaSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    conta = serializers.SlugRelatedField(slug_field="nome", read_only=True)

    class Meta:
        model = Categoria
        fields = ["id", "nome", "ordem", "conta"]

    def validate_nome(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Informe um nome para a categoria.")
        return value

    def validate(self, data):
        """Nome unico dentro da empresa (a constraint do banco diz o mesmo).

        A conta nunca vem do corpo: na criacao ela e a do usuario logado
        (a view passa em perform_create) e na edicao e a que a linha ja tem.
        Isso substituiu um _gerente_efetivo() que precisava adivinhar o dono
        futuro a partir do initial_data para nao comparar contra o dono errado.
        """
        nome = data.get("nome", getattr(self.instance, "nome", None))
        if not nome:
            return data

        conta = self.instance.conta if self.instance else self.context.get("conta")

        existentes = Categoria.objects.filter(nome__iexact=nome)
        existentes = (
            existentes.filter(conta=conta) if conta else existentes.none()
        )
        if self.instance:
            existentes = existentes.exclude(pk=self.instance.pk)

        if existentes.exists():
            raise serializers.ValidationError(
                {"nome": "Ja existe uma categoria com este nome nesta empresa."}
            )

        return data
