from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from app.models import Caixa, Estoque, LeituraCaixa, MovimentacaoEstoque, Pedido
from app.services.fabrica import imprimir_etiquetas
from app.tests.fabricas import (
    criar_conta,
    criar_fabrica,
    criar_gerente,
    criar_loja,
    criar_pedido,
    criar_produto,
)


class CenarioDeLeitura(TestCase):
    """Fabrica com 5 caixas de coxinha e um pedido de 2 da Lapa ja impresso."""

    def setUp(self):
        self.conta = criar_conta()
        self.fabrica = criar_fabrica(self.conta)
        self.lapa = criar_loja(self.conta, "Lapa")
        self.moema = criar_loja(self.conta, "Moema")
        self.coxinha = criar_produto(self.conta)
        self.estoque_fabrica = Estoque.objects.create(
            loja=self.fabrica, produto=self.coxinha,
            quantidade_atual=5, quantidade_minima=0, quantidade_maxima=100,
        )
        self.pedido = self.imprimir(2)
        self.caixa1, self.caixa2 = self.pedido.caixas.order_by("numero")
        self.client = APIClient()
        self.client.force_authenticate(self.lapa.responsavel)

    def imprimir(self, quantidade, loja=None):
        pedido = criar_pedido(loja or self.lapa, self.coxinha, quantidade=quantidade, da_fabrica=True)
        resultado = imprimir_etiquetas(self.fabrica, [pedido.public_id])
        self.assertEqual(resultado.recusados, [])
        pedido.refresh_from_db()
        return pedido

    def ler(self, caixa, confirmar=False, usuario=None):
        if usuario is not None:
            self.client.force_authenticate(usuario)
        return self.client.post(
            f"/api/v1/caixas/{caixa.codigo}/ler/", {"confirmar": confirmar}, format="json"
        )

    def desfazer(self, leitura_id, usuario=None):
        if usuario is not None:
            self.client.force_authenticate(usuario)
        return self.client.post(f"/api/v1/leituras/{leitura_id}/desfazer/", format="json")

    def passar_tempo(self, minutos):
        """Empurra as leituras para o passado (created_at e auto_now_add)."""
        LeituraCaixa.objects.update(created_at=timezone.now() - timedelta(minutes=minutos))

    def estoque_da(self, loja):
        linha = Estoque.objects.filter(loja=loja, produto=self.coxinha).first()
        return linha.quantidade_atual if linha else None


class LeituraCaixaModeloTests(CenarioDeLeitura):
    def test_leitura_guarda_passo_usuario_e_caixa_fechada(self):
        leitura = LeituraCaixa.objects.create(
            caixa=self.caixa1,
            passo=Caixa.Situacao.ABERTA,
            usuario=self.lapa.responsavel,
            caixa_fechada=self.caixa2,
        )
        self.assertIsNone(leitura.desfeita_em)
        self.assertEqual(list(self.caixa1.leituras.all()), [leitura])
        self.assertIsNotNone(leitura.public_id)


