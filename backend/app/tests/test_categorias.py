from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from app.models import Categoria, Loja
from app.tests.fabricas import criar_conta, criar_gerente, criar_responsavel


class CategoriaApiTests(APITestCase):
    def setUp(self):
        self.conta = criar_conta("Empresa A")
        self.conta_alheia = criar_conta("Empresa B")

        self.gerente = criar_gerente("ger", self.conta)
        # Mesma empresa do self.gerente: e o cenario que o modelo antigo (dono
        # = pessoa) nao sabia representar.
        self.colega = criar_gerente("colega", self.conta)
        self.outro_gerente = criar_gerente("ger2", self.conta_alheia)

        self.responsavel = criar_responsavel("resp", self.conta)
        Loja.objects.create(
            nome_loja="Loja do gerente",
            cidade="Patos",
            endereco="Rua A, 1",
            responsavel=self.responsavel,
            conta=self.conta,
        )

    def test_colega_da_mesma_empresa_ve_a_categoria(self):
        """O ganho da camada de Conta: catalogo compartilhado na empresa."""
        Categoria.objects.create(nome="Bebidas", ordem=0, conta=self.conta)
        self.client.force_authenticate(self.colega)

        response = self.client.get("/api/v1/categorias/")

        self.assertEqual(response.status_code, 200, response.data)
        nomes = {c["nome"] for c in response.data.get("results", response.data)}
        self.assertIn("Bebidas", nomes)

    def test_responsavel_le_o_catalogo_da_propria_empresa(self):
        Categoria.objects.create(nome="Bebidas", ordem=0, conta=self.conta)
        self.client.force_authenticate(self.responsavel)

        response = self.client.get("/api/v1/categorias/")

        self.assertEqual(response.status_code, 200, response.data)
        nomes = {c["nome"] for c in response.data.get("results", response.data)}
        self.assertIn("Bebidas", nomes)

    def test_gerente_nao_ve_categoria_de_outro_gerente(self):
        Categoria.objects.create(nome="Bebidas", ordem=0, conta=self.conta_alheia)
        self.client.force_authenticate(self.gerente)

        response = self.client.get("/api/v1/categorias/")

        self.assertEqual(response.status_code, 200, response.data)
        nomes = {c["nome"] for c in response.data.get("results", response.data)}
        self.assertNotIn("Bebidas", nomes)

    def test_usuario_sem_empresa_nao_ve_catalogo_de_ninguem(self):
        Categoria.objects.create(nome="Bebidas", ordem=0, conta=self.conta)
        sem_loja = User.objects.create_user(username="sememprego", password="123456")
        self.client.force_authenticate(sem_loja)

        response = self.client.get("/api/v1/categorias/")

        self.assertEqual(response.status_code, 200, response.data)
        nomes = {c["nome"] for c in response.data.get("results", response.data)}
        self.assertNotIn("Bebidas", nomes)

    def test_gerente_cria_categoria(self):
        self.client.force_authenticate(self.gerente)

        response = self.client.post(
            "/api/v1/categorias/", {"nome": "Bebidas"}, format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        categoria = Categoria.objects.get(nome="Bebidas")
        self.assertEqual(categoria.conta_id, self.conta.id)

    def test_responsavel_nao_pode_criar_categoria(self):
        self.client.force_authenticate(self.responsavel)

        response = self.client.post(
            "/api/v1/categorias/", {"nome": "Bebidas"}, format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_nao_permite_nome_duplicado_na_mesma_empresa(self):
        Categoria.objects.create(nome="Bebidas", conta=self.conta)
        self.client.force_authenticate(self.gerente)

        response = self.client.post(
            "/api/v1/categorias/", {"nome": "bebidas"}, format="json",
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("nome", response.data)

    def test_permite_nome_duplicado_entre_empresas_diferentes(self):
        Categoria.objects.create(nome="Bebidas", conta=self.conta_alheia)
        self.client.force_authenticate(self.gerente)

        response = self.client.post(
            "/api/v1/categorias/", {"nome": "Bebidas"}, format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)

    def test_nao_da_para_mudar_a_empresa_da_categoria_pelo_corpo(self):
        """A empresa nao e mais um campo que o cliente possa mandar.

        Antes existia um 403 explicito para isto. Agora `conta` e read_only no
        serializer: o valor enviado e simplesmente ignorado, e a linha continua
        na empresa em que nasceu. E uma barreira mais forte, nao mais fraca —
        nao depende de a view lembrar de checar.
        """
        categoria = Categoria.objects.create(nome="Bebidas", conta=self.conta)
        self.client.force_authenticate(self.gerente)

        response = self.client.patch(
            f"/api/v1/categorias/{categoria.public_id}/",
            {"conta": str(self.conta_alheia.public_id)},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        categoria.refresh_from_db()
        self.assertEqual(categoria.conta_id, self.conta.id)
