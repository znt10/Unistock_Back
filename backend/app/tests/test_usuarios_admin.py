from django.contrib.auth.models import Group, User
from django.test import TestCase
from rest_framework.test import APIClient

from app.models import Loja
from app.tests.fabricas import (
    criar_admin,
    criar_conta,
    criar_gerente,
    criar_responsavel,
)


class RegistrarSoAdminTests(TestCase):
    def setUp(self):
        self.conta = criar_conta()
        self.admin = criar_admin("admin@x.com")
        self.gerente = criar_gerente("ger@x.com", self.conta)

    def _payload(self, **extra):
        dados = {
            "first_name": "Novo Gerente",
            "email": "novoger@x.com",
            "password": "123456",
            "tipo_usuario": "gerente",
            # Gerente sem empresa nao enxerga nada: o registro exige a conta.
            "conta": str(self.conta.public_id),
        }
        dados.update(extra)
        return dados

    def test_admin_cria_gerente(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        resp = client.post("/api/v1/user/registrar/", self._payload(), format="json")
        self.assertEqual(resp.status_code, 201, resp.data)

        criado = User.objects.get(username="novoger@x.com")
        self.assertEqual(criado.perfil.conta_id, self.conta.id)

    def test_nao_cria_gerente_sem_empresa(self):
        """Um gerente orfao logaria num sistema vazio — melhor recusar."""
        client = APIClient()
        client.force_authenticate(self.admin)
        resp = client.post(
            "/api/v1/user/registrar/", self._payload(conta=""), format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn("conta", resp.data)

    def test_gerente_nao_cria_outro_gerente(self):
        """Mudanca intencional: antes gerente podia criar gerente."""
        client = APIClient()
        client.force_authenticate(self.gerente)
        resp = client.post("/api/v1/user/registrar/", self._payload(), format="json")
        self.assertEqual(resp.status_code, 403)


class EstruturaAdminTests(TestCase):
    def setUp(self):
        self.conta = criar_conta("Empresa do Zeca")
        self.admin = criar_admin("admin@x.com")
        self.gerente = criar_gerente("ger@x.com", self.conta, first_name="Zeca")
        self.responsavel_loja = criar_responsavel("loja@x.com", self.conta)
        Loja.objects.create(
            nome_loja="Loja A", cidade="Patos", endereco="Rua 1",
            conta=self.conta, responsavel=self.responsavel_loja,
        )

    def test_admin_ve_estrutura_completa(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        resp = client.get("/api/v1/user/estrutura/")
        self.assertEqual(resp.status_code, 200)
        # A arvore agora e por EMPRESA, nao por gerente: uma conta com dois
        # gerentes aparecia duas vezes no formato antigo, cada uma com um
        # pedaco das lojas.
        #
        # Nao se compara o TAMANHO da lista: todo banco nasce com a "Conta
        # padrao" que a migracao 0026 cria para adotar as categorias vindas
        # das migracoes antigas. Procurar a nossa e o certo aqui.
        empresa = next(c for c in resp.data if c["nome"] == "Empresa do Zeca")
        self.assertEqual(
            {m["nome"] for m in empresa["membros"]}, {"Zeca", "loja@x.com"}
        )
        self.assertEqual(len(empresa["lojas"]), 1)
        self.assertEqual(empresa["lojas"][0]["nome_loja"], "Loja A")

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
