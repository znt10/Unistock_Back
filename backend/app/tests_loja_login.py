"""A loja como login: token de senha, criacao de acesso e migracao."""

from django.contrib.auth.models import User
from django.core import signing
from django.test import TestCase


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
        from django.core import mail

        from app.notifications.tasks import enviar_email_definir_senha

        user = User.objects.create_user(
            username='lapa@unistock.com', email='lapa@unistock.com',
        )

        enviado = enviar_email_definir_senha(user.id)

        self.assertTrue(enviado)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['lapa@unistock.com'])
        self.assertIn('/redefinir-senha/', mail.outbox[0].body)

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
