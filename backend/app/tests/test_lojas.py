from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework.test import APIClient, APITestCase

from app.models import Categoria, Loja, MovimentacaoEstoque, Produto


class LojaQuerysetEscopoTests(TestCase):
    def setUp(self):
        for nome in ("Admin", "Gerente", "Responsavel"):
            Group.objects.get_or_create(name=nome)

        self.admin = User.objects.create_user(username="admin@x.com", password="123456")
        self.admin.groups.add(Group.objects.get(name="Admin"))

        self.gerente = User.objects.create_user(username="ger@x.com", password="123456")
        self.gerente.groups.add(Group.objects.get(name="Gerente"))

        self.outro_gerente = User.objects.create_user(username="ger2@x.com", password="123456")
        self.outro_gerente.groups.add(Group.objects.get(name="Gerente"))

        self.loja_dele = Loja.objects.create(
            nome_loja="Loja A", cidade="Patos", endereco="Rua 1",
            gerente=self.gerente,
        )
        self.loja_alheia = Loja.objects.create(
            nome_loja="Loja B", cidade="Patos", endereco="Rua 2",
            gerente=self.outro_gerente,
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

    def test_so_admin_muda_gerente_da_loja(self):
        client = APIClient()
        client.force_authenticate(self.gerente)
        resp = client.patch(
            f"/api/v1/lojas/{self.loja_dele.public_id}/",
            {"gerente": self.outro_gerente.id},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_admin_muda_gerente_da_loja(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        resp = client.patch(
            f"/api/v1/lojas/{self.loja_dele.public_id}/",
            {"gerente": self.outro_gerente.id},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.loja_dele.refresh_from_db()
        self.assertEqual(self.loja_dele.gerente_id, self.outro_gerente.id)

    def test_admin_nao_pode_salvar_gerente_com_usuario_que_nao_e_gerente(self):
        """gerente aceita qualquer User na FK — quem restringe e validate_gerente."""
        responsavel = User.objects.create_user(username="resp@x.com", password="123456")
        responsavel.groups.add(Group.objects.get(name="Responsavel"))

        client = APIClient()
        client.force_authenticate(self.admin)
        resp = client.patch(
            f"/api/v1/lojas/{self.loja_dele.public_id}/",
            {"gerente": responsavel.id},
            format="json",
        )

        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn("gerente", resp.data)
        self.loja_dele.refresh_from_db()
        self.assertEqual(self.loja_dele.gerente_id, self.gerente.id)


class LojaDeleteTests(APITestCase):
    """DELETE /api/v1/lojas/<id>/ nao pode estourar 500 quando ha historico."""

    def setUp(self):
        grupo_admin, _ = Group.objects.get_or_create(name="Admin")
        self.admin = User.objects.create_user(username="admin", password="123456")
        self.admin.groups.add(grupo_admin)
        self.client.force_authenticate(self.admin)

        categoria = Categoria.objects.get_or_create(nome="Mercado")[0]
        self.produto = Produto.objects.create(nome_produto="Coca", categoria=categoria)

    def test_nao_permite_excluir_loja_com_historico_de_movimentacao(self):
        loja = Loja.objects.create(
            nome_loja="Loja Com Historico", cidade="Patos", endereco="Rua 1",
        )
        MovimentacaoEstoque.objects.create(
            tipo=MovimentacaoEstoque.Tipo.ENTRADA,
            produto=self.produto,
            loja_destino=loja,
            quantidade=5,
        )

        response = self.client.delete(f"/api/v1/lojas/{loja.public_id}/")

        self.assertEqual(response.status_code, 409, response.data)
        self.assertIn("error", response.data)
        self.assertTrue(Loja.objects.filter(pk=loja.pk).exists())

    def test_permite_excluir_loja_sem_historico(self):
        loja = Loja.objects.create(
            nome_loja="Loja Sem Historico", cidade="Patos", endereco="Rua 2",
        )

        response = self.client.delete(f"/api/v1/lojas/{loja.public_id}/")

        self.assertEqual(response.status_code, 204, getattr(response, "data", None))
        self.assertFalse(Loja.objects.filter(pk=loja.pk).exists())
