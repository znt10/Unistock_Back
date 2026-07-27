from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework.test import APIClient

from app.models import Categoria, Estoque, Loja, Produto


class EstoqueEscopoGerenteTests(TestCase):
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
        categoria = Categoria.objects.get_or_create(nome="Salgados grande")[0]
        produto = Produto.objects.create(
            nome_produto="Coxinha",
            unidade_medida=Produto.UnidadeMedida.CAIXA,
            categoria=categoria,
        )
        self.estoque_dele = Estoque.objects.create(
            loja=self.loja_dele, produto=produto, quantidade_atual=5, quantidade_minima=2,
        )
        self.estoque_alheio = Estoque.objects.create(
            loja=self.loja_alheia, produto=produto, quantidade_atual=5, quantidade_minima=2,
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
