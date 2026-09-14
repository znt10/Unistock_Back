from django.test import TestCase
from rest_framework.test import APIClient

from app.models import Estoque, MovimentacaoEstoque
from app.services.fabrica import registrar_producao
from app.tests.fabricas import (
    criar_conta,
    criar_fabrica,
    criar_loja,
    criar_pedido,
    criar_produto,
)


class ProducaoEDisponivelTests(TestCase):
    def setUp(self):
        self.conta = criar_conta()
        self.fabrica = criar_fabrica(self.conta)
        self.coxinha = criar_produto(self.conta)
        self.detergente = criar_produto(self.conta, "Detergente", "Mercado", vem_da_fabrica=False)
        self.client = APIClient()
        self.client.force_authenticate(self.fabrica.responsavel)

    def produzir(self, produto, caixas):
        return self.client.post(
            "/api/v1/fabrica/producao/",
            {"produto": str(produto.public_id), "caixas": caixas},
            format="json",
        )

    def test_registrar_producao_soma_e_grava_entrada(self):
        resposta = self.produzir(self.coxinha, 10)
        self.assertEqual(resposta.status_code, 201, resposta.data)
        self.assertEqual(resposta.data["quantidade_atual"], 10)
        movimento = MovimentacaoEstoque.objects.get(
            tipo=MovimentacaoEstoque.Tipo.ENTRADA, loja_destino=self.fabrica
        )
        self.assertEqual(movimento.quantidade, 10)
        self.assertEqual(movimento.usuario, self.fabrica.responsavel)

    def test_segunda_producao_soma_na_mesma_linha(self):
        self.produzir(self.coxinha, 10)
        self.produzir(self.coxinha, 5)
        self.assertEqual(Estoque.objects.filter(loja=self.fabrica).count(), 1)
        self.assertEqual(Estoque.objects.get(loja=self.fabrica).quantidade_atual, 15)

    def test_produto_que_nao_vem_da_fabrica_e_recusado(self):
        self.assertEqual(self.produzir(self.detergente, 1).status_code, 400)

    def test_zero_caixas_e_recusado(self):
        self.assertEqual(self.produzir(self.coxinha, 0).status_code, 400)

    def test_loja_nao_registra_producao(self):
        self.client.force_authenticate(criar_loja(self.conta, "Lapa").responsavel)
        self.assertEqual(self.produzir(self.coxinha, 1).status_code, 403)

    def test_disponivel(self):
        registrar_producao(self.fabrica, self.coxinha, 5, self.fabrica.responsavel)
        pedido = criar_pedido(criar_loja(self.conta, "Lapa"), self.coxinha, quantidade=2, da_fabrica=True)
        self.client.post("/api/v1/fabrica/etiquetas/", {"pedidos": [str(pedido.public_id)]}, format="json")

        resposta = self.client.get("/api/v1/fabrica/disponivel/")

        self.assertEqual(resposta.status_code, 200)
        linha = resposta.data[0]
        self.assertEqual(
            (linha["produto_nome"], linha["estoque"], linha["a_caminho"], linha["disponivel"]),
            ("Coxinha", 5, 2, 3),
        )
