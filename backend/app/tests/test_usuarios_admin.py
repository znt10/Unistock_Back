from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework.test import APIClient

from app.models import Loja


class RegistrarSoAdminTests(TestCase):
    def setUp(self):
        for nome in ("Admin", "Gerente", "Responsavel"):
            Group.objects.get_or_create(name=nome)
        self.admin = User.objects.create_user(username="admin@x.com", password="123456")
        self.admin.groups.add(Group.objects.get(name="Admin"))
        self.gerente = User.objects.create_user(username="ger@x.com", password="123456")
        self.gerente.groups.add(Group.objects.get(name="Gerente"))

    def _payload(self):
        return {
            "first_name": "Novo Gerente",
            "email": "novoger@x.com",
            "password": "123456",
            "tipo_usuario": "gerente",
        }

    def test_admin_cria_gerente(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        resp = client.post("/api/v1/user/registrar/", self._payload(), format="json")
        self.assertEqual(resp.status_code, 201)

    def test_gerente_nao_cria_outro_gerente(self):
        """Mudanca intencional: antes gerente podia criar gerente."""
        client = APIClient()
        client.force_authenticate(self.gerente)
        resp = client.post("/api/v1/user/registrar/", self._payload(), format="json")
        self.assertEqual(resp.status_code, 403)


class EstruturaAdminTests(TestCase):
    def setUp(self):
        for nome in ("Admin", "Gerente", "Responsavel"):
            Group.objects.get_or_create(name=nome)
        self.admin = User.objects.create_user(username="admin@x.com", password="123456")
        self.admin.groups.add(Group.objects.get(name="Admin"))
        self.gerente = User.objects.create_user(
            username="ger@x.com", password="123456", first_name="Zeca"
        )
        self.gerente.groups.add(Group.objects.get(name="Gerente"))
        self.responsavel_loja = User.objects.create_user(username="loja@x.com", password="123456")
        self.responsavel_loja.groups.add(Group.objects.get(name="Responsavel"))
        Loja.objects.create(
            nome_loja="Loja A", cidade="Patos", endereco="Rua 1",
            gerente=self.gerente, responsavel=self.responsavel_loja,
        )

    def test_admin_ve_estrutura_completa(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        resp = client.get("/api/v1/user/estrutura/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["nome"], "Zeca")
        self.assertEqual(len(resp.data[0]["lojas"]), 1)
        self.assertEqual(resp.data[0]["lojas"][0]["nome_loja"], "Loja A")

    def test_gerente_nao_acessa_estrutura(self):
        client = APIClient()
        client.force_authenticate(self.gerente)
        resp = client.get("/api/v1/user/estrutura/")
        self.assertEqual(resp.status_code, 403)

    def test_gerente_nao_lista_todos_os_usuarios(self):
        client = APIClient()
        client.force_authenticate(self.gerente)
        resp = client.get("/api/v1/user/")
        ids = {u["id"] for u in resp.data.get("results", resp.data)}
        # Gerente ve so ele mesmo + responsaveis das proprias lojas.
        self.assertIn(self.gerente.id, ids)
        self.assertIn(self.responsavel_loja.id, ids)
        self.assertNotIn(self.admin.id, ids)
