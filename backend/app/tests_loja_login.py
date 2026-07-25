"""A loja como login: token de senha, criacao de acesso e migracao."""

from django.contrib.auth.models import Group, User
from django.core import signing
from django.test import TestCase
from rest_framework.test import APITestCase

from app.models import Loja


class TokenSenhaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='loja@teste.com', email='loja@teste.com', password='senha-antiga-123',
        )

    def test_token_valido_devolve_o_usuario(self):
        from app.notifications.tokens import gerar_token_senha, validar_token_senha

        token = gerar_token_senha(self.user)

        self.assertEqual(validar_token_senha(token), self.user.id)

    def test_token_deixa_de_valer_depois_que_a_senha_muda(self):
        """Uso unico: link usado (ou vazado) nao serve duas vezes."""
        from app.notifications.tokens import gerar_token_senha, validar_token_senha

        token = gerar_token_senha(self.user)
        self.user.set_password('senha-nova-456')
        self.user.save()

        with self.assertRaises(signing.BadSignature):
            validar_token_senha(token)

    def test_token_adulterado_e_recusado(self):
        from app.notifications.tokens import gerar_token_senha, validar_token_senha

        token = gerar_token_senha(self.user) + 'xx'

        with self.assertRaises(signing.BadSignature):
            validar_token_senha(token)

    def test_funciona_para_conta_sem_senha_utilizavel(self):
        """Caminho principal: a loja nasce sem senha e define no 1o acesso."""
        from app.notifications.tokens import gerar_token_senha, validar_token_senha

        loja = User.objects.create(username='lapa@unistock.com')
        loja.set_unusable_password()
        loja.save()

        token = gerar_token_senha(loja)

        self.assertEqual(validar_token_senha(token), loja.id)

        # Depois de definir a senha, o mesmo link nao serve mais.
        loja.set_password('SenhaForte#2026')
        loja.save()
        with self.assertRaises(signing.BadSignature):
            validar_token_senha(token)

    def test_token_expira_depois_de_3_dias(self):
        from unittest.mock import patch

        from app.notifications.tokens import gerar_token_senha, validar_token_senha

        token = gerar_token_senha(self.user)

        # Avanca o relogio do signing para 3 dias e 1 minuto no futuro.
        import time as _time

        futuro = _time.time() + 60 * 60 * 24 * 3 + 60
        with patch('django.core.signing.time.time', return_value=futuro):
            with self.assertRaises(signing.SignatureExpired):
                validar_token_senha(token)


class EmailDefinirSenhaTests(TestCase):
    def test_envia_link_de_definir_senha(self):
        import re

        from django.core import mail

        from app.notifications.tasks import enviar_email_definir_senha
        from app.notifications.tokens import validar_token_senha

        user = User.objects.create_user(
            username='lapa@unistock.com', email='lapa@unistock.com',
        )

        enviado = enviar_email_definir_senha(user.id)

        self.assertTrue(enviado)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['lapa@unistock.com'])

        # O link tem que carregar um token que realmente funciona e aponta pra
        # esta conta — nao basta a URL parecer certa.
        token = re.search(r"/redefinir-senha/(\S+)", mail.outbox[0].body).group(1)
        self.assertEqual(validar_token_senha(token), user.id)

    def test_usuario_inexistente_nao_envia(self):
        from django.core import mail

        from app.notifications.tasks import enviar_email_definir_senha

        self.assertFalse(enviar_email_definir_senha(99999))
        self.assertEqual(len(mail.outbox), 0)

    def test_usuario_sem_email_nao_envia(self):
        from django.core import mail

        from app.notifications.tasks import enviar_email_definir_senha

        user = User.objects.create_user(username='sem-email')

        self.assertFalse(enviar_email_definir_senha(user.id))
        self.assertEqual(len(mail.outbox), 0)


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
