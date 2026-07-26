"""A loja como login: o cadastro de usuarios nao pode roubar o acesso da loja."""

from django.contrib.auth.models import Group, User
from rest_framework.test import APITestCase

from app.models import Loja


class RegistroNaoRoubaLojaTests(APITestCase):
    """O cadastro publico nao pode reescrever o acesso de uma loja.

    /user/registrar/ e AllowAny. Antes, mandar tipo_usuario=responsavel com o
    id_loja sobrescrevia Loja.responsavel: a loja perdia o proprio login e
    quem cadastrou passava a enxergar o estoque dela.
    """

    def setUp(self):
        self.loja = Loja.objects.create(
            nome_loja='Alvo', cidade='Patos', endereco='Rua 1',
            email='alvo@unistock.com',
        )
        from app.api.v1.serializers.lojas import criar_acesso_da_loja
        self.acesso = criar_acesso_da_loja(self.loja)

    def test_cadastro_anonimo_nao_troca_o_responsavel_da_loja(self):
        response = self.client.post(
            '/api/v1/user/registrar/',
            {
                'username': 'invasor@email.com',
                'email': 'invasor@email.com',
                'password': 'SenhaForte#2026',
                'tipo_usuario': 'responsavel',
                'id_loja': str(self.loja.public_id),
            },
            format='json',
        )

        self.loja.refresh_from_db()
        self.assertEqual(self.loja.responsavel_id, self.acesso.id)
        self.assertNotEqual(response.status_code, 500)

    def test_anonimo_nao_cadastra_ninguem(self):
        response = self.client.post(
            '/api/v1/user/registrar/',
            {
                'username': 'qualquer@email.com', 'email': 'qualquer@email.com',
                'password': 'SenhaForte#2026', 'tipo_usuario': 'responsavel',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username='qualquer@email.com').exists())

    def test_gerente_nao_cria_responsavel_a_mao(self):
        """Responsavel nasce so pela loja. Cadastrar a mao voltaria ao modelo antigo."""
        admin = User.objects.create_user(username='chefe@unistock.com', password='Chefe#2026')
        admin.groups.add(Group.objects.get_or_create(name='Gerente')[0])
        self.client.force_authenticate(user=admin)

        response = self.client.post(
            '/api/v1/user/registrar/',
            {
                'username': 'novo@email.com', 'email': 'novo@email.com',
                'password': 'SenhaForte#2026', 'tipo_usuario': 'responsavel',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username='novo@email.com').exists())
