from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework.test import APIClient

from app.models import Categoria, ItemPedido, Loja, Pedido, Produto
from app.tests.fabricas import criar_conta, criar_gerente


class PedidoEscopoGerenteTests(TestCase):
    def setUp(self):
        self.conta = criar_conta("Empresa A")
        self.conta_alheia = criar_conta("Empresa B")

        self.gerente = criar_gerente("ger@x.com", self.conta)
        self.outro_gerente = criar_gerente("ger2@x.com", self.conta_alheia)

        self.loja_dele = Loja.objects.create(
            nome_loja="Loja A", cidade="Patos", endereco="Rua 1", conta=self.conta,
        )
        self.loja_alheia = Loja.objects.create(
            nome_loja="Loja B", cidade="Patos", endereco="Rua 2", conta=self.conta_alheia,
        )
        categoria = Categoria.objects.create(nome="Salgados grande", conta=self.conta)
        produto = Produto.objects.create(
            nome_produto="Coxinha",
            unidade_medida=Produto.UnidadeMedida.CAIXA,
            categoria=categoria,
            conta=self.conta,
        )
        categoria_alheia = Categoria.objects.create(
            nome="Salgados grande", conta=self.conta_alheia
        )
        produto_alheio = Produto.objects.create(
            nome_produto="Coxinha",
            unidade_medida=Produto.UnidadeMedida.CAIXA,
            categoria=categoria_alheia,
            conta=self.conta_alheia,
        )

        pedido_dele = Pedido.objects.create(responsavel=self.gerente, loja=self.loja_dele)
        ItemPedido.objects.create(
            pedido=pedido_dele, produto=produto, quantidade=2, responsavel=self.gerente,
        )
        pedido_alheio = Pedido.objects.create(responsavel=self.outro_gerente, loja=self.loja_alheia)
        ItemPedido.objects.create(
            pedido=pedido_alheio, produto=produto_alheio, quantidade=3, responsavel=self.outro_gerente,
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
