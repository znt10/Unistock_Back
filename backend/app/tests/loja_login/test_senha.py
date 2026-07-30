"""A loja como login: endpoints de definir senha e esqueci a senha."""

from django.contrib.auth.models import Group, User
from rest_framework.test import APITestCase


class DefinirSenhaTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='lapa@unistock.com', email='lapa@unistock.com',
        )
        self.user.set_unusable_password()
        self.user.is_active = False
        self.user.save()
        # Conta real de loja sempre nasce no grupo Responsavel (ver
        # criar_acesso_da_loja); sem grupo o LoginView recusa com 403.
        grupo, _ = Group.objects.get_or_create(name='Responsavel')
        self.user.groups.add(grupo)

    def _token(self):
        from app.notifications.tokens import gerar_token_senha

        return gerar_token_senha(self.user)

    def test_define_a_senha_e_ativa_a_conta(self):
        response = self.client.post(
            f'/api/v1/user/definir-senha/{self._token()}/',
            {'password': 'SenhaForte#2026'},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertTrue(self.user.check_password('SenhaForte#2026'))

    def test_token_invalido_400(self):
        response = self.client.post(
            '/api/v1/user/definir-senha/token-falso/',
            {'password': 'SenhaForte#2026'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)

    def test_senha_fraca_400(self):
        response = self.client.post(
            f'/api/v1/user/definir-senha/{self._token()}/',
            {'password': '123'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.has_usable_password())

    def test_mesmo_token_nao_serve_duas_vezes(self):
        token = self._token()
        self.client.post(
            f'/api/v1/user/definir-senha/{token}/',
            {'password': 'SenhaForte#2026'}, format='json',
        )

        response = self.client.post(
            f'/api/v1/user/definir-senha/{token}/',
            {'password': 'OutraSenha#2026'}, format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('SenhaForte#2026'))

    def test_conta_consegue_entrar_depois_de_definir_a_senha(self):
        """O objetivo da feature: a loja passa a conseguir entrar de verdade."""
        self.client.post(
            f'/api/v1/user/definir-senha/{self._token()}/',
            {'password': 'SenhaForte#2026'}, format='json',
        )

        login = self.client.post('/login/', {
            'email': 'lapa@unistock.com',
            'password': 'SenhaForte#2026',
        })

        self.assertEqual(login.status_code, 200, getattr(login, 'data', login.content))
        self.assertIn('access_token', login.cookies)

    def test_link_expirado_avisa_para_pedir_outro(self):
        from unittest.mock import patch
        import time as _time

        token = self._token()
        futuro = _time.time() + 60 * 60 * 24 * 3 + 60

        with patch('django.core.signing.time.time', return_value=futuro):
            response = self.client.post(
                f'/api/v1/user/definir-senha/{token}/',
                {'password': 'SenhaForte#2026'}, format='json',
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn('expirado', str(response.data).lower())


class EsqueciSenhaTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='lapa@unistock.com', email='lapa@unistock.com',
            password='qualquer-123',
        )

    def test_email_existente_recebe_link(self):
        from django.core import mail

        response = self.client.post(
            '/api/v1/user/esqueci-senha/',
            {'email': 'lapa@unistock.com'}, format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['lapa@unistock.com'])

    def test_email_inexistente_responde_igual_sem_enviar(self):
        """Nao vazar quais emails estao cadastrados."""
        from django.core import mail

        response = self.client.post(
            '/api/v1/user/esqueci-senha/',
            {'email': 'naoexiste@unistock.com'}, format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_loja_provisionada_com_link_expirado_consegue_pedir_outro(self):
        """Conta inativa que nunca definiu senha e loja recem-criada.

        So filtrar is_active deixaria ela travada pra sempre: o link de 3 dias
        expirou e ela nao teria como pedir outro.
        """
        from django.core import mail

        nova = User.objects.create(
            username='nova@unistock.com', email='nova@unistock.com',
            is_active=False,
        )
        nova.set_unusable_password()
        nova.save()

        response = self.client.post(
            '/api/v1/user/esqueci-senha/',
            {'email': 'nova@unistock.com'}, format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['nova@unistock.com'])

    def test_conta_desativada_de_proposito_continua_bloqueada(self):
        """Quem ja definiu senha e foi desativado nao recebe link de volta."""
        from django.core import mail

        banida = User.objects.create_user(
            username='banida@unistock.com', email='banida@unistock.com',
            password='tinha-senha-123',
        )
        banida.is_active = False
        banida.save(update_fields=['is_active'])

        response = self.client.post(
            '/api/v1/user/esqueci-senha/',
            {'email': 'banida@unistock.com'}, format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)

    def test_email_que_nao_e_texto_da_400_e_nao_500(self):
        response = self.client.post(
            '/api/v1/user/esqueci-senha/', {'email': 12345}, format='json',
        )

        self.assertEqual(response.status_code, 400)


class ThrottleEsqueciSenhaTests(APITestCase):
    """O limite tem que valer para quem esta logado tambem.

    SenhaRateThrottle herdava de AnonRateThrottle, cujo get_cache_key devolve
    None para requisicao autenticada: nao limitava nada. Uma conta qualquer
    podia encher a caixa de outra loja de links de redefinicao.
    """

    def setUp(self):
        from django.core.cache import cache

        cache.clear()  # o historico do throttle vaza entre testes
        self.alvo = User.objects.create_user(
            username='alvo@unistock.com', email='alvo@unistock.com',
            password='qualquer-123',
        )
        self.logado = User.objects.create_user(
            username='logado@unistock.com', email='logado@unistock.com',
            password='qualquer-123',
        )

    def test_conta_logada_tambem_esbarra_no_limite(self):
        self.client.force_authenticate(user=self.logado)

        codigos = [
            self.client.post(
                '/api/v1/user/esqueci-senha/',
                {'email': 'alvo@unistock.com'}, format='json',
            ).status_code
            for _ in range(11)
        ]

        self.assertEqual(codigos[0], 200)
        self.assertEqual(codigos[-1], 429)  # taxa "senha" e 10/hour
