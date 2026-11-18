"""Estoque.niveis_definidos: a gerencia ja definiu minimo/maximo nesta loja?

Linha criada sozinha (chegada de caixa, toque, pedido entregue) nasce com os
niveis sugeridos do produto, mas ninguem os definiu: a tela de Minimo e
maximo mostra um "?" ate alguem salvar.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from app.models import Categoria, Estoque, Loja, Produto
from app.tests.fabricas import criar_conta, criar_gerente, criar_responsavel


class NiveisDefinidosTests(TestCase):
    def setUp(self):
        self.conta = criar_conta("Empresa A")
        self.gerente = criar_gerente("ger@x.com", self.conta)
        resp = criar_responsavel("lapa@x.com", self.conta)
        self.lapa = Loja.objects.create(
            nome_loja="Lapa", cidade="Patos", endereco="Rua 1",
            conta=self.conta, responsavel=resp,
        )
        categoria = Categoria.objects.create(nome="Mercado", conta=self.conta)
        self.detergente = Produto.objects.create(
            nome_produto="Detergente", categoria=categoria, conta=self.conta,
            estoque_minimo_sugerido=2, estoque_maximo_sugerido=6,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.gerente)

    def _linha(self):
        return Estoque.objects.create(
            loja=self.lapa, produto=self.detergente,
            quantidade_atual=3, quantidade_minima=2, quantidade_maxima=6,
        )

    def test_linha_nova_nasce_sem_niveis_definidos(self):
        self.assertFalse(self._linha().niveis_definidos)

    def test_leitura_mostra_o_campo(self):
        linha = self._linha()
        resp = self.client.get("/api/v1/estoque/")
        item = next(i for i in resp.data["results"] if i["id"] == str(linha.public_id))
        self.assertIs(item["niveis_definidos"], False)

    def test_salvar_minimo_marca_definido(self):
        linha = self._linha()
        resp = self.client.patch(
            f"/api/v1/estoque/{linha.public_id}/", {"quantidade_minima": 3}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        linha.refresh_from_db()
        self.assertTrue(linha.niveis_definidos)
        self.assertIs(resp.data["niveis_definidos"], True)

    def test_salvar_o_mesmo_valor_sugerido_tambem_marca(self):
        linha = self._linha()
        self.client.patch(
            f"/api/v1/estoque/{linha.public_id}/",
            {"quantidade_minima": 2, "quantidade_maxima": 6},
            format="json",
        )
        linha.refresh_from_db()
        self.assertTrue(linha.niveis_definidos)

    def test_mexer_so_na_quantidade_nao_marca(self):
        linha = self._linha()
        self.client.patch(
            f"/api/v1/estoque/{linha.public_id}/", {"quantidade_atual": 5}, format="json"
        )
        linha.refresh_from_db()
        self.assertFalse(linha.niveis_definidos)

    def test_criar_com_niveis_marca_definido(self):
        resp = self.client.post(
            "/api/v1/estoque/",
            {
                "loja": str(self.lapa.public_id),
                "produto": str(self.detergente.public_id),
                "quantidade_atual": 0,
                "quantidade_minima": 1,
                "quantidade_maxima": 4,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertTrue(Estoque.objects.get(loja=self.lapa, produto=self.detergente).niveis_definidos)
