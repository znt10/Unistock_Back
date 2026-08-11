from django.contrib.auth.models import Group, User
from rest_framework.test import APITestCase

from app.models import Categoria, Loja


class CategoriaApiTests(APITestCase):
    def setUp(self):
        grupo_gerente, _ = Group.objects.get_or_create(name="Gerente")
        self.gerente = User.objects.create_user(username="ger", password="123456")
        self.gerente.groups.add(grupo_gerente)

        self.outro_gerente = User.objects.create_user(username="ger2", password="123456")
        self.outro_gerente.groups.add(grupo_gerente)

        self.responsavel = User.objects.create_user(username="resp", password="123456")
        Loja.objects.create(
            nome_loja="Loja do gerente",
            cidade="Patos",
            endereco="Rua A, 1",
            responsavel=self.responsavel,
            gerente=self.gerente,
        )

    def test_responsavel_le_o_catalogo_do_proprio_gerente(self):
        Categoria.objects.create(nome="Bebidas", ordem=0, gerente=self.gerente)
        self.client.force_authenticate(self.responsavel)

        response = self.client.get("/api/v1/categorias/")

        self.assertEqual(response.status_code, 200, response.data)
        nomes = {c["nome"] for c in response.data.get("results", response.data)}
        self.assertIn("Bebidas", nomes)

    def test_gerente_nao_ve_categoria_de_outro_gerente(self):
        Categoria.objects.create(nome="Bebidas", ordem=0, gerente=self.outro_gerente)
        self.client.force_authenticate(self.gerente)

        response = self.client.get("/api/v1/categorias/")

        self.assertEqual(response.status_code, 200, response.data)
        nomes = {c["nome"] for c in response.data.get("results", response.data)}
        self.assertNotIn("Bebidas", nomes)

    def test_responsavel_sem_loja_nao_ve_catalogo_de_ninguem(self):
        Categoria.objects.create(nome="Bebidas", ordem=0, gerente=self.gerente)
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
        self.assertEqual(categoria.gerente_id, self.gerente.id)

    def test_responsavel_nao_pode_criar_categoria(self):
        self.client.force_authenticate(self.responsavel)

        response = self.client.post(
            "/api/v1/categorias/", {"nome": "Bebidas"}, format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_nao_permite_nome_duplicado_do_mesmo_gerente(self):
        Categoria.objects.create(nome="Bebidas", gerente=self.gerente)
        self.client.force_authenticate(self.gerente)

        response = self.client.post(
            "/api/v1/categorias/", {"nome": "bebidas"}, format="json",
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("nome", response.data)

    def test_permite_nome_duplicado_entre_gerentes_diferentes(self):
        Categoria.objects.create(nome="Bebidas", gerente=self.outro_gerente)
        self.client.force_authenticate(self.gerente)

        response = self.client.post(
            "/api/v1/categorias/", {"nome": "Bebidas"}, format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)

    def test_gerente_nao_muda_gerente_da_categoria_depois_de_criada(self):
        categoria = Categoria.objects.create(nome="Bebidas", gerente=self.gerente)
        self.client.force_authenticate(self.gerente)

        response = self.client.patch(
            f"/api/v1/categorias/{categoria.public_id}/",
            {"gerente": self.outro_gerente.id},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
