from django.test import TestCase
from rest_framework.test import APIClient

from app.models import Estoque, Pedido
from app.tests.fabricas import (
    criar_conta,
    criar_fabrica,
    criar_gerente,
    criar_loja,
    criar_pedido,
    criar_produto,
)


class ImprimirEtiquetasTests(TestCase):
    def setUp(self):
        self.conta = criar_conta()
        self.fabrica = criar_fabrica(self.conta)
        self.lapa = criar_loja(self.conta, "Lapa")
        self.coxinha = criar_produto(self.conta)
        self.estoque = Estoque.objects.create(
            loja=self.fabrica, produto=self.coxinha,
            quantidade_atual=5, quantidade_minima=1, quantidade_maxima=100,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.fabrica.responsavel)

    def pedido(self, quantidade, **extras):
        extras.setdefault("da_fabrica", True)
        return criar_pedido(self.lapa, self.coxinha, quantidade=quantidade, **extras)

    def imprimir(self, *pedidos):
        return self.client.post(
            "/api/v1/fabrica/etiquetas/",
            {"pedidos": [str(pedido.public_id) for pedido in pedidos]},
            format="json",
        )

    def test_cria_caixas_numeradas_e_muda_para_em_entrega(self):
        pedido = self.pedido(3)
        resposta = self.imprimir(pedido)

        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertEqual(resposta.data["recusados"], [])
        self.assertEqual(resposta.data["impressos"][0]["caixas"], 3)
        pedido.refresh_from_db()
        self.assertEqual(pedido.status, Pedido.Status.EM_ENTREGA)
        self.assertEqual(list(pedido.caixas.order_by("numero").values_list("numero", flat=True)), [1, 2, 3])
        self.assertEqual(len(set(pedido.caixas.values_list("codigo", flat=True))), 3)
        # Imprimir nao mexe no estoque: a caixa so sai da fabrica ao ser lida na loja.
        self.estoque.refresh_from_db()
        self.assertEqual(self.estoque.quantidade_atual, 5)

    def test_recusa_sem_estoque_e_mantem_pendente(self):
        pedido = self.pedido(6)
        resposta = self.imprimir(pedido)

        self.assertEqual(resposta.data["impressos"], [])
        recusa = resposta.data["recusados"][0]
        self.assertEqual(recusa["faltam"], 1)
        self.assertIn("Faltam 1 caixa de Coxinha", recusa["motivo"])
        pedido.refresh_from_db()
        self.assertEqual(pedido.status, Pedido.Status.PENDENTE)
        self.assertFalse(pedido.caixas.exists())

    def test_disponivel_desconta_caixas_a_caminho(self):
        self.imprimir(self.pedido(4))
        resposta = self.imprimir(self.pedido(2))
        self.assertEqual(resposta.data["recusados"][0]["faltam"], 1)

    def test_dois_pedidos_do_mesmo_produto_na_mesma_impressao(self):
        primeiro, segundo = self.pedido(3), self.pedido(3)
        resposta = self.imprimir(primeiro, segundo)
        self.assertEqual([p["pedido"] for p in resposta.data["impressos"]], [str(primeiro.public_id)])
        self.assertEqual(resposta.data["recusados"][0]["pedido"], str(segundo.public_id))

    def test_segunda_impressao_do_mesmo_pedido_e_recusada(self):
        pedido = self.pedido(2)
        self.imprimir(pedido)
        resposta = self.imprimir(pedido)
        self.assertEqual(resposta.data["recusados"][0]["motivo"], "Já impresso, use Reimprimir.")
        self.assertEqual(pedido.caixas.count(), 2)

    def test_recusa_pedido_que_nao_e_da_fabrica(self):
        resposta = self.imprimir(self.pedido(1, da_fabrica=False))
        self.assertEqual(resposta.data["recusados"][0]["motivo"], "Não é pedido da fábrica.")

    def test_pedido_de_outra_empresa_nao_e_encontrado(self):
        conta_b = criar_conta("B")
        criar_fabrica(conta_b)
        alheio = criar_pedido(criar_loja(conta_b, "Centro"), criar_produto(conta_b), da_fabrica=True)
        resposta = self.imprimir(alheio)
        self.assertEqual(resposta.data["recusados"][0]["motivo"], "Pedido não encontrado.")

    def test_loja_nao_imprime(self):
        self.client.force_authenticate(self.lapa.responsavel)
        self.assertEqual(self.imprimir(self.pedido(1)).status_code, 403)

    def test_gerente_imprime_na_fabrica_da_empresa(self):
        self.client.force_authenticate(criar_gerente("ger@x.com", self.conta))
        resposta = self.imprimir(self.pedido(1))
        self.assertEqual(len(resposta.data["impressos"]), 1)
