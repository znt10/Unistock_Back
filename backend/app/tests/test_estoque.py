from django.contrib.auth.models import Group, User
from django.db import IntegrityError, transaction
from rest_framework.test import APITestCase

from app.models import (
    Estoque, ItemPedido, Loja, MovimentacaoEstoque, Pedido, Produto,
)


class EstoqueBaixosTests(APITestCase):
    """Painel de estoque baixo: /estoque/baixos/ (gerente ve todas as lojas)."""

    def setUp(self):
        grupo_gerente, _ = Group.objects.get_or_create(name='Gerente')
        self.gerente = User.objects.create_user(username='ger', password='123')
        self.gerente.groups.add(grupo_gerente)
        self.resp_a = User.objects.create_user(username='respa', password='123')

        self.loja_a = Loja.objects.create(
            nome_loja='Loja A', cidade='Patos', endereco='Rua 1',
            responsavel=self.resp_a,
        )
        self.loja_b = Loja.objects.create(
            nome_loja='Loja B', cidade='Patos', endereco='Rua 2',
        )
        coxinha = Produto.objects.create(
            nome_produto='Coxinha', categoria='SALGADOS_GDE',
        )
        coca = Produto.objects.create(nome_produto='Coca', categoria='MERCADO')

        # Baixo na loja A, baixo na loja B, e um em dia na loja A.
        Estoque.objects.create(
            loja=self.loja_a, produto=coxinha,
            quantidade_atual=1, quantidade_minima=5,
        )
        Estoque.objects.create(
            loja=self.loja_b, produto=coxinha,
            quantidade_atual=0, quantidade_minima=3,
        )
        Estoque.objects.create(
            loja=self.loja_a, produto=coca,
            quantidade_atual=50, quantidade_minima=5,
        )

    def test_gerente_ve_baixos_de_todas_as_lojas(self):
        self.client.force_authenticate(self.gerente)

        response = self.client.get('/api/v1/estoque/baixos/')

        self.assertEqual(response.status_code, 200, response.data)
        nomes_lojas = {item['loja_nome'] for item in response.data}
        self.assertEqual(nomes_lojas, {'Loja A', 'Loja B'})
        self.assertEqual(len(response.data), 2)

    def test_responsavel_ve_apenas_baixos_da_sua_loja(self):
        self.client.force_authenticate(self.resp_a)

        response = self.client.get('/api/v1/estoque/baixos/')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['loja_nome'], 'Loja A')
        self.assertEqual(response.data[0]['produto_nome'], 'Coxinha')

    def test_produto_acima_do_minimo_nao_aparece(self):
        self.client.force_authenticate(self.gerente)

        response = self.client.get('/api/v1/estoque/baixos/')

        produtos = {item['produto_nome'] for item in response.data}
        self.assertNotIn('Coca', produtos)


class EstoqueIntegridadeTests(APITestCase):
    """Constraints do Estoque e historico de MovimentacaoEstoque."""

    def setUp(self):
        self.grupo_gerente, _ = Group.objects.get_or_create(name='Gerente')
        self.user = User.objects.create_user(username='resp', password='123')
        self.gerente = User.objects.create_user(username='ger', password='123')
        self.gerente.groups.add(self.grupo_gerente)

        self.loja = Loja.objects.create(
            nome_loja='Loja A', cidade='Patos', endereco='Rua 1',
            responsavel=self.user,
        )
        self.produto = Produto.objects.create(
            nome_produto='Coxinha', categoria='SALGADOS_GDE',
        )
        self.estoque = Estoque.objects.create(
            loja=self.loja, produto=self.produto,
            quantidade_atual=10, quantidade_minima=2,
        )

    def test_nao_permite_estoque_duplicado_para_produto_e_loja(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Estoque.objects.create(
                loja=self.loja, produto=self.produto,
                quantidade_atual=5, quantidade_minima=1,
            )

    def test_nao_permite_estoque_negativo(self):
        outro = Produto.objects.create(nome_produto='Coca', categoria='MERCADO')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Estoque.objects.create(
                loja=self.loja, produto=outro,
                quantidade_atual=-1, quantidade_minima=0,
            )

    def test_entrega_de_pedido_registra_movimentacao_entrada(self):
        from app.services.pedidos import somar_itens_no_estoque

        pedido = Pedido.objects.create(responsavel=self.user, loja=self.loja)
        ItemPedido.objects.create(
            pedido=pedido, produto=self.produto, quantidade=4, responsavel=self.user,
        )
        somar_itens_no_estoque(pedido)

        mov = MovimentacaoEstoque.objects.get(tipo=MovimentacaoEstoque.Tipo.ENTRADA)
        self.assertEqual(mov.loja_destino, self.loja)
        self.assertEqual(mov.produto, self.produto)
        self.assertEqual(mov.quantidade, 4)
        self.assertEqual(mov.usuario, self.user)

    def test_venda_pdv_registra_movimentacao_saida(self):
        self.client.force_authenticate(self.gerente)
        response = self.client.post(
            '/api/v1/vendas/',
            {
                'loja_id': str(self.loja.public_id),
                'itens': [{'produto_id': str(self.produto.public_id), 'quantidade': 3}],
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)

        mov = MovimentacaoEstoque.objects.get(tipo=MovimentacaoEstoque.Tipo.VENDA_PDV)
        self.assertEqual(mov.loja_origem, self.loja)
        self.assertEqual(mov.quantidade, 3)
        self.assertEqual(mov.usuario, self.gerente)
        self.estoque.refresh_from_db()
        self.assertEqual(self.estoque.quantidade_atual, 7)

    def test_ajuste_manual_registra_delta(self):
        self.client.force_authenticate(self.gerente)
        response = self.client.patch(
            f'/api/v1/estoque/{self.estoque.public_id}/',
            {'quantidade_atual': 6},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)

        mov = MovimentacaoEstoque.objects.get(tipo=MovimentacaoEstoque.Tipo.AJUSTE)
        self.assertEqual(mov.quantidade, -4)  # 10 -> 6
        self.assertEqual(mov.loja_origem, self.loja)
        self.assertEqual(mov.usuario, self.gerente)