class LerCaixaTests(CenarioDeLeitura):
    def test_primeira_leitura_chegou_move_da_fabrica_para_a_loja(self):
        resposta = self.ler(self.caixa1)

        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertEqual(resposta.data["caixa"]["situacao"], "CHEGOU")
        self.assertEqual(resposta.data["caixa"]["proximo"], "ABERTA")
        self.assertEqual(resposta.data["caixa"]["numero"], 1)
        self.assertEqual(resposta.data["caixa"]["total"], 2)
        self.assertEqual(resposta.data["caixa"]["caixas_chegaram"], 1)
        self.assertEqual(resposta.data["caixa"]["loja_nome"], "Lapa")
        self.assertFalse(resposta.data["ja_acabou"])
        self.assertIsNotNone(resposta.data["leitura"])
        self.assertEqual(self.estoque_da(self.fabrica), 4)
        self.assertEqual(self.estoque_da(self.lapa), 1)
        movimento = MovimentacaoEstoque.objects.get(tipo=MovimentacaoEstoque.Tipo.TRANSFERENCIA)
        self.assertEqual((movimento.loja_origem, movimento.loja_destino, movimento.quantidade),
                         (self.fabrica, self.lapa, 1))
        self.caixa1.refresh_from_db()
        self.assertIsNotNone(self.caixa1.chegou_em)
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.status, Pedido.Status.EM_ENTREGA)

    def test_ultima_caixa_entrega_o_pedido(self):
        self.ler(self.caixa1)
        resposta = self.ler(self.caixa2)

        self.assertEqual(resposta.data["caixa"]["caixas_chegaram"], 2)
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.status, Pedido.Status.ENTREGUE)
        self.assertEqual(self.estoque_da(self.lapa), 2)

    def test_segunda_leitura_abre_sem_mexer_no_estoque(self):
        self.ler(self.caixa1)
        self.passar_tempo(3)
        resposta = self.ler(self.caixa1)

        self.assertEqual(resposta.data["caixa"]["situacao"], "ABERTA")
        self.assertIsNone(resposta.data["caixa_fechada"])
        self.assertEqual(self.estoque_da(self.lapa), 1)

    def test_terceira_leitura_acaba_e_baixa_na_loja(self):
        self.ler(self.caixa1)
        self.passar_tempo(3)
        self.ler(self.caixa1)
        self.passar_tempo(3)
        resposta = self.ler(self.caixa1)

        self.assertEqual(resposta.data["caixa"]["situacao"], "ACABOU")
        self.assertIsNone(resposta.data["caixa"]["proximo"])
        self.assertEqual(self.estoque_da(self.lapa), 0)
        saida = MovimentacaoEstoque.objects.get(tipo=MovimentacaoEstoque.Tipo.SAIDA)
        self.assertEqual((saida.loja_origem, saida.quantidade), (self.lapa, 1))

    def test_caixa_que_ja_acabou_so_avisa(self):
        self.ler(self.caixa1)
        self.passar_tempo(3)
        self.ler(self.caixa1)
        self.passar_tempo(3)
        self.ler(self.caixa1)
        antes = LeituraCaixa.objects.count()

        resposta = self.ler(self.caixa1, confirmar=True)

        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.data["ja_acabou"])
        self.assertIsNone(resposta.data["leitura"])
        self.assertEqual(LeituraCaixa.objects.count(), antes)
        self.assertEqual(self.estoque_da(self.lapa), 0)

    def test_abrir_com_outra_aberta_do_mesmo_produto_fecha_a_antiga(self):
        self.ler(self.caixa1)
        self.ler(self.caixa2)
        self.passar_tempo(3)
        self.ler(self.caixa1)
        self.passar_tempo(3)

        resposta = self.ler(self.caixa2)

        self.assertEqual(resposta.data["caixa"]["situacao"], "ABERTA")
        self.assertEqual(resposta.data["caixa_fechada"]["numero"], 1)
        self.assertEqual(resposta.data["caixa_fechada"]["situacao"], "ACABOU")
        self.caixa1.refresh_from_db()
        self.assertEqual(self.caixa1.situacao, Caixa.Situacao.ACABOU)
        self.assertEqual(self.estoque_da(self.lapa), 1)
        leitura = LeituraCaixa.objects.get(public_id=resposta.data["leitura"])
        self.assertEqual(leitura.caixa_fechada, self.caixa1)

    def test_leitura_repetida_em_menos_de_2_minutos_pede_confirmacao(self):
        self.ler(self.caixa1)

        resposta = self.ler(self.caixa1)

        self.assertEqual(resposta.status_code, 409)
        self.assertEqual(resposta.data["codigo"], "precisa_confirmar")
        self.assertEqual(resposta.data["proximo"], "ABERTA")
        self.assertEqual(resposta.data["error"], "Essa caixa chegou agora. Marcar como ABERTA?")
        self.caixa1.refresh_from_db()
        self.assertEqual(self.caixa1.situacao, Caixa.Situacao.CHEGOU)

    def test_confirmar_avanca_dentro_dos_2_minutos(self):
        self.ler(self.caixa1)
        resposta = self.ler(self.caixa1, confirmar=True)
        self.assertEqual(resposta.data["caixa"]["situacao"], "ABERTA")

    def test_caixa_de_outra_loja_e_recusada(self):
        resposta = self.ler(self.caixa1, usuario=self.moema.responsavel)

        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(resposta.data["error"], "Essa caixa é da Lapa.")
        self.assertEqual(self.estoque_da(self.fabrica), 5)

    def test_gerente_e_fabrica_nao_leem(self):
        gerente = criar_gerente("gerente@x.com", self.conta)
        self.assertEqual(self.ler(self.caixa1, usuario=gerente).status_code, 403)
        self.assertEqual(self.ler(self.caixa1, usuario=self.fabrica.responsavel).status_code, 403)

    def test_codigo_inexistente(self):
        resposta = self.client.post("/api/v1/caixas/naoexiste123/ler/", {}, format="json")
        self.assertEqual(resposta.status_code, 404)
        self.assertEqual(resposta.data["error"], "Caixa não encontrada ou pedido cancelado.")

    def test_fabrica_sem_a_caixa_no_estoque(self):
        Estoque.objects.filter(pk=self.estoque_fabrica.pk).update(quantidade_atual=0)

        resposta = self.ler(self.caixa1)

        self.assertEqual(resposta.status_code, 409)
        self.assertEqual(resposta.data["codigo"], "fabrica_sem_estoque")
        self.caixa1.refresh_from_db()
        self.assertEqual(self.caixa1.situacao, Caixa.Situacao.A_CAMINHO)
        self.assertFalse(LeituraCaixa.objects.exists())
        self.assertIsNone(self.estoque_da(self.lapa))
        self.assertFalse(MovimentacaoEstoque.objects.exists())

    def test_loja_zerada_a_mao_recusa_o_acabou(self):
        self.ler(self.caixa1)
        self.passar_tempo(3)
        self.ler(self.caixa1)
        self.passar_tempo(3)
        Estoque.objects.filter(loja=self.lapa, produto=self.coxinha).update(quantidade_atual=0)

        resposta = self.ler(self.caixa1)

        self.assertEqual(resposta.status_code, 409)
        self.assertEqual(resposta.data["codigo"], "loja_zerada")
        self.caixa1.refresh_from_db()
        self.assertEqual(self.caixa1.situacao, Caixa.Situacao.ABERTA)

    def test_fechar_a_antiga_com_loja_zerada_recusa_e_nao_muda_nenhuma_caixa(self):
        """O fechamento automatico (ao abrir outra) tambem respeita a loja zerada.

        A leitura inteira roda numa transacao so: se a baixa da caixa antiga
        falha, nem ela nem a nova caixa mudam de situacao.
        """
        self.ler(self.caixa1)
        self.ler(self.caixa2)
        self.passar_tempo(3)
        self.ler(self.caixa1)
        self.passar_tempo(3)
        Estoque.objects.filter(loja=self.lapa, produto=self.coxinha).update(quantidade_atual=0)
        antes = LeituraCaixa.objects.count()

        resposta = self.ler(self.caixa2, confirmar=True)

        self.assertEqual(resposta.status_code, 409)
        self.assertEqual(resposta.data["codigo"], "loja_zerada")
        self.caixa1.refresh_from_db()
        self.caixa2.refresh_from_db()
        self.assertEqual(self.caixa1.situacao, Caixa.Situacao.ABERTA)
        self.assertEqual(self.caixa2.situacao, Caixa.Situacao.CHEGOU)
        self.assertEqual(self.estoque_da(self.lapa), 0)
        self.assertEqual(LeituraCaixa.objects.count(), antes)

    def test_caixa_aberta_de_outra_loja_nao_e_fechada(self):
        """So fecha a antiga da mesma loja — outra loja com o mesmo produto
        aberto fica intacta."""
        pedido_moema = self.imprimir(1, loja=self.moema)
        caixa_moema = pedido_moema.caixas.get()
        self.ler(caixa_moema, usuario=self.moema.responsavel)
        self.passar_tempo(3)
        self.ler(caixa_moema, usuario=self.moema.responsavel)
        self.passar_tempo(3)

        self.ler(self.caixa1, usuario=self.lapa.responsavel)
        self.passar_tempo(3)
        resposta = self.ler(self.caixa1, usuario=self.lapa.responsavel)

        self.assertEqual(resposta.data["caixa"]["situacao"], "ABERTA")
        self.assertIsNone(resposta.data["caixa_fechada"])
        caixa_moema.refresh_from_db()
        self.assertEqual(caixa_moema.situacao, Caixa.Situacao.ABERTA)


