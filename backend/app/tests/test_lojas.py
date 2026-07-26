from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework.test import APIClient

from app.models import Loja


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
