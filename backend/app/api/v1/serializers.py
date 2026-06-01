from django.contrib.auth.models import Group, User
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from app.models import Estoque, ItemPedido, Loja, Notificacao, Pedido, Produto
from app.notifications import (
    notificar_estoque_baixo,
    notificar_estoques_baixos_do_pedido,
)


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

        for gerente in gerentes:
            Notificacao.objects.create(
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


class VendaItemSerializer(serializers.Serializer):
    produto_id = serializers.CharField()
    quantidade = serializers.IntegerField(min_value=1)


class VendaCreateSerializer(serializers.Serializer):
    loja_id = serializers.CharField(required=False, allow_blank=True)
    itens = VendaItemSerializer(many=True)

    def _usuario_pode_vender_na_loja(self, user, loja):
        if (
            user.is_superuser
            or user.groups.filter(name="Admin").exists()
            or user.groups.filter(name="Gerente").exists()
        ):
            return True

        return loja.responsavel_id == user.id

    def _buscar_loja(self, loja_id):
        user = self.context["request"].user

        if loja_id:
            try:
                loja = Loja.objects.get(public_id=loja_id, ativo=True)
            except Loja.DoesNotExist as exc:
                raise serializers.ValidationError(
                    {"loja_id": "Loja nao encontrada ou inativa."}
                ) from exc

            if not self._usuario_pode_vender_na_loja(user, loja):
                raise serializers.ValidationError(
                    {"loja_id": "Voce nao pode registrar venda para esta loja."}
                )

            return loja

        lojas_usuario = Loja.objects.filter(responsavel=user, ativo=True)

        if lojas_usuario.count() == 1:
            return lojas_usuario.first()

        raise serializers.ValidationError(
            {"loja_id": "Informe a loja para registrar a venda."}
        )

    def validate(self, data):
        itens = data.get("itens") or []

        if not itens:
            raise serializers.ValidationError(
                {"itens": "A venda precisa ter pelo menos um item."}
            )

        loja = self._buscar_loja(data.get("loja_id"))
        quantidades_por_produto = {}
        produtos_por_id = {}

        for item in itens:
            produto_id = str(item["produto_id"]).strip()

            if not produto_id:
                raise serializers.ValidationError(
                    {"itens": "Informe o produto de todos os itens."}
                )

            try:
                produto = Produto.objects.get(public_id=produto_id)
            except Produto.DoesNotExist:
                try:
                    produto = Produto.objects.get(id=produto_id)
                except (Produto.DoesNotExist, ValueError) as exc:
                    raise serializers.ValidationError(
                        {"itens": f"Produto {produto_id} nao encontrado."}
                    ) from exc

            produtos_por_id[produto.id] = produto
            quantidades_por_produto[produto.id] = (
                quantidades_por_produto.get(produto.id, 0) + item["quantidade"]
            )

        data["loja"] = loja
        data["produtos_por_id"] = produtos_por_id
        data["quantidades_por_produto"] = quantidades_por_produto

        return data

    @transaction.atomic
    def create(self, validated_data):
        user = self.context["request"].user
        loja = validated_data["loja"]
        produtos_por_id = validated_data["produtos_por_id"]
        quantidades_por_produto = validated_data["quantidades_por_produto"]
        produto_ids = list(quantidades_por_produto.keys())

        estoques = (
            Estoque.objects.select_for_update()
            .select_related("produto", "loja")
            .filter(loja=loja, produto_id__in=produto_ids)
            .order_by("id")
        )
        estoques_por_produto = {}
        for estoque in estoques:
            estoques_por_produto.setdefault(estoque.produto_id, []).append(estoque)

        erros = []
        for produto_id, quantidade in quantidades_por_produto.items():
            produto = produtos_por_id[produto_id]
            estoques_do_produto = estoques_por_produto.get(produto_id, [])
            quantidade_disponivel = sum(
                estoque.quantidade_atual for estoque in estoques_do_produto
            )

            if not estoques_do_produto:
                erros.append(f"{produto.nome_produto}: sem estoque cadastrado.")
                continue

            if quantidade_disponivel < quantidade:
                erros.append(
                    f"{produto.nome_produto}: estoque insuficiente "
                    f"(disponivel {quantidade_disponivel}, solicitado {quantidade})."
                )

        if erros:
            raise serializers.ValidationError({"itens": erros})

        pedido = Pedido.objects.create(
            responsavel=user,
            loja=loja,
            status=Pedido.Status.ENTREGUE,
            descricao="Venda registrada pelo PDV",
        )

        for produto_id, quantidade in quantidades_por_produto.items():
            produto = produtos_por_id[produto_id]
            estoques_do_produto = estoques_por_produto[produto_id]

            ItemPedido.objects.create(
                pedido=pedido,
                produto=produto,
                quantidade=quantidade,
                responsavel=user,
            )

            quantidade_restante = quantidade
            for estoque in estoques_do_produto:
                if quantidade_restante <= 0:
                    break

                baixa = min(estoque.quantidade_atual, quantidade_restante)
                estoque.quantidade_atual -= baixa
                quantidade_restante -= baixa
                estoque.save(update_fields=["quantidade_atual", "updated_at"])
                notificar_estoque_baixo(estoque, usuario_editor=user)

        return pedido


class NotificacaoSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    pedido = serializers.UUIDField(source="pedido.public_id", read_only=True)
    loja_id = serializers.UUIDField(source="loja.public_id", read_only=True)
    loja_nome = serializers.CharField(source="loja.nome_loja", read_only=True)
    criada_em = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = Notificacao
        fields = ["id", "pedido", "loja_id", "loja_nome", "tipo", "titulo", "mensagem", "lida", "criada_em"]


class ProdutoSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)

    class Meta:
        model = Produto
        fields = [
            "id",
            "nome_produto",
            "unidade_medida",
            "quantidade_por_embalagem",
            "estoque_minimo_sugerido",
            "categoria",
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

        return data


class UsuarioSerializer(serializers.ModelSerializer):
    tipo_usuario = serializers.ChoiceField(
        choices=["responsavel", "gerente"],
        write_only=True,
    )

    class Meta:
        model = User
        fields = ["id", "first_name", "email", "password", "tipo_usuario"]
        extra_kwargs = {"password": {"write_only": True}}

    def validate_password(self, value):
        if len(value) < 6:
            raise serializers.ValidationError(
                "A senha deve conter pelo menos 6 caracteres."
            )
        return value

    def validate_email(self, value):
        value = value.lower()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Este email ja esta em uso.")
        return value

    def create(self, validated_data):
        senha = validated_data.pop("password")
        email = validated_data.get("email")
        tipo_usuario = validated_data.pop("tipo_usuario")

        user = User(**validated_data)
        user.set_password(senha)
        user.username = email
        user.email = email
        user.save()

        if tipo_usuario == "gerente":
            grupo, _ = Group.objects.get_or_create(name="Gerente")
        else:
            grupo, _ = Group.objects.get_or_create(name="Responsavel")

        user.groups.add(grupo)

        return user


class LojaSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    responsavel_nome = serializers.CharField(
        source="responsavel.first_name",
        read_only=True,
    )

    class Meta:
        model = Loja
        fields = [
            "id",
            "nome_loja",
            "tipo",
            "cidade",
            "endereco",
            "responsavel",
            "responsavel_nome",
            "ativo",
        ]

    def get_fields(self):
        fields = super().get_fields()
        fields["responsavel"].required = False
        fields["responsavel"].allow_null = True
        return fields


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
        estoque = super().update(instance, validated_data)
        request = self.context.get("request")

        if estoque.quantidade_minima > 0 and estoque.quantidade_atual > estoque.quantidade_minima:
            chave_mensagem = (
                f"{estoque.produto.nome_produto} esta com estoque baixo na loja "
                f"{estoque.loja.nome_loja}."
            )
            Notificacao.objects.filter(
                tipo="estoque_baixo",
                mensagem__startswith=chave_mensagem,
                lida=False,
            ).delete()
        else:
            notificar_estoque_baixo(
                estoque,
                usuario_editor=getattr(request, "user", None),
            )

        return estoque
