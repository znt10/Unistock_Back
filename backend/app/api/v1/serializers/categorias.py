from rest_framework import serializers

from app.models import Categoria


class CategoriaSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)

    class Meta:
        model = Categoria
        fields = ["id", "nome", "ordem"]

    def validate_nome(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Informe um nome para a categoria.")

        existentes = Categoria.objects.filter(nome__iexact=value)
        if self.instance:
            existentes = existentes.exclude(pk=self.instance.pk)
        if existentes.exists():
            raise serializers.ValidationError("Ja existe uma categoria com este nome.")

        return value