class DesfazerLeituraTests(CenarioDeLeitura):
    def test_desfazer_chegou_devolve_para_a_fabrica(self):
        leitura = self.ler(self.caixa1).data["leitura"]

        resposta = self.desfazer(leitura)

        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertEqual(resposta.data["caixa"]["situacao"], "A_CAMINHO")
        self.assertEqual(self.estoque_da(self.fabrica), 5)
        self.assertEqual(self.estoque_da(self.lapa), 0)
        volta = MovimentacaoEstoque.objects.filter(
            tipo=MovimentacaoEstoque.Tipo.TRANSFERENCIA, loja_origem=self.lapa
        ).get()
        self.assertEqual(volta.loja_destino, self.fabrica)
        self.caixa1.refresh_from_db()
        self.assertIsNone(self.caixa1.chegou_em)
        self.assertIsNotNone(LeituraCaixa.objects.get(public_id=leitura).desfeita_em)

    def test_desfazer_a_ultima_chegada_volta_o_pedido_para_em_entrega(self):
        self.ler(self.caixa1)
        leitura = self.ler(self.caixa2).data["leitura"]

        self.desfazer(leitura)

        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.status, Pedido.Status.EM_ENTREGA)

    def test_desfazer_aberta_volta_para_chegou(self):
        self.ler(self.caixa1)
        leitura = self.ler(self.caixa1, confirmar=True).data["leitura"]

        resposta = self.desfazer(leitura)

        self.assertEqual(resposta.data["caixa"]["situacao"], "CHEGOU")
        self.caixa1.refresh_from_db()
        self.assertIsNone(self.caixa1.aberta_em)
        self.assertEqual(self.estoque_da(self.lapa), 1)

    def test_desfazer_acabou_repoe_na_loja_com_entrada(self):
        self.ler(self.caixa1)
        self.ler(self.caixa1, confirmar=True)
        leitura = self.ler(self.caixa1, confirmar=True).data["leitura"]

        resposta = self.desfazer(leitura)

        self.assertEqual(resposta.data["caixa"]["situacao"], "ABERTA")
        self.assertEqual(self.estoque_da(self.lapa), 1)
        self.assertTrue(MovimentacaoEstoque.objects.filter(
            tipo=MovimentacaoEstoque.Tipo.ENTRADA, loja_destino=self.lapa
        ).exists())

    def test_desfazer_abertura_reabre_a_caixa_fechada_junto(self):
        self.ler(self.caixa1)
        self.ler(self.caixa2)
        self.ler(self.caixa1, confirmar=True)
        leitura = self.ler(self.caixa2, confirmar=True).data["leitura"]
        self.assertEqual(self.estoque_da(self.lapa), 1)

        resposta = self.desfazer(leitura)

        self.assertEqual(resposta.data["caixa"]["situacao"], "CHEGOU")
        self.assertEqual(resposta.data["caixa_reaberta"]["numero"], 1)
        self.caixa1.refresh_from_db()
        self.assertEqual(self.caixa1.situacao, Caixa.Situacao.ABERTA)
        self.assertIsNone(self.caixa1.acabou_em)
        self.assertEqual(self.estoque_da(self.lapa), 2)

    def test_so_desfaz_a_ultima_leitura_da_caixa(self):
        primeira = self.ler(self.caixa1).data["leitura"]
        self.ler(self.caixa1, confirmar=True)

        resposta = self.desfazer(primeira)

        self.assertEqual(resposta.status_code, 409)
        self.assertEqual(resposta.data["error"], "Essa caixa já foi lida de novo.")

    def test_nao_desfaz_duas_vezes(self):
        leitura = self.ler(self.caixa1).data["leitura"]
        self.desfazer(leitura)

        resposta = self.desfazer(leitura)

        self.assertEqual(resposta.status_code, 409)
        self.assertEqual(resposta.data["codigo"], "ja_desfeita")
        self.assertEqual(self.estoque_da(self.fabrica), 5)

    def test_prazo_de_10_minutos(self):
        leitura = self.ler(self.caixa1).data["leitura"]
        self.passar_tempo(11)

        resposta = self.desfazer(leitura)

        self.assertEqual(resposta.status_code, 409)
        self.assertEqual(resposta.data["error"], "Passou o prazo para desfazer essa leitura.")

    def test_outra_loja_nao_desfaz(self):
        leitura = self.ler(self.caixa1).data["leitura"]

        resposta = self.desfazer(leitura, usuario=self.moema.responsavel)

        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(self.estoque_da(self.lapa), 1)

    def test_leitura_inexistente(self):
        resposta = self.desfazer("00000000-0000-0000-0000-000000000000")
        self.assertEqual(resposta.status_code, 404)


class CancelarDepoisDeDesfazerTests(CenarioDeLeitura):
    """Caixa lida e desfeita volta para A_CAMINHO mas fica com LeituraCaixa
    (todas desfeitas, por construcao): o cancelamento tem que apagar essas
    leituras antes das caixas, ou o PROTECT da FK barra o delete."""

    def test_cancelar_depois_de_desfazer_apaga_caixas_e_leituras(self):
        leitura = self.ler(self.caixa1).data["leitura"]
        self.desfazer(leitura)
        gerente = criar_gerente("gerente@x.com", self.conta)
        # O setUp autentica a loja; o cancelamento em EM_ENTREGA e so da gerencia.
        self.client.force_authenticate(gerente)
        resposta = self.client.patch(
            f"/api/v1/pedidos/{self.pedido.public_id}/status/",
            {"status": "CANCELADO"},
            format="json",
        )

        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.status, Pedido.Status.CANCELADO)
        self.assertFalse(Caixa.objects.filter(pedido=self.pedido).exists())
        self.assertFalse(LeituraCaixa.objects.filter(caixa__pedido=self.pedido).exists())
