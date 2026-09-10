"""Teto de estoque por loja: alerta de excesso e aviso ao pedir demais.

O minimo ja era por loja; o que faltava era o teto. O motivo dele nao e
espaco de prateleira, e validade — produto parado demais estraga. Por isso o
excesso ALERTA como a falta alerta, e o pedido que estoura o teto AVISA antes
de passar.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from app.models import Categoria, Estoque, Loja, Notificacao, Produto
from app.notifications import notificar_estoque_excedido
from app.tests.fabricas import criar_conta, criar_gerente, criar_responsavel


class TetoPorLojaTests(TestCase):
    def setUp(self):
        self.conta = criar_conta("Empresa A")
        self.gerente = criar_gerente("ger@x.com", self.conta)
        self.resp_lapa = criar_responsavel("lapa@x.com", self.conta)

        # As duas lojas do exemplo real: a Lapa gira muito mais que a Casa
        # Verde, entao o mesmo produto tem niveis diferentes em cada uma.
        self.lapa = Loja.objects.create(
            nome_loja="Lapa", cidade="Patos", endereco="Rua 1",
            conta=self.conta, responsavel=self.resp_lapa,
        )
        self.casa_verde = Loja.objects.create(
            nome_loja="Casa Verde", cidade="Patos", endereco="Rua 2",
            conta=self.conta,
        )
        categoria = Categoria.objects.create(nome="Salgados", conta=self.conta)
        self.coxinha = Produto.objects.create(
            nome_produto="Coxinha", categoria=categoria, conta=self.conta,
            estoque_minimo_sugerido=5, estoque_maximo_sugerido=15,
        )

    def _estoque(self, loja, atual, minima, maxima):
        return Estoque.objects.create(
            loja=loja, produto=self.coxinha,
            quantidade_atual=atual, quantidade_minima=minima,
            quantidade_maxima=maxima,
        )

    # --- niveis diferentes por loja ---

    def test_cada_loja_tem_o_proprio_teto(self):
        na_lapa = self._estoque(self.lapa, atual=60, minima=30, maxima=80)
        na_casa_verde = self._estoque(self.casa_verde, atual=60, minima=5, maxima=20)

        excedidos = list(Estoque.objects.excedidos())

        # Mesma quantidade nas duas: sobra numa, esta em dia na outra.
        self.assertIn(na_casa_verde, excedidos)
        self.assertNotIn(na_lapa, excedidos)

    def test_excedidos_ignora_loja_inativa(self):
        self.casa_verde.ativo = False
        self.casa_verde.save(update_fields=["ativo"])
        self._estoque(self.casa_verde, atual=60, minima=5, maxima=20)

        self.assertEqual(list(Estoque.objects.excedidos()), [])

    def test_no_teto_exato_nao_e_excesso(self):
        """O limite e "acima de", nao "a partir de" — igual ao minimo, que so
        alerta em quantidade_atual <= quantidade_minima."""
        self._estoque(self.casa_verde, atual=20, minima=5, maxima=20)

        self.assertEqual(list(Estoque.objects.excedidos()), [])

    # --- alerta de excesso ---

    def test_excesso_notifica_a_loja_e_a_gerencia(self):
        estoque = self._estoque(self.lapa, atual=100, minima=30, maxima=80)

        notificar_estoque_excedido(estoque)

        destinatarios = set(
            Notificacao.objects.filter(tipo="estoque_excedido").values_list(
                "usuario_id", flat=True
            )
        )
        self.assertEqual(destinatarios, {self.resp_lapa.id, self.gerente.id})

    def test_alerta_de_excesso_some_quando_o_estoque_volta_ao_teto(self):
        estoque = self._estoque(self.lapa, atual=100, minima=30, maxima=80)
        notificar_estoque_excedido(estoque)

        estoque.quantidade_atual = 70
        estoque.save(update_fields=["quantidade_atual"])
        notificar_estoque_excedido(estoque)

        self.assertFalse(
            Notificacao.objects.filter(tipo="estoque_excedido").exists()
        )

    def test_nao_duplica_e_atualiza_o_numero(self):
        estoque = self._estoque(self.lapa, atual=100, minima=30, maxima=80)
        notificar_estoque_excedido(estoque)

        estoque.quantidade_atual = 120
        estoque.save(update_fields=["quantidade_atual"])
        notificar_estoque_excedido(estoque)

        alertas = Notificacao.objects.filter(
            tipo="estoque_excedido", usuario=self.resp_lapa
        )
        self.assertEqual(alertas.count(), 1)
        self.assertIn("120", alertas.first().mensagem)

    def test_gerente_de_outra_empresa_nao_recebe(self):
        outra = criar_conta("Empresa B")
        de_fora = criar_gerente("fora@x.com", outra)
        estoque = self._estoque(self.lapa, atual=100, minima=30, maxima=80)

        notificar_estoque_excedido(estoque)

        self.assertFalse(
            Notificacao.objects.filter(
                tipo="estoque_excedido", usuario=de_fora
            ).exists()
        )

    # --- validacao do teto ---

    def test_api_recusa_maximo_menor_ou_igual_ao_minimo(self):
        client = APIClient()
        client.force_authenticate(self.gerente)

        resp = client.post(
            "/api/v1/estoque/",
            {
                "loja": str(self.lapa.public_id),
                "produto": str(self.coxinha.public_id),
                "quantidade_atual": 10,
                "quantidade_minima": 30,
                "quantidade_maxima": 30,
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn("quantidade_maxima", resp.data)

    def test_api_recusa_teto_zerado(self):
        client = APIClient()
        client.force_authenticate(self.gerente)

        resp = client.post(
            "/api/v1/estoque/",
            {
                "loja": str(self.lapa.public_id),
                "produto": str(self.coxinha.public_id),
                "quantidade_atual": 0,
                "quantidade_minima": 0,
                "quantidade_maxima": 0,
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 400, resp.data)


class PedidoQueEstouraOTetoTests(TestCase):
    """A trava e AVISADA, nao dura: a primeira tentativa explica, a segunda
    passa se a pessoa confirmar.

    Trava dura empurra quem esta na loja a subir o teto para 200 so para
    conseguir pedir — e nunca mais abaixar. Ai o teto vira ficcao e o alerta
    de excesso, que protege o produto de estragar, morre junto.
    """

    def setUp(self):
        self.conta = criar_conta("Empresa A")
        self.resp = criar_responsavel("lapa@x.com", self.conta)
        self.lapa = Loja.objects.create(
            nome_loja="Lapa", cidade="Patos", endereco="Rua 1",
            conta=self.conta, responsavel=self.resp,
        )
        categoria = Categoria.objects.create(nome="Salgados", conta=self.conta)
        self.coxinha = Produto.objects.create(
            nome_produto="Coxinha", categoria=categoria, conta=self.conta,
        )
        Estoque.objects.create(
            loja=self.lapa, produto=self.coxinha,
            quantidade_atual=40, quantidade_minima=10, quantidade_maxima=50,
        )
        self.client_api = APIClient()
        self.client_api.force_authenticate(self.resp)

    def _pedir(self, quantidade, **extra):
        corpo = {
            "loja": str(self.lapa.public_id),
            "itens": [{"produto": str(self.coxinha.public_id), "quantidade": quantidade}],
        }
        corpo.update(extra)
        return self.client_api.post("/api/v1/pedidos/", corpo, format="json")

    def test_pedido_dentro_do_teto_passa_direto(self):
        resp = self._pedir(10)  # 40 + 10 = 50, exatamente o teto

        self.assertEqual(resp.status_code, 201, resp.data)

    def test_pedido_que_estoura_avisa_e_nao_cria(self):
        from app.models import Pedido

        resp = self._pedir(30)  # 40 + 30 = 70, teto 50

        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertIn("excesso", resp.data)
        aviso = resp.data["excesso"][0]
        self.assertEqual(aviso["produto"], "Coxinha")
        self.assertEqual(aviso["resultante"], 70)
        self.assertEqual(aviso["maximo"], 50)
        self.assertEqual(aviso["cabe"], 10)
        self.assertFalse(Pedido.objects.exists())

    def test_confirmando_o_excesso_o_pedido_passa(self):
        from app.models import Pedido

        resp = self._pedir(30, confirmar_excesso=True)

        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(Pedido.objects.count(), 1)

    def test_produto_que_a_loja_ainda_nao_tem_nao_dispara_aviso(self):
        """Sem linha de estoque nao existe teto DESTA loja.

        Avisar aqui seria decidir pelo palpite universal do produto — que e
        justamente o que o teto por loja veio eliminar, e na pratica fazia o
        bot reclamar do primeiro pedido de qualquer produto novo. A protecao
        nao some: o pedido entregue cria a linha, e dali em diante o excesso
        alerta.
        """
        outro = Produto.objects.create(
            nome_produto="Pastel",
            categoria=self.coxinha.categoria,
            conta=self.conta,
            estoque_minimo_sugerido=2,
            estoque_maximo_sugerido=6,
        )
        corpo = {
            "loja": str(self.lapa.public_id),
            "itens": [{"produto": str(outro.public_id), "quantidade": 10}],
        }

        resp = self.client_api.post("/api/v1/pedidos/", corpo, format="json")

        self.assertEqual(resp.status_code, 201, resp.data)
