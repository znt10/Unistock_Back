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

from app.models import Caixa, Categoria, Estoque, ItemPedido, Loja, Pedido, Produto
from app.tests.fabricas import (
    criar_conta,
    criar_fabrica,
    criar_gerente,
    criar_loja,
    criar_pedido,
    criar_produto,
    vincular,
)

TOKEN_BOT = "token-de-teste"
CABECALHO_BOT = {"HTTP_X_BOT_TOKEN": TOKEN_BOT}
TELEFONE_LOJA = "5583999998888"


@override_settings(BOT_SERVICE_TOKEN=TOKEN_BOT)
class TransicaoDeStatusTests(APITestCase):
    def setUp(self):
        self.conta = criar_conta()
        Group.objects.get_or_create(name="Responsavel")
        grupo_gerente, _ = Group.objects.get_or_create(name="Gerente")

        self.gerente = User.objects.create_user(
            username="ger@email.com", password="123456"
        )
        self.gerente.groups.add(grupo_gerente)
        vincular(self.gerente, self.conta)

        self.responsavel = User.objects.create_user(
            username="loja@email.com", password="123456"
        )
        self.loja = Loja.objects.create(
            nome_loja="Loja Centro",
            cidade="Patos",
            endereco="Rua A, 1",
            responsavel=self.responsavel,
            conta=self.conta,
            telefone_whatsapp=TELEFONE_LOJA,
        )
        categoria = Categoria.objects.create(nome="Salgados grande", conta=self.conta)
        self.produto = Produto.objects.create(
            nome_produto="Coxinha",
            unidade_medida=Produto.UnidadeMedida.CAIXA,
            categoria=categoria,
            conta=self.conta,
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


@override_settings(BOT_SERVICE_TOKEN=TOKEN_BOT)
class PedidoDaFabricaStatusTests(APITestCase):
    def setUp(self):
        self.conta = criar_conta("Empresa com Fabrica")
        self.gerente = criar_gerente("gerente-fabrica@x.com", self.conta)
        criar_fabrica(self.conta)
        self.lapa = criar_loja(self.conta, "Lapa", telefone_whatsapp=TELEFONE_LOJA)
        self.coxinha = criar_produto(self.conta)

    def patch_status(self, usuario, pedido, status_novo):
        self.client.force_authenticate(usuario)
        return self.client.patch(
            f"/api/v1/pedidos/{pedido.public_id}/status/",
            {"status": status_novo},
            format="json",
        )

    def test_site_nao_marca_entregue(self):
        pedido = criar_pedido(self.lapa, self.coxinha, da_fabrica=True)
        resposta = self.patch_status(self.gerente, pedido, "ENTREGUE")
        self.assertEqual(resposta.status_code, 409)
        self.assertIn("etiquetas", resposta.data["status"])
        pedido.refresh_from_db()
        self.assertEqual(pedido.status, Pedido.Status.PENDENTE)
        self.assertFalse(Estoque.objects.filter(loja=self.lapa).exists())

    def test_bot_nao_confirma(self):
        pedido = criar_pedido(self.lapa, self.coxinha, da_fabrica=True)
        resposta = self.client.post(
            f"/api/v1/bot/pedido/{pedido.id}/confirmar/",
            {"telefone": TELEFONE_LOJA},
            format="json",
            **CABECALHO_BOT,
        )
        self.assertEqual(resposta.status_code, 409)
        self.assertIn("etiquetas", resposta.data["error"])

    def test_loja_cancela_pendente(self):
        pedido = criar_pedido(self.lapa, self.coxinha, da_fabrica=True)
        resposta = self.patch_status(self.lapa.responsavel, pedido, "CANCELADO")
        self.assertEqual(resposta.status_code, 200, resposta.data)

    def criar_em_entrega(self, situacao=Caixa.Situacao.A_CAMINHO):
        pedido = criar_pedido(
            self.lapa, self.coxinha, quantidade=2,
            da_fabrica=True, status=Pedido.Status.EM_ENTREGA,
        )
        Caixa.objects.create(pedido=pedido, numero=1, codigo="caixa-1", situacao=situacao)
        Caixa.objects.create(pedido=pedido, numero=2, codigo="caixa-2")
        return pedido

    def test_gerente_cancela_em_entrega_sem_leitura_e_apaga_caixas(self):
        pedido = self.criar_em_entrega()
        resposta = self.patch_status(self.gerente, pedido, "CANCELADO")
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertFalse(Caixa.objects.filter(pedido=pedido).exists())

    def test_loja_nao_cancela_em_entrega(self):
        pedido = self.criar_em_entrega()
        resposta = self.patch_status(self.lapa.responsavel, pedido, "CANCELADO")
        self.assertEqual(resposta.status_code, 409)
        self.assertEqual(Caixa.objects.filter(pedido=pedido).count(), 2)

    def test_nao_cancela_com_caixa_lida(self):
        pedido = self.criar_em_entrega(situacao=Caixa.Situacao.CHEGOU)
        resposta = self.patch_status(self.gerente, pedido, "CANCELADO")
        self.assertEqual(resposta.status_code, 409)
        pedido.refresh_from_db()
        self.assertEqual(pedido.status, Pedido.Status.EM_ENTREGA)
