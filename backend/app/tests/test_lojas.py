from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework.test import APIClient, APITestCase

from app.models import Categoria, Loja, MovimentacaoEstoque, Produto
from app.tests.fabricas import criar_admin, criar_conta, criar_gerente


class LojaQuerysetEscopoTests(TestCase):
    def setUp(self):
        self.conta = criar_conta("Empresa A")
        self.conta_alheia = criar_conta("Empresa B")

        self.admin = criar_admin("admin@x.com")
        self.gerente = criar_gerente("ger@x.com", self.conta)
        self.colega = criar_gerente("colega@x.com", self.conta)
        self.outro_gerente = criar_gerente("ger2@x.com", self.conta_alheia)

        self.loja_dele = Loja.objects.create(
            nome_loja="Loja A", cidade="Patos", endereco="Rua 1",
            conta=self.conta,
        )
        self.loja_alheia = Loja.objects.create(
            nome_loja="Loja B", cidade="Patos", endereco="Rua 2",
            conta=self.conta_alheia,
        )

    def test_admin_ve_todas_as_lojas(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        resp = client.get("/api/v1/lojas/")
        nomes = {loja["nome_loja"] for loja in resp.data.get("results", resp.data)}
        self.assertEqual(nomes, {"Loja A", "Loja B"})

    def test_gerente_ve_so_as_proprias_lojas(self):
        client = APIClient()
        client.force_authenticate(self.gerente)
        resp = client.get("/api/v1/lojas/")
        nomes = {loja["nome_loja"] for loja in resp.data.get("results", resp.data)}
        self.assertEqual(nomes, {"Loja A"})

    def test_colega_da_mesma_empresa_ve_as_mesmas_lojas(self):
        """Dois gerentes numa empresa compartilham as lojas dela.

        No modelo antigo (Loja.gerente = pessoa) o colega via zero lojas: elas
        pertenciam a outra pessoa, nao a empresa.
        """
        client = APIClient()
        client.force_authenticate(self.colega)
        resp = client.get("/api/v1/lojas/")
        nomes = {loja["nome_loja"] for loja in resp.data.get("results", resp.data)}
        self.assertEqual(nomes, {"Loja A"})

    def test_empresa_da_loja_nao_muda_pelo_corpo_do_request(self):
        """`conta` e read_only: mandar outra empresa nao move a loja.

        Substitui o antigo 403 de "o gerente da loja nao pode ser alterado".
        A barreira ficou mais forte: nao depende de a view lembrar de checar,
        o campo simplesmente nao entra pelo serializer.
        """
        client = APIClient()
        client.force_authenticate(self.gerente)
        resp = client.patch(
            f"/api/v1/lojas/{self.loja_dele.public_id}/",
            {"conta": str(self.conta_alheia.public_id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.loja_dele.refresh_from_db()
        self.assertEqual(self.loja_dele.conta_id, self.conta.id)

    def test_gerente_cria_loja_na_propria_empresa(self):
        """A empresa vem de quem cria, e nao de um id no corpo."""
        client = APIClient()
        client.force_authenticate(self.gerente)
        resp = client.post(
            "/api/v1/lojas/",
            {
                "nome_loja": "Loja C",
                "cidade": "Patos",
                "endereco": "Rua 3",
                "conta": str(self.conta_alheia.public_id),
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(
            Loja.objects.get(nome_loja="Loja C").conta_id, self.conta.id
        )

    def test_admin_precisa_dizer_a_empresa_ao_criar_loja(self):
        """Admin nao tem conta propria: sem informar, e 400 e nao uma loja orfa."""
        client = APIClient()
        client.force_authenticate(self.admin)
        resp = client.post(
            "/api/v1/lojas/",
            {"nome_loja": "Loja D", "cidade": "Patos", "endereco": "Rua 4"},
            format="json",
        )

        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn("conta", resp.data)


class LojaDeleteTests(APITestCase):
    """DELETE /api/v1/lojas/<id>/ nao pode estourar 500 quando ha historico."""

    def setUp(self):
        self.conta = criar_conta()
        self.admin = criar_admin("admin")
        self.client.force_authenticate(self.admin)

        categoria = Categoria.objects.create(nome="Mercado", conta=self.conta)
        self.produto = Produto.objects.create(nome_produto="Coca", categoria=categoria, conta=self.conta)

    def test_nao_permite_excluir_loja_com_historico_de_movimentacao(self):
        loja = Loja.objects.create(
            nome_loja="Loja Com Historico", cidade="Patos", endereco="Rua 1",
            conta=self.conta,
        )
        MovimentacaoEstoque.objects.create(
            tipo=MovimentacaoEstoque.Tipo.ENTRADA,
            produto=self.produto,
            loja_destino=loja,
            quantidade=5,)

        response = self.client.delete(f"/api/v1/lojas/{loja.public_id}/")

        self.assertEqual(response.status_code, 409, response.data)
        self.assertIn("error", response.data)
        self.assertTrue(Loja.objects.filter(pk=loja.pk).exists())

    def test_permite_excluir_loja_sem_historico(self):
        loja = Loja.objects.create(
            nome_loja="Loja Sem Historico", cidade="Patos", endereco="Rua 2",
            conta=self.conta,
        )

        response = self.client.delete(f"/api/v1/lojas/{loja.public_id}/")

        self.assertEqual(response.status_code, 204, getattr(response, "data", None))
        self.assertFalse(Loja.objects.filter(pk=loja.pk).exists())
