"""A loja como login: criacao e manutencao do acesso da loja."""

from django.contrib.auth.models import Group, User
from rest_framework.test import APITestCase

from app.models import Loja


class CriarLojaCriaAcessoTests(APITestCase):
    def setUp(self):
        Group.objects.get_or_create(name='Responsavel')
        grupo_gerente, _ = Group.objects.get_or_create(name='Gerente')
        self.gerente = User.objects.create_user(username='ger', password='123')
        self.gerente.groups.add(grupo_gerente)
        self.client.force_authenticate(self.gerente)

    def _payload(self, **extra):
        dados = {
            'nome_loja': 'Lapa', 'cidade': 'Patos', 'endereco': 'Rua 1',
            'email': 'lapa@unistock.com',
        }
        dados.update(extra)
        return dados

    def test_loja_com_email_ganha_login_proprio(self):
        from django.core import mail

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post('/api/v1/lojas/', self._payload(), format='json')

        self.assertEqual(response.status_code, 201, response.data)
        loja = Loja.objects.get(nome_loja='Lapa')
        self.assertIsNotNone(loja.responsavel)
        acesso = loja.responsavel
        self.assertEqual(acesso.username, 'lapa@unistock.com')
        self.assertEqual(acesso.email, 'lapa@unistock.com')
        self.assertEqual(acesso.first_name, 'Lapa')
        self.assertFalse(acesso.is_active)
        self.assertFalse(acesso.has_usable_password())
        self.assertTrue(acesso.groups.filter(name='Responsavel').exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['lapa@unistock.com'])

    def test_loja_sem_email_nao_cria_login(self):
        from django.core import mail

        response = self.client.post(
            '/api/v1/lojas/', self._payload(email=''), format='json',
        )

        self.assertEqual(response.status_code, 201, response.data)
        loja = Loja.objects.get(nome_loja='Lapa')
        self.assertIsNone(loja.responsavel)
        self.assertEqual(len(mail.outbox), 0)

    def test_duas_lojas_com_o_mesmo_email_e_recusado(self):
        self.client.post('/api/v1/lojas/', self._payload(), format='json')

        response = self.client.post(
            '/api/v1/lojas/', self._payload(nome_loja='Outra'), format='json',
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('email', response.data)

    def test_email_ja_usado_por_uma_conta_e_recusado(self):
        """Cadastro publico e aberto: alguem pode ter registrado esse email
        antes. Tem que dar 400, nao 500 com a loja pela metade."""
        User.objects.create_user(
            username='lapa@unistock.com', email='lapa@unistock.com', password='123',
        )

        response = self.client.post('/api/v1/lojas/', self._payload(), format='json')

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('email', response.data)
        self.assertFalse(Loja.objects.filter(nome_loja='Lapa').exists())

    def test_nao_da_para_escolher_o_responsavel_pela_api(self):
        """responsavel e read-only: era possivel se auto-atribuir a loja e
        ganhar acesso aos dados dela."""
        self.client.post('/api/v1/lojas/', self._payload(), format='json')
        loja = Loja.objects.get(nome_loja='Lapa')
        acesso_original = loja.responsavel_id
        invasor = User.objects.create_user(username='invasor', password='123')

        response = self.client.patch(
            f'/api/v1/lojas/{loja.public_id}/',
            {'responsavel': invasor.id}, format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)
        loja.refresh_from_db()
        self.assertEqual(loja.responsavel_id, acesso_original)

    def test_loja_sem_acesso_devolve_email_acesso_nulo(self):
        """O front le esse campo; ele nao pode sumir do JSON."""
        response = self.client.post(
            '/api/v1/lojas/', self._payload(email=''), format='json',
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertIn('email_acesso', response.data)
        self.assertIsNone(response.data['email_acesso'])


class TrocarEmailDaLojaTests(APITestCase):
    def setUp(self):
        Group.objects.get_or_create(name='Responsavel')
        grupo_gerente, _ = Group.objects.get_or_create(name='Gerente')
        self.gerente = User.objects.create_user(username='ger2', password='123')
        self.gerente.groups.add(grupo_gerente)
        self.client.force_authenticate(self.gerente)
        self.client.post('/api/v1/lojas/', {
            'nome_loja': 'Lapa', 'cidade': 'Patos', 'endereco': 'Rua 1',
            'email': 'antigo@unistock.com',
        }, format='json')
        self.loja = Loja.objects.get(nome_loja='Lapa')

    def test_login_acompanha_o_novo_email(self):
        response = self.client.patch(
            f'/api/v1/lojas/{self.loja.public_id}/',
            {'email': 'novo@unistock.com'},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.loja.refresh_from_db()
        acesso = self.loja.responsavel
        acesso.refresh_from_db()
        self.assertEqual(acesso.username, 'novo@unistock.com')
        self.assertEqual(acesso.email, 'novo@unistock.com')

    def test_loja_que_ganha_email_depois_ganha_acesso(self):
        loja_sem = Loja.objects.create(
            nome_loja='Sem Email', cidade='Patos', endereco='Rua 2',
            gerente=self.gerente,
        )

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.patch(
                f'/api/v1/lojas/{loja_sem.public_id}/',
                {'email': 'depois@unistock.com'},
                format='json',
            )

        self.assertEqual(response.status_code, 200, response.data)
        loja_sem.refresh_from_db()
        self.assertIsNotNone(loja_sem.responsavel)
        self.assertEqual(loja_sem.responsavel.username, 'depois@unistock.com')

    def test_nao_permite_limpar_o_email_de_loja_com_acesso(self):
        """Limpar o email zeraria o username: a conta ficaria irrecuperavel e a
        proxima loja que limpasse colidiria no username vazio."""
        response = self.client.patch(
            f'/api/v1/lojas/{self.loja.public_id}/',
            {'email': ''},
            format='json',
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('email', response.data)
        acesso = self.loja.responsavel
        acesso.refresh_from_db()
        self.assertEqual(acesso.username, 'antigo@unistock.com')

    def test_loja_sem_acesso_pode_ficar_sem_email(self):
        """Sem login pra quebrar, continua sendo um estado valido."""
        loja_sem = Loja.objects.create(
            nome_loja='Sem Acesso', cidade='Patos', endereco='Rua 3',
            gerente=self.gerente,
        )

        response = self.client.patch(
            f'/api/v1/lojas/{loja_sem.public_id}/',
            {'email': ''},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)


class CriarLojaEhAtomicoTests(APITestCase):
    """Loja e acesso nascem juntos ou nao nascem.

    LojaSerializer.create commitava a Loja e so depois chamava
    criar_acesso_da_loja, numa transacao separada. Se a criacao do User
    estourasse, a Loja ficava gravada sem acesso — e como o email dela ja
    estava tomado, nem dava pra recadastrar.
    """

    def setUp(self):
        self.gerente = User.objects.create_user(
            username='chefe@unistock.com', password='Chefe#2026',
        )
        self.gerente.groups.add(Group.objects.get_or_create(name='Gerente')[0])
        self.client.force_authenticate(user=self.gerente)

    def test_falha_ao_criar_o_acesso_nao_deixa_loja_orfa(self):
        from unittest.mock import patch

        with patch(
            'app.api.v1.serializers.lojas.User.objects.create',
            side_effect=Exception('banco caiu no meio'),
        ):
            with self.assertRaises(Exception):
                self.client.post(
                    '/api/v1/lojas/',
                    {
                        'nome_loja': 'Orfa', 'cidade': 'Patos',
                        'endereco': 'Rua 1', 'email': 'orfa@unistock.com',
                    },
                    format='json',
                )

        self.assertFalse(Loja.objects.filter(email='orfa@unistock.com').exists())
