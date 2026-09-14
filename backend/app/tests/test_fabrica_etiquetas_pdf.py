from unittest import skipUnless

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from app.models import Caixa, Pedido
from app.relatorios.etiquetas_pdf import (
    html_das_etiquetas,
    link_da_caixa,
    tamanho_da_fonte_da_loja,
)
from app.services.fabrica import caixas_para_etiqueta
from app.tests.fabricas import (
    criar_conta,
    criar_fabrica,
    criar_loja,
    criar_pedido,
    criar_produto,
)

try:
    import weasyprint  # noqa: F401
    HAS_WEASYPRINT = True
except Exception:
    HAS_WEASYPRINT = False


class EtiquetaTests(TestCase):
    def setUp(self):
        conta = criar_conta()
        self.fabrica = criar_fabrica(conta)
        self.pedido = criar_pedido(
            criar_loja(conta, "Lapa"), criar_produto(conta), quantidade=2,
            da_fabrica=True, status=Pedido.Status.EM_ENTREGA,
        )
        Caixa.objects.create(pedido=self.pedido, numero=1, codigo="cod1")
        Caixa.objects.create(pedido=self.pedido, numero=2, codigo="cod2")

    @override_settings(FRONTEND_URL="https://unistock.exemplo")
    def test_link_da_caixa(self):
        self.assertEqual(link_da_caixa("cod1"), "https://unistock.exemplo/caixa/cod1")

    def test_html_tem_loja_pedido_numero_e_um_qr_por_caixa(self):
        html = html_das_etiquetas(caixas_para_etiqueta(self.fabrica, [self.pedido.public_id]))
        self.assertIn("Lapa", html)
        self.assertIn("Coxinha", html)
        self.assertIn(f"Pedido #{self.pedido.id}", html)
        self.assertIn("Caixa 1/2", html)
        self.assertIn("Caixa 2/2", html)
        self.assertEqual(html.count("data:image/svg+xml"), 2)

    def test_fonte_da_loja_pelo_tamanho_do_nome(self):
        self.assertEqual(tamanho_da_fonte_da_loja("Lapa"), "16pt")
        self.assertEqual(tamanho_da_fonte_da_loja("Casa Verde"), "12pt")
        self.assertEqual(tamanho_da_fonte_da_loja("Zilda / Casa Verde"), "9pt")

    def test_so_caixas_a_caminho(self):
        Caixa.objects.filter(pedido=self.pedido, numero=1).update(situacao=Caixa.Situacao.CHEGOU)
        caixas = caixas_para_etiqueta(self.fabrica, [self.pedido.public_id])
        self.assertEqual([caixa.numero for caixa in caixas], [2])

    def test_sem_caixas_404(self):
        client = APIClient()
        client.force_authenticate(self.fabrica.responsavel)
        Caixa.objects.filter(pedido=self.pedido).update(situacao=Caixa.Situacao.CHEGOU)
        resposta = client.get(f"/api/v1/fabrica/etiquetas/pdf/?pedidos={self.pedido.public_id}")
        self.assertEqual(resposta.status_code, 404)

    @skipUnless(HAS_WEASYPRINT, "WeasyPrint indisponivel")
    def test_endpoint_devolve_pdf(self):
        client = APIClient()
        client.force_authenticate(self.fabrica.responsavel)
        resposta = client.get(f"/api/v1/fabrica/etiquetas/pdf/?pedidos={self.pedido.public_id}")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta["Content-Type"], "application/pdf")
        self.assertTrue(resposta.content.startswith(b"%PDF"))
