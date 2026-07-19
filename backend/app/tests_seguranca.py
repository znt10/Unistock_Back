"""Autorizacao dos endpoints sensiveis (relatorio PDF e listas)."""

from django.contrib.auth.models import Group, User
from rest_framework.test import APITestCase

from app.models import Estoque, Loja, Notificacao, Produto
from app.notifications import notificar_estoque_baixo

try:
    import weasyprint  # noqa: F401
    HAS_WEASYPRINT = True
except Exception:
    HAS_WEASYPRINT = False


class EndpointsProtegidosTests(APITestCase):
    def setUp(self):
        grupo_gerente, _ = Group.objects.get_or_create(name='Gerente')
        Group.objects.get_or_create(name='Responsavel')

        self.gerente = User.objects.create_user(username='ger@email.com', password='123')
        self.gerente.groups.add(grupo_gerente)
        self.responsavel = User.objects.create_user(username='resp@email.com', password='123')

    # --- /gerar_pdf/ ---

    def test_relatorio_pdf_sem_login_nega(self):
        response = self.client.get('/gerar_pdf/?periodo=mes')
        self.assertIn(response.status_code, (401, 403))

    def test_relatorio_pdf_responsavel_403(self):
        self.client.force_authenticate(self.responsavel)
        response = self.client.get('/gerar_pdf/?periodo=dia')
        self.assertEqual(response.status_code, 403)

    def test_relatorio_pdf_gerente_ok(self):
        if not HAS_WEASYPRINT:
            self.skipTest('weasyprint nao instalado neste ambiente')
        self.client.force_authenticate(self.gerente)
        response = self.client.get('/gerar_pdf/?periodo=dia')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')

    # --- listas exigem login ---

    def test_lista_lojas_sem_login_nega(self):
        response = self.client.get('/api/v1/lojas/')
        self.assertIn(response.status_code, (401, 403))

    def test_lista_produtos_sem_login_nega(self):
        response = self.client.get('/api/v1/produtos/')
        self.assertIn(response.status_code, (401, 403))

    def test_listas_autenticadas_paginadas(self):
        self.client.force_authenticate(self.responsavel)
        for url in ('/api/v1/lojas/', '/api/v1/produtos/'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
            self.assertIn('results', response.data, url)


class NotificacaoPorFkTests(APITestCase):
    """Dedup e limpeza do alerta de estoque baixo pela FK, nao por texto."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='fk@email.com', email='fk@email.com', password='123',
        )
        self.loja = Loja.objects.create(
            nome_loja='Loja FK', cidade='Patos', endereco='Rua 1',
            responsavel=self.user,
        )
        self.produto = Produto.objects.create(nome_produto='Coca', categoria='MERCADO')
        self.estoque = Estoque.objects.create(
            loja=self.loja, produto=self.produto,
            quantidade_atual=1, quantidade_minima=5,
        )

    def test_notificacao_gravada_com_fk_e_dedup(self):
        notificar_estoque_baixo(self.estoque)
        notificar_estoque_baixo(self.estoque)

        notifs = Notificacao.objects.filter(tipo='estoque_baixo')
        self.assertEqual(notifs.count(), 1)
        self.assertEqual(notifs.first().estoque, self.estoque)

    def test_renomear_produto_nao_quebra_dedup(self):
        notificar_estoque_baixo(self.estoque)

        # Antes o dedup casava por texto da mensagem: renomear o produto
        # duplicava a notificacao. Com a FK, continua 1.
        self.produto.nome_produto = 'Coca 2L'
        self.produto.save()
        notificar_estoque_baixo(self.estoque)

        self.assertEqual(
            Notificacao.objects.filter(tipo='estoque_baixo').count(), 1
        )
