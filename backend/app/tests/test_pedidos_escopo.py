from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework.test import APIClient

from app.models import ItemPedido, Loja, Pedido, Produto


class PedidoEscopoGerenteTests(TestCase):
    def setUp(self):
        for nome in ("Admin", "Gerente", "Responsavel"):
            Group.objects.get_or_create(name=nome)

        self.gerente = User.objects.create_user(username="ger@x.com", password="123456")
        self.gerente.groups.add(Group.objects.get(name="Gerente"))
        self.outro_gerente = User.objects.create_user(username="ger2@x.com", password="123456")
        self.outro_gerente.groups.add(Group.objects.get(name="Gerente"))

        self.loja_dele = Loja.objects.create(
            nome_loja="Loja A", cidade="Patos", endereco="Rua 1", gerente=self.gerente,
        )
        self.loja_alheia = Loja.objects.create(
            nome_loja="Loja B", cidade="Patos", endereco="Rua 2", gerente=self.outro_gerente,
        )
        produto = Produto.objects.create(
            nome_produto="Coxinha",
            unidade_medida=Produto.UnidadeMedida.CAIXA,
            categoria=Produto.Categoria.SALGADOS_GDE,
        )

        pedido_dele = Pedido.objects.create(responsavel=self.gerente, loja=self.loja_dele)
        ItemPedido.objects.create(
            pedido=pedido_dele, produto=produto, quantidade=2, responsavel=self.gerente,
        )
        pedido_alheio = Pedido.objects.create(responsavel=self.outro_gerente, loja=self.loja_alheia)
        ItemPedido.objects.create(
            pedido=pedido_alheio, produto=produto, quantidade=3, responsavel=self.outro_gerente,
        )

    def test_gerente_ve_so_pedidos_das_proprias_lojas(self):
        client = APIClient()
        client.force_authenticate(self.gerente)
        resp = client.get("/api/v1/pedidos/")
        itens = resp.data.get("results", resp.data)
        self.assertEqual(len(itens), 1)
        self.assertEqual(str(itens[0]["loja"]), str(self.loja_dele.public_id))

    def test_gerente_ve_so_itens_de_pedido_das_proprias_lojas(self):
        client = APIClient()
        client.force_authenticate(self.gerente)
        resp = client.get("/api/v1/itens-pedido/")
        itens = resp.data.get("results", resp.data)
        self.assertEqual(len(itens), 1)
