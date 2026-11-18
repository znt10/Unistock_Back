from django.test import TestCase
from rest_framework.test import APIClient

from app.models import Caixa, Estoque, MovimentacaoEstoque, ToqueEstoque
from app.services.fabrica import imprimir_etiquetas
from app.tests.fabricas import (
    criar_conta,
    criar_fabrica,
    criar_gerente,
    criar_loja,
    criar_pedido,
    criar_produto,
)

T = MovimentacaoEstoque.Tipo


class CenarioDeToque(TestCase):
    """Fabrica com 5 caixas de coxinha e um pedido de 2 da Lapa ja impresso."""

    def setUp(self):
        self.conta = criar_conta()
        self.fabrica = criar_fabrica(self.conta)
        self.lapa = criar_loja(self.conta, "Lapa")
        self.moema = criar_loja(self.conta, "Moema")
        self.coxinha = criar_produto(self.conta)
        self.detergente = criar_produto(
            self.conta, "Detergente", categoria="Mercado", vem_da_fabrica=False
        )
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
        return pedido

    def tocar(self, loja, produto, delta, usuario=None):
        if usuario is not None:
            self.client.force_authenticate(usuario)
        return self.client.post(
            "/api/v1/estoque/tocar/",
            {"loja": str(loja.public_id), "produto": str(produto.public_id), "delta": delta},
            format="json",
        )

    def ler(self, caixa, confirmar=False, usuario=None):
        if usuario is not None:
            self.client.force_authenticate(usuario)
        return self.client.post(
            f"/api/v1/caixas/{caixa.codigo}/ler/", {"confirmar": confirmar}, format="json"
        )

    def situacao(self, caixa):
        return Caixa.objects.get(pk=caixa.pk).situacao

    def quantidade(self, loja, produto):
        return Estoque.objects.get(loja=loja, produto=produto).quantidade_atual

    def estoque_com(self, loja, produto, quantidade):
        return Estoque.objects.create(
            loja=loja, produto=produto,
            quantidade_atual=quantidade, quantidade_minima=0, quantidade_maxima=100,
        )


class ToqueNaFabricaTests(CenarioDeToque):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.fabrica.responsavel)

    def test_fabrica_mais_um_e_producao(self):
        r = self.tocar(self.fabrica, self.coxinha, 1)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["quantidade"], 6)
        self.assertEqual(r.data["significado"], "PRODUCAO")
        self.assertIsNone(r.data["caixa"])
        self.assertEqual(self.quantidade(self.fabrica, self.coxinha), 6)
        mov = MovimentacaoEstoque.objects.get(tipo=T.ENTRADA)
        self.assertEqual(mov.quantidade, 1)
        self.assertEqual(mov.loja_destino, self.fabrica)
        self.assertEqual(mov.usuario, self.fabrica.responsavel)
        toque = ToqueEstoque.objects.get()
        self.assertEqual(toque.significado, ToqueEstoque.Significado.PRODUCAO)
        self.assertEqual(toque.usuario, self.fabrica.responsavel)
        self.assertEqual(toque.movimentacao, mov)
        self.assertEqual(r.data["toque"], str(toque.public_id))

    def test_fabrica_mais_um_cria_a_linha(self):
        novo = criar_produto(self.conta, "Risole")
        r = self.tocar(self.fabrica, novo, 1)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["quantidade"], 1)
        linha = Estoque.objects.get(loja=self.fabrica, produto=novo)
        self.assertEqual(linha.quantidade_minima, novo.estoque_minimo_sugerido)

    def test_fabrica_menos_um_e_correcao(self):
        # o setUp imprimiu 2 caixas; sobram 3 de folga
        r = self.tocar(self.fabrica, self.coxinha, -1)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["quantidade"], 4)
        self.assertEqual(r.data["significado"], "CORRECAO")
        mov = MovimentacaoEstoque.objects.get(tipo=T.AJUSTE)
        self.assertEqual(mov.quantidade, -1)
        self.assertEqual(mov.loja_origem, self.fabrica)
        self.assertEqual(ToqueEstoque.objects.get().significado, "CORRECAO")

    def test_fabrica_nao_baixa_abaixo_das_caixas_a_caminho(self):
        self.imprimir(3)  # 2 + 3 = 5 a caminho, estoque 5
        antes = MovimentacaoEstoque.objects.count()
        r = self.tocar(self.fabrica, self.coxinha, -1)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data["codigo"], "a_caminho")
        self.assertEqual(r.data["error"], "Tem 5 caixas impressas a caminho; não dá para baixar mais.")
        self.assertEqual(self.quantidade(self.fabrica, self.coxinha), 5)
        self.assertEqual(MovimentacaoEstoque.objects.count(), antes)

    def test_fabrica_produto_que_nao_vem_da_fabrica(self):
        r = self.tocar(self.fabrica, self.detergente, 1)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["codigo"], "produto_invalido")
        self.assertEqual(r.data["error"], "Esse produto não vem da fábrica.")


