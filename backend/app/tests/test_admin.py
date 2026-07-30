"""O /admin do Django nao passa pelo serializer: sem restricao propria aqui,
qualquer usuario aparecia no seletor de gerente da Loja."""

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Group, User
from django.test import RequestFactory, TestCase

from app.admin import LojaAdmin
from app.models import Loja


class LojaAdminGerenteTests(TestCase):
    def setUp(self):
        for nome in ("Gerente", "Responsavel"):
            Group.objects.get_or_create(name=nome)

        self.gerente = User.objects.create_user(username="ger@x.com", password="123456")
        self.gerente.groups.add(Group.objects.get(name="Gerente"))

        self.responsavel = User.objects.create_user(username="resp@x.com", password="123456")
        self.responsavel.groups.add(Group.objects.get(name="Responsavel"))

        self.loja_admin = LojaAdmin(Loja, AdminSite())
        self.request = RequestFactory().get("/admin/app/loja/add/")

    def test_seletor_de_gerente_so_lista_usuarios_do_grupo_gerente(self):
        campo_gerente = Loja._meta.get_field("gerente")

        formfield = self.loja_admin.formfield_for_foreignkey(
            campo_gerente, self.request
        )

        usuarios = list(formfield.queryset)
        self.assertIn(self.gerente, usuarios)
        self.assertNotIn(self.responsavel, usuarios)

    def test_outros_campos_de_usuario_nao_sao_restringidos(self):
        campo_responsavel = Loja._meta.get_field("responsavel")

        formfield = self.loja_admin.formfield_for_foreignkey(
            campo_responsavel, self.request
        )

        usuarios = list(formfield.queryset)
        self.assertIn(self.gerente, usuarios)
        self.assertIn(self.responsavel, usuarios)
