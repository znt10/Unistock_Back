from django.test import TestCase
from rest_framework.test import APIClient

from app.api.v1.serializers.pedidos import MENSAGEM_UM_PRODUTO
from app.models import Notificacao, Pedido
from app.tests.fabricas import (
    criar_conta,
    criar_fabrica,
    criar_loja,
    criar_pedido,
    criar_produto,
)


class PedidoUmProdutoTests(TestCase):
    def setUp(self):
        self.conta = criar_conta()
        self.fabrica = criar_fabrica(self.conta)
        self.lapa = criar_loja(self.conta, "Lapa")
        self.coxinha = criar_produto(self.conta)
        self.detergente = criar_produto(
            self.conta, "Detergente", "Mercado", vem_da_fabrica=False
        )
        self.client = APIClient()
        self.client.force_authenticate(self.lapa.responsavel)

    def pedir(self, *itens, loja=None):
        return self.client.post(
            "/api/v1/pedidos/",
            {
                "loja": str((loja or self.lapa).public_id),
                "itens": [
                    {"produto": str(produto.public_id), "quantidade": quantidade}
                    for produto, quantidade in itens
                ],
            },
            format="json",
        )

    def test_recusa_mais_de_um_produto(self):
        resposta = self.pedir((self.coxinha, 2), (self.detergente, 1))
        self.assertEqual(resposta.status_code, 400)
        self.assertIn(MENSAGEM_UM_PRODUTO, str(resposta.data))
        self.assertEqual(Pedido.objects.count(), 0)

    def test_produto_da_fabrica_nasce_pedido_da_fabrica(self):
        resposta = self.pedir((self.coxinha, 2))
        self.assertEqual(resposta.status_code, 201, resposta.data)
        self.assertTrue(resposta.data["da_fabrica"])
        self.assertEqual(resposta.data["caixas_total"], 0)
        self.assertEqual(resposta.data["caixas_chegaram"], 0)
        self.assertEqual(resposta.data["loja_nome"], "Lapa")
        self.assertTrue(Pedido.objects.get(public_id=resposta.data["id"]).da_fabrica)

    def test_sem_fabrica_cadastrada_segue_o_fluxo_de_hoje(self):
        self.fabrica.ativo = False
        self.fabrica.save()
        resposta = self.pedir((self.coxinha, 2))
        self.assertFalse(resposta.data["da_fabrica"])

    def test_produto_que_nao_vem_da_fabrica(self):
        resposta = self.pedir((self.detergente, 1))
        self.assertFalse(resposta.data["da_fabrica"])

    def test_mudar_o_produto_depois_nao_muda_o_pedido(self):
        resposta = self.pedir((self.coxinha, 2))
        self.coxinha.vem_da_fabrica = False
        self.coxinha.save()
        self.assertTrue(Pedido.objects.get(public_id=resposta.data["id"]).da_fabrica)

    def test_fabrica_nao_pede_produto_da_fabrica(self):
        self.client.force_authenticate(self.fabrica.responsavel)
        resposta = self.pedir((self.coxinha, 1), loja=self.fabrica)
        self.assertEqual(resposta.status_code, 400)

    def test_fabrica_e_avisada_do_pedido(self):
        self.pedir((self.coxinha, 2))
        self.assertTrue(
            Notificacao.objects.filter(
                usuario=self.fabrica.responsavel, tipo="novo_pedido"
            ).exists()
        )
        aviso = Notificacao.objects.get(usuario=self.lapa.responsavel, tipo="pedido_criado")
        self.assertIn("enviado para a fábrica", aviso.mensagem)

    def test_pedido_da_fabrica_em_entrega_nao_edita(self):
        pedido = criar_pedido(
            self.lapa, self.coxinha, da_fabrica=True, status=Pedido.Status.EM_ENTREGA
        )
        resposta = self.client.patch(
            f"/api/v1/pedidos/{pedido.public_id}/", {"descricao": "x"}, format="json"
        )
        self.assertEqual(resposta.status_code, 400)

    def test_trocar_produto_para_outro_fluxo_e_recusado(self):
        pedido = criar_pedido(self.lapa, self.coxinha, da_fabrica=True)
        resposta = self.client.patch(
            f"/api/v1/pedidos/{pedido.public_id}/",
            {"itens": [{"produto": str(self.detergente.public_id), "quantidade": 1}]},
            format="json",
        )
        self.assertEqual(resposta.status_code, 400)
