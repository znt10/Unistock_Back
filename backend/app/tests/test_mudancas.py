"""GET /api/v1/mudancas/ — a "versao" que o front consulta a cada 5s.

O front so compara a resposta com a anterior: se mudou, recarrega o grupo.
Entao o que importa aqui e (1) mudar quando algo muda, inclusive apagar e
ler caixa, e (2) NAO mudar por causa de outra conta.
"""

from rest_framework.test import APIClient
from django.test import TestCase

from app.models import Caixa, Estoque
from app.tests.fabricas import (
    criar_admin,
    criar_conta,
    criar_gerente,
    criar_loja,
    criar_pedido,
    criar_produto,
    criar_usuario,
)

URL = "/api/v1/mudancas/"


def montar_conta(nome):
    conta = criar_conta(nome)
    loja = criar_loja(conta, f"Loja {nome}")
    produto = criar_produto(conta)
    estoque = Estoque.objects.create(
        loja=loja, produto=produto, quantidade_atual=5,
        quantidade_minima=2, quantidade_maxima=20,
    )
    pedido = criar_pedido(loja, produto)
    return conta, loja, produto, estoque, pedido


class MudancasTests(TestCase):
    def setUp(self):
        self.conta_a, self.loja_a, self.produto_a, self.estoque_a, self.pedido_a = montar_conta("A")
        self.conta_b, self.loja_b, self.produto_b, self.estoque_b, self.pedido_b = montar_conta("B")
        self.gerente_a = criar_gerente("gerente-a@x.com", self.conta_a)

    def versao(self, user):
        client = APIClient()
        if user:
            client.force_authenticate(user)
        return client.get(URL)

    def test_sem_login_bloqueado(self):
        # O projeto autentica por cookie JWT sem WWW-Authenticate, entao o DRF
        # responde 403 (e nao 401) a quem nao esta logado — igual as outras rotas.
        self.assertEqual(self.versao(None).status_code, 403)

    def test_formato(self):
        r = self.versao(self.gerente_a)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.json()), {"pedidos", "estoque"})

    def test_nada_muda_versao_igual(self):
        self.assertEqual(self.versao(self.gerente_a).json(), self.versao(self.gerente_a).json())

    def test_criar_pedido_muda_pedidos_nao_estoque(self):
        antes = self.versao(self.gerente_a).json()
        criar_pedido(self.loja_a, self.produto_a)
        depois = self.versao(self.gerente_a).json()
        self.assertNotEqual(antes["pedidos"], depois["pedidos"])
        self.assertEqual(antes["estoque"], depois["estoque"])

    def test_editar_estoque_muda_estoque(self):
        antes = self.versao(self.gerente_a).json()
        self.estoque_a.quantidade_atual += 1
        self.estoque_a.save()
        self.assertNotEqual(antes["estoque"], self.versao(self.gerente_a).json()["estoque"])

    def test_apagar_estoque_muda_estoque(self):
        antes = self.versao(self.gerente_a).json()
        Estoque.objects.filter(pk=self.estoque_a.pk).delete()
        self.assertNotEqual(antes["estoque"], self.versao(self.gerente_a).json()["estoque"])

    def test_caixa_lida_muda_pedidos(self):
        caixa = Caixa.objects.create(pedido=self.pedido_a, numero=1, codigo="abc123")
        antes = self.versao(self.gerente_a).json()
        caixa.situacao = Caixa.Situacao.CHEGOU
        caixa.save()
        self.assertNotEqual(antes["pedidos"], self.versao(self.gerente_a).json()["pedidos"])

    def test_outra_conta_nao_afeta(self):
        antes = self.versao(self.gerente_a).json()
        criar_pedido(self.loja_b, self.produto_b)
        self.estoque_b.quantidade_atual += 1
        self.estoque_b.save()
        self.assertEqual(antes, self.versao(self.gerente_a).json())

    def test_responsavel_ve_versao_da_conta(self):
        self.assertEqual(
            self.versao(self.loja_a.responsavel).json(),
            self.versao(self.gerente_a).json(),
        )

    def test_usuario_sem_conta_200(self):
        orfao = criar_usuario("orfao@x.com")
        self.assertEqual(self.versao(orfao).status_code, 200)

    def test_admin_ve_mudanca_de_qualquer_conta(self):
        admin = criar_admin()
        antes = self.versao(admin).json()
        self.estoque_b.quantidade_atual += 1
        self.estoque_b.save()
        self.assertNotEqual(antes["estoque"], self.versao(admin).json()["estoque"])
