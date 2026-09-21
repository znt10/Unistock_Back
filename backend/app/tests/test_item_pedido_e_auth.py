"""Gerente editando item de pedido (card #39) e erros da autenticacao (card #40)."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from app.authentication import CookieJWTAuthentication
from app.models import ItemPedido
from app.tests.fabricas import (
    criar_conta,
    criar_gerente,
    criar_loja,
    criar_pedido,
    criar_produto,
)


class GerenteEditaItemDePedidoTests(TestCase):
    def setUp(self):
        self.conta = criar_conta("Empresa A")
        self.lapa = criar_loja(self.conta, "Lapa")
        self.coxinha = criar_produto(self.conta, vem_da_fabrica=False)
        self.item = criar_pedido(self.lapa, self.coxinha, quantidade=3).itens.get()
        self.gerente = criar_gerente("gerente@x.com", self.conta)
        self.client = APIClient()
        self.client.force_authenticate(self.gerente)

    def url(self, item):
        return f"/api/v1/itens-pedido/{item.public_id}/"

    def test_gerente_da_empresa_edita_item(self):
        resposta = self.client.patch(self.url(self.item), {"quantidade": 5}, format="json")

        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantidade, 5)

    def test_gerente_da_empresa_exclui_item(self):
        resposta = self.client.delete(self.url(self.item))

        self.assertEqual(resposta.status_code, 204)
        self.assertFalse(ItemPedido.objects.filter(pk=self.item.pk).exists())

    def test_gerente_de_outra_empresa_nao_alcanca_o_item(self):
        outra = criar_conta("Empresa B")
        self.client.force_authenticate(criar_gerente("outro@x.com", outra))

        resposta = self.client.patch(self.url(self.item), {"quantidade": 5}, format="json")

        self.assertEqual(resposta.status_code, 404)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantidade, 3)

    def test_loja_continua_editando_o_proprio_item(self):
        self.client.force_authenticate(self.lapa.responsavel)

        resposta = self.client.patch(self.url(self.item), {"quantidade": 4}, format="json")

        self.assertEqual(resposta.status_code, 200, resposta.data)


class AutenticacaoPorCookieTests(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user(username="u@x.com", password="123")
        self.auth = CookieJWTAuthentication()
        self.fabrica = RequestFactory()

    def pedido_com(self, token):
        request = self.fabrica.get("/")
        request.COOKIES["access_token"] = token
        return request

    def test_token_valido_autentica(self):
        resultado = self.auth.authenticate(self.pedido_com(str(AccessToken.for_user(self.usuario))))
        self.assertEqual(resultado[0], self.usuario)

    def test_token_invalido_vira_anonimo(self):
        self.assertIsNone(self.auth.authenticate(self.pedido_com("nao-e-um-token")))

    def test_usuario_apagado_vira_anonimo(self):
        token = str(AccessToken.for_user(self.usuario))
        self.usuario.delete()
        self.assertIsNone(self.auth.authenticate(self.pedido_com(token)))

    def test_erro_inesperado_nao_e_escondido(self):
        token = str(AccessToken.for_user(self.usuario))
        with patch("app.authentication.get_user_model", side_effect=RuntimeError("banco fora")):
            with self.assertRaises(RuntimeError):
                self.auth.authenticate(self.pedido_com(token))
