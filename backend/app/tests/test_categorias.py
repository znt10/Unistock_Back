from django.contrib.auth.models import Group, User
from rest_framework.test import APITestCase

from app.models import Categoria


class CategoriaApiTests(APITestCase):
    def setUp(self):
        grupo_gerente, _ = Group.objects.get_or_create(name="Gerente")
        self.gerente = User.objects.create_user(username="ger", password="123456")
        self.gerente.groups.add(grupo_gerente)

        self.responsavel = User.objects.create_user(username="resp", password="123456")

    def test_qualquer_autenticado_le_a_lista(self):
        Categoria.objects.create(nome="Bebidas", ordem=0)
        self.client.force_authenticate(self.responsavel)

        response = self.client.get("/api/v1/categorias/")

        self.assertEqual(response.status_code, 200, response.data)
        nomes = {c["nome"] for c in response.data.get("results", response.data)}
        self.assertIn("Bebidas", nomes)

    def test_gerente_cria_categoria(self):
        self.client.force_authenticate(self.gerente)

        response = self.client.post(
            "/api/v1/categorias/", {"nome": "Bebidas"}, format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(Categoria.objects.filter(nome="Bebidas").exists())

    def test_responsavel_nao_pode_criar_categoria(self):
        self.client.force_authenticate(self.responsavel)

        response = self.client.post(
            "/api/v1/categorias/", {"nome": "Bebidas"}, format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_nao_permite_nome_duplicado(self):
        Categoria.objects.create(nome="Bebidas")
        self.client.force_authenticate(self.gerente)

        response = self.client.post(
            "/api/v1/categorias/", {"nome": "bebidas"}, format="json",
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("nome", response.data)
