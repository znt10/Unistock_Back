"""A loja como login: notificacao de estoque baixo nao pode ficar obsoleta."""

from django.contrib.auth.models import User
from django.test import TestCase

from app.models import Loja


class NotificacaoObsoletaTests(TestCase):
    """Notificacao de estoque baixo tem que sumir quando o estoque se recupera.

    notificar_estoque_baixo saia cedo quando o estoque estava acima do minimo,
    sem apagar o que ja existia. So o EstoqueUpdateSerializer limpava — e
    somar_itens_no_estoque (pedido entregue, e o bot) nao passa por ele. Depois
    de um pedido chegar e resolver a falta, o alerta continuava no sininho.
    """

    def setUp(self):
        from app.models import Categoria, Produto

        self.dono = User.objects.create_user(username='dono@unistock.com', password='123')
        self.loja = Loja.objects.create(
            nome_loja='Lapa', cidade='Patos', endereco='Rua 1', responsavel=self.dono,
        )
        categoria = Categoria.objects.get_or_create(nome='Salgados grande')[0]
        self.produto = Produto.objects.create(
            nome_produto='Coxinha', categoria=categoria,
        )

    def test_alerta_some_quando_o_estoque_se_recupera(self):
        from app.models import Estoque, Notificacao
        from app.notifications import notificar_estoque_baixo

        estoque = Estoque.objects.create(
            loja=self.loja, produto=self.produto,
            quantidade_atual=1, quantidade_minima=5,
        )
        notificar_estoque_baixo(estoque)
        self.assertTrue(
            Notificacao.objects.filter(tipo='estoque_baixo', estoque=estoque).exists()
        )

        # Chegou o pedido e resolveu a falta.
        estoque.quantidade_atual = 20
        estoque.save(update_fields=['quantidade_atual'])
        notificar_estoque_baixo(estoque)

        self.assertFalse(
            Notificacao.objects.filter(tipo='estoque_baixo', estoque=estoque).exists()
        )