class ToqueNaLojaTests(CenarioDeToque):
    def test_loja_mais_um_em_salgado_e_correcao(self):
        r = self.tocar(self.lapa, self.coxinha, 1)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["quantidade"], 1)
        self.assertEqual(r.data["significado"], "CORRECAO")
        mov = MovimentacaoEstoque.objects.get(tipo=T.AJUSTE)
        self.assertEqual(mov.quantidade, 1)
        self.assertEqual(mov.loja_origem, self.lapa)

    def test_loja_menos_um_sem_caixa_e_correcao(self):
        self.estoque_com(self.lapa, self.detergente, 3)
        r = self.tocar(self.lapa, self.detergente, -1)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["quantidade"], 2)
        self.assertEqual(r.data["significado"], "CORRECAO")
        mov = MovimentacaoEstoque.objects.get(tipo=T.AJUSTE)
        self.assertEqual(mov.quantidade, -1)
        self.assertEqual(mov.loja_origem, self.lapa)

    def test_nao_fica_negativo(self):
        self.estoque_com(self.lapa, self.detergente, 0)
        antes = MovimentacaoEstoque.objects.count()
        r = self.tocar(self.lapa, self.detergente, -1)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data["codigo"], "zerado")
        self.assertEqual(r.data["error"], "O estoque já está zerado.")
        self.assertEqual(MovimentacaoEstoque.objects.count(), antes)
        self.assertEqual(ToqueEstoque.objects.count(), 0)

    def test_dois_toques_seguidos_somam(self):
        self.tocar(self.lapa, self.detergente, 1)
        r = self.tocar(self.lapa, self.detergente, 1)
        self.assertEqual(r.data["quantidade"], 2)
        self.assertEqual(ToqueEstoque.objects.count(), 2)

    def test_delta_invalido(self):
        r = self.tocar(self.lapa, self.detergente, 2)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(ToqueEstoque.objects.count(), 0)

    def test_produto_de_outra_conta(self):
        outro = criar_produto(criar_conta("Outra"), "Pao", vem_da_fabrica=False)
        r = self.tocar(self.lapa, outro, 1)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["codigo"], "produto_invalido")

    def test_loja_ou_produto_inexistente(self):
        r = self.client.post(
            "/api/v1/estoque/tocar/",
            {"loja": "00000000-0000-4000-8000-000000000000",
             "produto": str(self.detergente.public_id), "delta": 1},
            format="json",
        )
        self.assertEqual(r.status_code, 404)


