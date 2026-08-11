from rest_framework import serializers

from app.models import Categoria
from app.permissions import is_admin, is_gerente


class CategoriaSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)

    class Meta:
        model = Categoria
        fields = ["id", "nome", "ordem", "gerente"]
        extra_kwargs = {"gerente": {"required": False}}

    def validate_nome(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Informe um nome para a categoria.")
        return value

    def validate_gerente(self, value):
        # Quem PODE mexer neste campo e checado na view (perform_update),
        # que responde 403 — aqui e so a regra de negocio (400): o valor tem
        # que ser de fato um Gerente.
        if value is not None and not value.groups.filter(name="Gerente").exists():
            raise serializers.ValidationError("Este usuario nao e um gerente.")
        return value

    def _gerente_efetivo(self, data):
        """O gerente que a linha vai ter DEPOIS de salva.

        Nao da pra so ler data.get("gerente"): campo nullable e required=False
        entra em validated_data como None mesmo quando o cliente nao mandou
        nada — "gerente" in data e sempre True. Por isso o cheque de "foi
        enviado?" usa initial_data (o corpo cru), igual a view (perform_create)
        ja faz. Quando quem cria e um Gerente e nao manda o campo, a view
        atribui ele mesmo DEPOIS desta validacao rodar; repete a mesma regra
        aqui, senao o cheque de nome duplicado compara contra o gerente
        errado (None) e deixa passar um choque que so estoura na constraint
        do banco.
        """
        if "gerente" in self.initial_data:
            return data.get("gerente")
        if self.instance:
            return self.instance.gerente

        request = self.context.get("request")
        if request and is_gerente(request.user) and not is_admin(request.user):
            return request.user
        return None

    def validate(self, data):
        nome = data.get("nome", getattr(self.instance, "nome", None))
        gerente = self._gerente_efetivo(data)

        if nome:
            existentes = Categoria.objects.filter(nome__iexact=nome, gerente=gerente)
            if self.instance:
                existentes = existentes.exclude(pk=self.instance.pk)
            if existentes.exists():
                raise serializers.ValidationError(
                    {"nome": "Ja existe uma categoria com este nome para este gerente."}
                )

        return data
