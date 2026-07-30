"""Autorizacao dos endpoints sensiveis (relatorio PDF, listas, movimentacoes)."""

from django.contrib.auth.models import Group, User
from rest_framework.test import APITestCase

from app.models import Categoria, Estoque, Loja, MovimentacaoEstoque, Notificacao, Produto
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
        categoria = Categoria.objects.get_or_create(nome='Mercado')[0]
        self.produto = Produto.objects.create(nome_produto='Coca', categoria=categoria)
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

    def test_movimentacoes_escopo_por_loja(self):
        """Responsavel ve so movimentos das lojas dele; admin ve tudo.

        Gerente deixou de ver tudo sem restricao (mudanca intencional: agora
        e escopado as proprias lojas, ver test_estoque_escopo.py)."""
        outro = User.objects.create_user(username='outro@email.com', password='123')
        outra_loja = Loja.objects.create(
            nome_loja='Loja Outra', cidade='Patos', endereco='Rua 2',
            responsavel=outro,
        )
        minha = MovimentacaoEstoque.objects.create(
            tipo=MovimentacaoEstoque.Tipo.ENTRADA, produto=self.produto,
            loja_destino=self.loja, quantidade=5, usuario=self.user,
        )
        MovimentacaoEstoque.objects.create(
            tipo=MovimentacaoEstoque.Tipo.ENTRADA, produto=self.produto,
            loja_destino=outra_loja, quantidade=7, usuario=outro,
        )

        # Sem login nega
        response = self.client.get('/api/v1/movimentacoes/')
        self.assertIn(response.status_code, (401, 403))

        # Responsavel: so a propria loja
        self.client.force_authenticate(self.user)
        response = self.client.get('/api/v1/movimentacoes/')
        self.assertEqual(response.status_code, 200)
        ids = [m['id'] for m in response.data['results']]
        self.assertEqual(ids, [str(minha.public_id)])

        # Admin: todas
        admin = User.objects.create_user(username='adm@email.com', password='123')
        grupo, _ = Group.objects.get_or_create(name='Admin')
        admin.groups.add(grupo)
        self.client.force_authenticate(admin)
        response = self.client.get('/api/v1/movimentacoes/')
        self.assertEqual(len(response.data['results']), 2)

        # Filtro por loja (tela de historico separada por loja no front)
        response = self.client.get(
            f'/api/v1/movimentacoes/?loja={self.loja.public_id}'
        )
        ids = [m['id'] for m in response.data['results']]
        self.assertEqual(ids, [str(minha.public_id)])

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
