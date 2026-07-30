from django.contrib.auth.models import Group, User
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from app.models import Categoria, Loja, Produto


class PedidoAPITestCase(APITestCase):

    def setUp(self):
        self.client = APIClient()

        # Criar grupos
        self.grupo_responsavel, _ = Group.objects.get_or_create(name='Responsavel')
        self.grupo_gerente, _ = Group.objects.get_or_create(name='Gerente')
        self.grupo_admin, _ = Group.objects.get_or_create(name='Admin')

        # Usuário responsável
        self.responsavel = User.objects.create_user(
            username='teste',
            password='123'
        )
        self.responsavel.groups.add(self.grupo_responsavel)

        # Usuário gerente
        self.gerente = User.objects.create_user(
            username='admin',
            password='123'
        )
        self.gerente.groups.add(self.grupo_gerente)

        # Usuário admin
        self.admin = User.objects.create_user(
            username='chefe@unistock.com',
            password='123'
        )
        self.admin.groups.add(self.grupo_admin)


        self.categoria = Categoria.objects.get_or_create(nome="Salgados grande")[0]
        self.produto = Produto.objects.create(
            nome_produto="coxinha",
            unidade_medida="QUILO",
            categoria=self.categoria,
        )
        # Loja
        self.loja = Loja.objects.create(
            nome_loja='Loja A',
            endereco='Rua 1',
            responsavel=self.responsavel
        )



    def test_admin_cadastra_gerente_que_ja_entra(self):
        """Unico cadastro que sobrou: admin criando gerente.

        A conta nasce ativa — nao ha mais confirmacao por email, porque nao ha
        mais cadastro aberto para confirmar. Loja nao passa por aqui: ganha o
        proprio acesso quando e cadastrada.

        Antes, gerente tambem podia criar outro gerente — agora e exclusivo
        do admin (ver test_usuarios_admin.py).
        """
        self.client.force_authenticate(user=self.admin)
        response = self.client.post("/api/v1/user/registrar/", {
            "email": "novo@email.com",
            "password": "SenhaForte#2026",
            "tipo_usuario": "gerente",
        })
        self.assertEqual(response.status_code, 201, response.data)
        self.client.force_authenticate(user=None)

        response = self.client.post("/login/", {
            "email": "novo@email.com",
            "password": "SenhaForte#2026",
        })
        self.assertEqual(response.status_code, 200, response.data)






    def test_login_sucesso(self):
        url = "/login/"

        data = {
            "email": "teste",
            "password": "123"
        }

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 200)

        # valida cookies JWT
        self.assertIn("access_token", response.cookies)
        self.assertIn("refresh_token", response.cookies)


    def test_fluxo_completo_gerente(self):
        # login como gerente
        self.client.force_authenticate(user=self.gerente)

        # cria produto
        url_produto = reverse('produto-list')

        produto_data = {
            "nome_produto": "Produto X",
            "unidade_medida": "UNIDADE",
            "categoria": str(self.categoria.public_id),
        }

        response = self.client.post(url_produto, produto_data)
        self.assertEqual(response.status_code, 201)

        # cria loja
        url_loja = reverse('loja-list')

        loja_data = {
            "nome_loja": "Loja Gerente",
            "cidade": "Patos",
            "endereco": "Rua 1",
            "responsavel": self.gerente.id
        }

        response = self.client.post(url_loja, loja_data)
        self.assertEqual(response.status_code, 201)

    def test_responsavel_cria_pedido(self):
        self.client.force_authenticate(user=self.responsavel)

        url = "/api/v1/pedidos/"

        data = {
            "loja": str(self.loja.public_id),
            "itens": [
                {
                    "produto": str(self.produto.public_id),
                    "quantidade": 2
                }
            ]
        }

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertIn("id", response.data)


    def test_user_nao_pode_criar_produto(self):
        self.client.force_authenticate(user=self.responsavel)


        url = reverse('produto-list')

        data = {
            "nome_produto": "Produto Teste",
            "unidade_medida": "UNIDADE",
            "categoria": str(self.categoria.public_id),
        }

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 403)

    def test_responsavel_nao_pode_criar_loja(self):
        self.client.force_authenticate(user=self.responsavel)

        url = reverse('loja-list')

        data = {
            "nome_loja": "Loja Teste",
            "endereco": "Rua 2",
            "responsavel": self.responsavel.id
        }

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 403)
