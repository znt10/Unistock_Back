from django.test import TestCase
from rest_framework.test import APIClient

from app.models import Categoria, Estoque, Loja, Produto
from app.tests.fabricas import criar_conta, criar_gerente


class EstoqueEscopoContaTests(TestCase):
    """Duas empresas nao se enxergam; dois gerentes da mesma se enxergam."""

    def setUp(self):
        self.conta = criar_conta("Empresa A")
        self.conta_alheia = criar_conta("Empresa B")

        self.gerente = criar_gerente("ger@x.com", self.conta)
        # Segundo gerente na MESMA empresa: o caso que o modelo antigo (dono
        # = pessoa) nao conseguia representar.
        self.colega = criar_gerente("colega@x.com", self.conta)
        self.gerente_alheio = criar_gerente("ger2@x.com", self.conta_alheia)

        self.loja_dele = Loja.objects.create(
            nome_loja="Loja A", cidade="Patos", endereco="Rua 1", conta=self.conta,
        )
        self.loja_alheia = Loja.objects.create(
            nome_loja="Loja B", cidade="Patos", endereco="Rua 2",
            conta=self.conta_alheia,
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
        self.estoque_dele = Estoque.objects.create(
            loja=self.loja_dele, produto=produto, quantidade_atual=5, quantidade_minima=2, quantidade_maxima=999,)
        self.estoque_alheio = Estoque.objects.create(
            loja=self.loja_alheia, produto=produto_alheio,
            quantidade_atual=5, quantidade_minima=2, quantidade_maxima=999,)

    def test_colega_da_mesma_empresa_ve_o_mesmo_estoque(self):
        """O ganho da camada de Conta, impossivel no modelo anterior.

        O colega nao administra nenhuma loja diretamente — ele so pertence a
        mesma empresa. Antes, isso o deixava sem enxergar nada.
        """
        client = APIClient()
        client.force_authenticate(self.colega)
        resp = client.get("/api/v1/estoque/")
        itens = resp.data.get("results", resp.data)
        self.assertEqual(len(itens), 1)
        self.assertEqual(
            {str(item["loja"]) for item in itens}, {str(self.loja_dele.public_id)}
        )

    def test_gerente_ve_so_estoque_das_proprias_lojas(self):
        client = APIClient()
        client.force_authenticate(self.gerente)
        resp = client.get("/api/v1/estoque/")
        itens = resp.data.get("results", resp.data)
        lojas = {str(item["loja"]) for item in itens}
        self.assertEqual(len(itens), 1)
        self.assertEqual(lojas, {str(self.loja_dele.public_id)})

    def test_gerente_nao_edita_estoque_de_loja_alheia(self):
        client = APIClient()
        client.force_authenticate(self.gerente)
        resp = client.patch(
            f"/api/v1/estoque/{self.estoque_alheio.public_id}/",
            {"quantidade_atual": 1},
            format="json",
        )
        self.assertIn(resp.status_code, (403, 404))
