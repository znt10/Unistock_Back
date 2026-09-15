from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from app.services.estoque_teto import conferir_teto
from app.models import Caixa, ItemPedido, Loja, Notificacao, Pedido, Produto
from app.services.fabrica import fabrica_da_conta, segue_fluxo_fabrica
from app.notifications import notificar_estoques_baixos_do_pedido

MENSAGEM_UM_PRODUTO = "Um pedido tem um produto só. Faça um pedido para cada produto."


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
    numero = serializers.IntegerField(source="id", read_only=True)
    loja = serializers.SlugRelatedField(slug_field="public_id", read_only=True)
    loja_nome = serializers.ReadOnlyField(source="loja.nome_loja")
    itens = ItemPedidoSerializer(many=True, read_only=True)
    status = serializers.CharField(read_only=True)
    data = serializers.SerializerMethodField()
    hora = serializers.SerializerMethodField()
    responsavel = serializers.ReadOnlyField(source="responsavel.username")
    da_fabrica = serializers.BooleanField(read_only=True)
    caixas_total = serializers.SerializerMethodField()
    caixas_chegaram = serializers.SerializerMethodField()

    class Meta:
        model = Pedido
        fields = [
            "id",
            "numero",
            "responsavel",
            "loja",
            "loja_nome",
            "status",
            "data",
            "hora",
            "itens",
            "descricao",
            "da_fabrica",
            "caixas_total",
            "caixas_chegaram",
        ]

    def get_data(self, obj):
        if not obj.data_pedido:
            return None
        return timezone.localtime(obj.data_pedido).strftime("%Y-%m-%d")

    def get_hora(self, obj):
        if not obj.data_pedido:
            return None
        return timezone.localtime(obj.data_pedido).strftime("%H:%M:%S")

    def get_caixas_total(self, obj):
        # Vem anotado do PedidoViewSet, sem N+1. A contagem direta cobre o
        # pedido recem-criado, que nao passou pelo queryset anotado.
        valor = getattr(obj, "caixas_total_anotado", None)
        return obj.caixas.count() if valor is None else valor

    def get_caixas_chegaram(self, obj):
        valor = getattr(obj, "caixas_chegaram_anotado", None)
        if valor is not None:
            return valor
        return obj.caixas.exclude(situacao=Caixa.Situacao.A_CAMINHO).count()


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

        if len(itens) > 1:
            raise serializers.ValidationError({"itens": MENSAGEM_UM_PRODUTO})

        for item in itens:
            if item.get("quantidade", 0) <= 0:
                raise serializers.ValidationError(
                    {"itens": "A quantidade de cada item deve ser maior que zero."}
                )

        return data


class PedidoCreateSerializer(PedidoWriteSerializer):
    """Serializer para criacao de pedidos."""

    # Nao e campo do modelo: e a resposta ao aviso de excesso. Write-only
    # porque nao faz sentido nenhum devolve-lo na leitura do pedido.
    confirmar_excesso = serializers.BooleanField(
        write_only=True, required=False, default=False
    )

    class Meta(PedidoWriteSerializer.Meta):
        fields = PedidoWriteSerializer.Meta.fields + ["confirmar_excesso"]

    def validate(self, data):
        data = super().validate(data)

        produto = data["itens"][0]["produto"]
        if segue_fluxo_fabrica(produto):
            if data["loja"].tipo == Loja.Tipo.FABRICA:
                raise serializers.ValidationError(
                    {"loja": "A fábrica não faz pedido de produto da fábrica."}
                )
            # Vai direto para Pedido.objects.create(**validated_data).
            data["da_fabrica"] = True

        conferir_teto(
            data["loja"],
            data["itens"],
            confirmado=data.get("confirmar_excesso", False),
        )
        return data

    @transaction.atomic
    def create(self, validated_data):
        validated_data.pop("confirmar_excesso", None)
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

        # Quem e avisado: a gerencia DESTA empresa, mais o superuser (dono da
        # plataforma, que nao pertence a conta nenhuma). Antes da camada de
        # Conta isto pegava todo Gerente/Admin do sistema, entao um pedido de
        # uma empresa aparecia na caixa de notificacao das outras.
        gerentes = (
            User.objects.filter(
                groups__name__in=["Admin", "Gerente"],
                perfil__conta_id=pedido.loja.conta_id,
            )
            | User.objects.filter(is_superuser=True)
        ).distinct()

        destinatarios = {gerente.id: gerente for gerente in gerentes}
        if pedido.da_fabrica:
            # A fabrica e quem separa: sem isto ela so descobria o pedido
            # abrindo a fila.
            fabrica = fabrica_da_conta(pedido.loja.conta_id)
            if fabrica and fabrica.responsavel_id:
                destinatarios.setdefault(fabrica.responsavel_id, fabrica.responsavel)

        Notificacao.objects.bulk_create([
            Notificacao(
                usuario=destinatario,
                pedido=pedido,
                loja=pedido.loja,
                tipo="novo_pedido",
                titulo="Novo pedido recebido",
                mensagem=(
                    f"{user.first_name or user.username} criou um pedido para "
                    f"{pedido.loja.nome_loja}."
                ),
            )
            for destinatario in destinatarios.values()
        ])

        destino = "a fábrica" if pedido.da_fabrica else "analise"
        Notificacao.objects.create(
            usuario=user,
            pedido=pedido,
            loja=pedido.loja,
            tipo="pedido_criado",
            titulo="Pedido criado com sucesso",
            mensagem=f"Seu pedido para {pedido.loja.nome_loja} foi enviado para {destino}.",
        )

        return pedido


class PedidoUpdateSerializer(PedidoWriteSerializer):
    """Serializer para atualizacao de pedidos."""

    def validate(self, data):
        pedido = self.instance
        if pedido and pedido.da_fabrica and pedido.status != Pedido.Status.PENDENTE:
            # Mudar o pedido depois de impresso deixaria etiqueta sobrando ou
            # faltando.
            raise serializers.ValidationError(
                {"status": "Pedido da fábrica só pode ser editado enquanto está pendente."}
            )

        itens = data.get("itens")

        if itens is None:
            return data

        if len(itens) > 1:
            raise serializers.ValidationError({"itens": MENSAGEM_UM_PRODUTO})

        for item in itens:
            if item.get("quantidade", 0) <= 0:
                raise serializers.ValidationError(
                    {"itens": "A quantidade de cada item deve ser maior que zero."}
                )

        if pedido and itens and segue_fluxo_fabrica(itens[0]["produto"]) != pedido.da_fabrica:
            raise serializers.ValidationError(
                {"itens": "Para trocar o produto, cancele e faça um pedido novo."}
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
