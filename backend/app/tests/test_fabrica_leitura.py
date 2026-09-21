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
