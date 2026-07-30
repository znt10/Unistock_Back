from django.db import transaction
from rest_framework import serializers

from app.models import Estoque, ItemPedido, Loja, MovimentacaoEstoque, Pedido, Produto
from app.notifications import notificar_estoque_baixo


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
                MovimentacaoEstoque.objects.create(
                    tipo=MovimentacaoEstoque.Tipo.VENDA_PDV,
                    produto=produto,
                    loja_origem=estoque.loja,
                    quantidade=baixa,
                    usuario=user,
                )
                notificar_estoque_baixo(estoque, usuario_editor=user)

        return pedido