class ToqueQueEncerraCaixaTests(CenarioDeToque):
    """Lapa com as 2 caixas lidas (CHEGOU, estoque 2); -1 fecha uma caixa."""

    def setUp(self):
        super().setUp()
        for caixa in (self.caixa1, self.caixa2):
            self.assertEqual(self.ler(caixa).status_code, 200)

    def test_menos_um_encerra_a_caixa_aberta(self):
        self.assertEqual(self.ler(self.caixa1, confirmar=True).status_code, 200)  # abre
        antes = MovimentacaoEstoque.objects.filter(tipo=T.SAIDA).count()
        r = self.tocar(self.lapa, self.coxinha, -1)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.situacao(self.caixa1), "ACABOU")
        self.assertEqual(self.situacao(self.caixa2), "CHEGOU")
        self.assertIsNotNone(Caixa.objects.get(pk=self.caixa1.pk).acabou_em)
        self.assertEqual(self.quantidade(self.lapa, self.coxinha), 1)
        self.assertEqual(r.data["quantidade"], 1)
        self.assertEqual(MovimentacaoEstoque.objects.filter(tipo=T.SAIDA).count(), antes + 1)
        mov = MovimentacaoEstoque.objects.filter(tipo=T.SAIDA).latest("id")
        self.assertEqual(mov.quantidade, 1)
        self.assertEqual(mov.loja_origem, self.lapa)
        self.assertEqual(r.data["significado"], "FIM_DE_CAIXA")
        toque = ToqueEstoque.objects.get()
        self.assertEqual(toque.significado, "FIM_DE_CAIXA")
        self.assertEqual(toque.caixa, self.caixa1)
        self.assertEqual(toque.situacao_anterior_da_caixa, "ABERTA")
        self.assertEqual(toque.movimentacao, mov)
        self.assertEqual(r.data["caixa"], {"numero": 1, "total": 2})

    def test_sem_aberta_encerra_a_chegou_mais_antiga(self):
        r = self.tocar(self.lapa, self.coxinha, -1)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.situacao(self.caixa1), "ACABOU")
        self.assertEqual(self.situacao(self.caixa2), "CHEGOU")
        self.assertEqual(ToqueEstoque.objects.get().situacao_anterior_da_caixa, "CHEGOU")
        self.assertEqual(self.quantidade(self.lapa, self.coxinha), 1)

    def test_ler_a_caixa_encerrada_nao_tira_de_novo(self):
        self.tocar(self.lapa, self.coxinha, -1)
        r = self.ler(self.caixa1, confirmar=True)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["ja_acabou"])
        self.assertEqual(self.quantidade(self.lapa, self.coxinha), 1)

    def test_menos_um_e_abrir_a_proxima_tira_so_um(self):
        self.ler(self.caixa1, confirmar=True)  # abre
        self.tocar(self.lapa, self.coxinha, -1)
        self.assertEqual(self.quantidade(self.lapa, self.coxinha), 1)
        r = self.ler(self.caixa2, confirmar=True)  # CHEGOU -> ABERTA
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.situacao(self.caixa2), "ABERTA")
        self.assertEqual(self.quantidade(self.lapa, self.coxinha), 1)

    def test_caixa_de_outra_loja_nao_e_encerrada(self):
        pedido = self.imprimir(1, loja=self.moema)
        caixa_moema = pedido.caixas.get()
        self.assertEqual(self.ler(caixa_moema, usuario=self.moema.responsavel).status_code, 200)
        self.assertEqual(self.situacao(caixa_moema), "CHEGOU")
        # Lapa sem caixa em jogo: zera as duas dela e da +1 por toque
        Caixa.objects.filter(pedido=self.pedido).update(situacao="A_CAMINHO")
        Estoque.objects.filter(loja=self.lapa, produto=self.coxinha).update(quantidade_atual=0)
        self.assertEqual(self.tocar(self.lapa, self.coxinha, 1, usuario=self.lapa.responsavel).status_code, 200)
        r = self.tocar(self.lapa, self.coxinha, -1)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["significado"], "CORRECAO")
        self.assertIsNone(r.data["caixa"])
        self.assertEqual(self.situacao(caixa_moema), "CHEGOU")

    def test_zerado_nao_encerra_caixa(self):
        Estoque.objects.filter(loja=self.lapa, produto=self.coxinha).update(quantidade_atual=0)
        r = self.tocar(self.lapa, self.coxinha, -1)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data["codigo"], "zerado")
        self.assertEqual(self.situacao(self.caixa1), "CHEGOU")

    def test_salgado_sem_caixa_e_correcao(self):
        Caixa.objects.filter(pedido=self.pedido).update(situacao="ACABOU")
        r = self.tocar(self.lapa, self.coxinha, -1)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["significado"], "CORRECAO")
        self.assertIsNone(r.data["caixa"])
        self.assertEqual(MovimentacaoEstoque.objects.filter(tipo=T.AJUSTE).count(), 1)


class PermissaoDoToqueTests(CenarioDeToque):
    def test_responsavel_de_outra_loja_nao_toca(self):
        r = self.tocar(self.lapa, self.detergente, 1, usuario=self.moema.responsavel)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data["codigo"], "sem_permissao")
        self.assertEqual(r.data["error"], "Você só mexe no estoque da sua loja.")

    def test_gerente_da_conta_toca(self):
        gerente = criar_gerente("gerente@x.com", self.conta)
        r = self.tocar(self.lapa, self.detergente, 1, usuario=gerente)
        self.assertEqual(r.status_code, 200, r.data)

    def test_gerente_de_outra_conta_nao_toca(self):
        gerente = criar_gerente("gerente@outra.com", criar_conta("Outra"))
        r = self.tocar(self.lapa, self.detergente, 1, usuario=gerente)
        self.assertEqual(r.status_code, 403)
