"""Regra de transicao de status do pedido, nos dois caminhos que a executam.

O status do pedido move estoque: virar ENTREGUE cria uma ENTRADA. Por isso a
regra de quais transicoes valem nao pode depender de por onde a pessoa entrou.

Hoje entram por dois lugares — o site (PATCH /api/v1/pedidos/<id>/status/) e o
bot de WhatsApp (POST /api/v1/bot/pedido/<n>/confirmar/) — e os dois precisam
responder igual. Estes testes cobrem os dois lados de cada regra de proposito,
para que uma correcao aplicada so em um caminho fique vermelha.
"""

from django.contrib.auth.models import Group, User
from django.test import override_settings
from rest_framework.test import APITestCase

from app.models import Estoque, ItemPedido, Loja, Pedido, Produto

TOKEN_BOT = "token-de-teste"
CABECALHO_BOT = {"HTTP_X_BOT_TOKEN": TOKEN_BOT}
TELEFONE_LOJA = "5583999998888"


@override_settings(BOT_SERVICE_TOKEN=TOKEN_BOT)
class TransicaoDeStatusTests(APITestCase):
    def setUp(self):
        Group.objects.get_or_create(name="Responsavel")
        grupo_gerente, _ = Group.objects.get_or_create(name="Gerente")

        self.gerente = User.objects.create_user(
            username="ger@email.com", password="123456"
        )
        self.gerente.groups.add(grupo_gerente)

        self.responsavel = User.objects.create_user(
            username="loja@email.com", password="123456"
        )
        self.loja = Loja.objects.create(
            nome_loja="Loja Centro",
            cidade="Patos",
            endereco="Rua A, 1",
            responsavel=self.responsavel,
            telefone_whatsapp=TELEFONE_LOJA,
        )
        self.produto = Produto.objects.create(
            nome_produto="Coxinha",
            unidade_medida=Produto.UnidadeMedida.CAIXA,
            categoria=Produto.Categoria.SALGADOS_GDE,
        )

    def criar_pedido(self, status=Pedido.Status.PENDENTE, quantidade=3):
        pedido = Pedido.objects.create(
            responsavel=self.responsavel, loja=self.loja, status=status
        )
        ItemPedido.objects.create(
            pedido=pedido,
            produto=self.produto,
            quantidade=quantidade,
            responsavel=self.responsavel,
        )
        return pedido

    def estoque_atual(self):
        estoque = Estoque.objects.filter(
            loja=self.loja, produto=self.produto
        ).first()
        return estoque.quantidade_atual if estoque else 0

    def pelo_site(self, pedido, status_novo):
        self.client.force_authenticate(self.gerente)
        return self.client.patch(
            f"/api/v1/pedidos/{pedido.public_id}/status/",
            {"status": status_novo},
            format="json",
        )

    def pelo_bot(self, pedido):
        return self.client.post(
            f"/api/v1/bot/pedido/{pedido.id}/confirmar/",
            {"telefone": TELEFONE_LOJA},
            format="json",
            **CABECALHO_BOT,
        )

    # --- o caminho feliz ---

    def test_pendente_vira_entregue_e_soma_o_estoque(self):
        for canal, executar in (
            ("site", lambda p: self.pelo_site(p, Pedido.Status.ENTREGUE)),
            ("bot", self.pelo_bot),
        ):
            with self.subTest(canal=canal):
                pedido = self.criar_pedido()
                antes = self.estoque_atual()

                resposta = executar(pedido)

                self.assertIn(resposta.status_code, (200, 201), resposta.data)
                pedido.refresh_from_db()
                self.assertEqual(pedido.status, Pedido.Status.ENTREGUE)
                self.assertEqual(self.estoque_atual(), antes + 3)

    def test_pendente_vira_cancelado_sem_mexer_no_estoque(self):
        pedido = self.criar_pedido()

        resposta = self.pelo_site(pedido, Pedido.Status.CANCELADO)

        self.assertEqual(resposta.status_code, 200, resposta.data)
        pedido.refresh_from_db()
        self.assertEqual(pedido.status, Pedido.Status.CANCELADO)
        self.assertEqual(self.estoque_atual(), 0)

    # --- a regra que move dinheiro: cancelado nao entra no estoque ---

    def test_cancelado_nao_vira_entregue_pelo_site(self):
        """O bot ja recusava isso; o site aceitava e somava no estoque.

        Uma ENTRADA que nunca chegou vira estoque fantasma: a loja para de
        pedir um produto que ela nao tem. E um bug de dado, nao de tela.
        """
        pedido = self.criar_pedido(status=Pedido.Status.CANCELADO)

        resposta = self.pelo_site(pedido, Pedido.Status.ENTREGUE)

        self.assertEqual(resposta.status_code, 409, resposta.data)
        pedido.refresh_from_db()
        self.assertEqual(pedido.status, Pedido.Status.CANCELADO)
        self.assertEqual(self.estoque_atual(), 0)

    def test_cancelado_nao_vira_entregue_pelo_bot(self):
        pedido = self.criar_pedido(status=Pedido.Status.CANCELADO)

        resposta = self.pelo_bot(pedido)

        self.assertEqual(resposta.status_code, 409, resposta.data)
        pedido.refresh_from_db()
        self.assertEqual(pedido.status, Pedido.Status.CANCELADO)
        self.assertEqual(self.estoque_atual(), 0)

    # --- entregue e ponto final ---

    def test_entregue_nao_volta_para_pendente_nem_cancelado(self):
        for status_novo in (Pedido.Status.PENDENTE, Pedido.Status.CANCELADO):
            with self.subTest(status=status_novo):
                pedido = self.criar_pedido(status=Pedido.Status.ENTREGUE)

                resposta = self.pelo_site(pedido, status_novo)

                self.assertEqual(resposta.status_code, 409, resposta.data)
                pedido.refresh_from_db()
                self.assertEqual(pedido.status, Pedido.Status.ENTREGUE)

    def test_repetir_entregue_nao_soma_duas_vezes(self):
        """O bot repete a chamada quando a rede falha, e o site tem dois
        cliques. Repetir precisa ser silencioso, nao erro — e sobretudo nao
        pode somar de novo."""
        for canal, executar in (
            ("site", lambda p: self.pelo_site(p, Pedido.Status.ENTREGUE)),
            ("bot", self.pelo_bot),
        ):
            with self.subTest(canal=canal):
                pedido = self.criar_pedido()
                executar(pedido)
                somado_uma_vez = self.estoque_atual()

                resposta = executar(pedido)

                self.assertIn(resposta.status_code, (200, 201), resposta.data)
                self.assertEqual(self.estoque_atual(), somado_uma_vez)

    # --- entrada invalida ---

    def test_status_fora_das_opcoes_da_400(self):
        pedido = self.criar_pedido()

        resposta = self.pelo_site(pedido, "SUMIU")

        self.assertEqual(resposta.status_code, 400, resposta.data)
        pedido.refresh_from_db()
        self.assertEqual(pedido.status, Pedido.Status.PENDENTE)
