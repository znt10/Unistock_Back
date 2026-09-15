from django.test import TestCase, override_settings
from rest_framework.test import APIClient, APITestCase

from app.models import Caixa, Estoque, Pedido
from app.tests.fabricas import (
    criar_conta,
    criar_fabrica,
    criar_gerente,
    criar_loja,
    criar_pedido,
    criar_produto,
)


class PedidosQueCadaUmVeTests(TestCase):
    def setUp(self):
        self.conta = criar_conta("Empresa A")
        self.gerente = criar_gerente("ger@x.com", self.conta)
        self.fabrica = criar_fabrica(self.conta)
        self.lapa = criar_loja(self.conta, "Lapa")
        coxinha = criar_produto(self.conta)
        detergente = criar_produto(self.conta, "Detergente", "Mercado", vem_da_fabrica=False)

        self.da_fabrica = criar_pedido(self.lapa, coxinha, da_fabrica=True)
        self.de_mercado = criar_pedido(self.lapa, detergente)
        self.da_propria_fabrica = criar_pedido(self.fabrica, detergente)

        conta_b = criar_conta("Empresa B")
        criar_fabrica(conta_b)
        self.alheio = criar_pedido(criar_loja(conta_b, "Centro"), criar_produto(conta_b), da_fabrica=True)

    def ids(self, usuario, consulta=""):
        client = APIClient()
        client.force_authenticate(usuario)
        resposta = client.get(f"/api/v1/pedidos/{consulta}")
        return {item["id"] for item in resposta.data.get("results", resposta.data)}

    def test_fabrica_ve_os_da_fabrica_da_empresa_e_os_proprios(self):
        self.assertEqual(
            self.ids(self.fabrica.responsavel),
            {str(self.da_fabrica.public_id), str(self.da_propria_fabrica.public_id)},
        )

    def test_loja_continua_vendo_so_os_proprios(self):
        self.assertEqual(
            self.ids(self.lapa.responsavel),
            {str(self.da_fabrica.public_id), str(self.de_mercado.public_id)},
        )

    def test_filtro_da_fabrica(self):
        self.assertEqual(
            self.ids(self.gerente, "?da_fabrica=true"), {str(self.da_fabrica.public_id)}
        )

    def test_leitura_traz_o_progresso_das_caixas(self):
        self.da_fabrica.status = Pedido.Status.EM_ENTREGA
        self.da_fabrica.save()
        Caixa.objects.create(pedido=self.da_fabrica, numero=1, codigo="c1", situacao=Caixa.Situacao.CHEGOU)
        Caixa.objects.create(pedido=self.da_fabrica, numero=2, codigo="c2")
        Caixa.objects.create(pedido=self.da_fabrica, numero=3, codigo="c3")

        client = APIClient()
        client.force_authenticate(self.gerente)
        resposta = client.get("/api/v1/pedidos/?da_fabrica=true")
        item = resposta.data["results"][0]
        self.assertEqual((item["caixas_total"], item["caixas_chegaram"]), (3, 1))

    def test_fabrica_nao_muda_pedido_da_loja(self):
        client = APIClient()
        client.force_authenticate(self.fabrica.responsavel)
        resposta = client.patch(
            f"/api/v1/pedidos/{self.da_fabrica.public_id}/status/",
            {"status": "CANCELADO"},
            format="json",
        )
        self.assertEqual(resposta.status_code, 403)

    def test_pedido_com_etiqueta_nao_e_apagado(self):
        Caixa.objects.create(pedido=self.da_fabrica, numero=1, codigo="c1")
        client = APIClient()
        client.force_authenticate(self.lapa.responsavel)
        resposta = client.delete(f"/api/v1/pedidos/{self.da_fabrica.public_id}/")
        self.assertEqual(resposta.status_code, 403)


class EstoqueDeProdutoDaFabricaTests(TestCase):
    def setUp(self):
        self.conta = criar_conta()
        self.fabrica = criar_fabrica(self.conta)
        self.lapa = criar_loja(self.conta, "Lapa")
        self.gerente = criar_gerente("ger@x.com", self.conta)
        self.estoque = Estoque.objects.create(
            loja=self.lapa, produto=criar_produto(self.conta),
            quantidade_atual=2, quantidade_minima=1, quantidade_maxima=10,
        )

    def patch(self, usuario, dados):
        client = APIClient()
        client.force_authenticate(usuario)
        return client.patch(f"/api/v1/estoque/{self.estoque.public_id}/", dados, format="json")

    def test_responsavel_nao_muda_a_quantidade(self):
        resposta = self.patch(self.lapa.responsavel, {"quantidade_atual": 5})
        self.assertEqual(resposta.status_code, 403)
        self.estoque.refresh_from_db()
        self.assertEqual(self.estoque.quantidade_atual, 2)

    def test_responsavel_muda_minimo_e_maximo(self):
        resposta = self.patch(self.lapa.responsavel, {"quantidade_minima": 2, "quantidade_maxima": 12})
        self.assertEqual(resposta.status_code, 200, resposta.data)

    def test_gerente_corrige_a_quantidade(self):
        resposta = self.patch(self.gerente, {"quantidade_atual": 5})
        self.assertEqual(resposta.status_code, 200, resposta.data)

    def test_sem_fabrica_cadastrada_responsavel_muda_como_hoje(self):
        self.fabrica.ativo = False
        self.fabrica.save()
        resposta = self.patch(self.lapa.responsavel, {"quantidade_atual": 5})
        self.assertEqual(resposta.status_code, 200, resposta.data)


@override_settings(BOT_SERVICE_TOKEN="token-de-teste")
class BotRemoverProdutoDaFabricaTests(APITestCase):
    def test_recusa_baixa_manual(self):
        conta = criar_conta()
        criar_fabrica(conta)
        lapa = criar_loja(conta, "Lapa", telefone_whatsapp="5583999998888")
        coxinha = criar_produto(conta)
        estoque = Estoque.objects.create(
            loja=lapa, produto=coxinha, quantidade_atual=5, quantidade_minima=1, quantidade_maxima=10,
        )

        resposta = self.client.post(
            "/api/v1/bot/estoque/remover/",
            {"telefone": "5583999998888", "itens": [{"codigo": coxinha.id, "quantidade": 1}]},
            format="json",
            HTTP_X_BOT_TOKEN="token-de-teste",
        )

        self.assertEqual(resposta.status_code, 409)
        self.assertIn("etiqueta da caixa", resposta.data["error"])
        estoque.refresh_from_db()
        self.assertEqual(estoque.quantidade_atual, 5)
