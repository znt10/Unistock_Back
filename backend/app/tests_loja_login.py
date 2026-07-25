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
