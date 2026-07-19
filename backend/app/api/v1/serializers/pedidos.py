from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from app.models import ItemPedido, Loja, Notificacao, Pedido, Produto
from app.notifications import notificar_estoques_baixos_do_pedido


class ItemPedidoSerializer(serializers.ModelSerializer):
    produto = serializers.SlugRelatedField(
        slug_field="public_id",
        queryset=Produto.objects.all(),
    )
    produto_nome = serializers.ReadOnlyField(source="produto.nome_produto")

    class Meta:
        model = ItemPedido
        fields = ["produto", "produto_nome", "quantidade"]


class PedidoSerializer(serializers.ModelSerializer):
    """Serializer de leitura de pedidos."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    loja = serializers.SlugRelatedField(slug_field="public_id", read_only=True)
    itens = ItemPedidoSerializer(many=True, read_only=True)
    status = serializers.CharField(read_only=True)
    data = serializers.SerializerMethodField()
    hora = serializers.SerializerMethodField()
    responsavel = serializers.ReadOnlyField(source="responsavel.username")

    class Meta:
        model = Pedido
        fields = [
            "id",
            "responsavel",
            "loja",
            "status",
            "data",
            "hora",
            "itens",
            "descricao",
        ]

    def get_data(self, obj):
        if not obj.data_pedido:
            return None
        return timezone.localtime(obj.data_pedido).strftime("%Y-%m-%d")

    def get_hora(self, obj):
        if not obj.data_pedido:
            return None
        return timezone.localtime(obj.data_pedido).strftime("%H:%M:%S")


class PedidoWriteSerializer(PedidoSerializer):
    """Base para criacao/atualizacao de pedidos."""

    loja = serializers.SlugRelatedField(
        slug_field="public_id",
        queryset=Loja.objects.all(),
    )
    itens = ItemPedidoSerializer(many=True)

    def validate(self, data):
        itens = data.get("itens")

        if not itens:
            raise serializers.ValidationError(
                {"itens": "O pedido precisa ter pelo menos um item."}
            )

        for item in itens:
            if item.get("quantidade", 0) <= 0:
                raise serializers.ValidationError(
                    {"itens": "A quantidade de cada item deve ser maior que zero."}
                )

        return data


class PedidoCreateSerializer(PedidoWriteSerializer):
    """Serializer para criacao de pedidos."""

    @transaction.atomic
    def create(self, validated_data):
        itens_data = validated_data.pop("itens")
        user = self.context["request"].user

        pedido = Pedido.objects.create(responsavel=user, **validated_data)

        for item in itens_data:
            ItemPedido.objects.create(
                pedido=pedido,
                responsavel=user,
                **item,
            )

        notificar_estoques_baixos_do_pedido(pedido, usuario_editor=user)

        gerentes = (
            User.objects.filter(groups__name__in=["Admin", "Gerente"])
            | User.objects.filter(is_superuser=True)
        ).distinct()

        Notificacao.objects.bulk_create([
            Notificacao(
                usuario=gerente,
                pedido=pedido,
                loja=pedido.loja,
                tipo="novo_pedido",
                titulo="Novo pedido recebido",
                mensagem=(
                    f"{user.first_name or user.username} criou um pedido para "
                    f"{pedido.loja.nome_loja}."
                ),
            )
            for gerente in gerentes
        ])

        Notificacao.objects.create(
            usuario=user,
            pedido=pedido,
            loja=pedido.loja,
            tipo="pedido_criado",
            titulo="Pedido criado com sucesso",
            mensagem=f"Seu pedido para {pedido.loja.nome_loja} foi enviado para analise.",
        )

        return pedido


class PedidoUpdateSerializer(PedidoWriteSerializer):
    """Serializer para atualizacao de pedidos."""

    def validate(self, data):
        itens = data.get("itens")

        if itens is None:
            return data

        for item in itens:
            if item.get("quantidade", 0) <= 0:
                raise serializers.ValidationError(
                    {"itens": "A quantidade de cada item deve ser maior que zero."}
                )

        return data

    @transaction.atomic
    def update(self, instance, validated_data):
        itens_data = validated_data.pop("itens", None)
        user = self.context["request"].user

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if itens_data is not None:
            instance.itens.all().delete()

            for item in itens_data:
                ItemPedido.objects.create(
                    pedido=instance,
                    responsavel=user,
                    **item,
                )

        notificar_estoques_baixos_do_pedido(instance, usuario_editor=user)

        return instance
