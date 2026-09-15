import importlib

from django.apps import apps
from django.db import IntegrityError, transaction
from django.test import TestCase

from app.models import Caixa, Categoria, Loja, Produto
from app.tests.fabricas import criar_conta, criar_loja, criar_pedido, criar_produto

migracao = importlib.import_module("app.migrations.0031_fabrica_e_caixas")


class MigracaoDaFabricaTests(TestCase):
    def setUp(self):
        self.conta = criar_conta()

    def test_normaliza_tipo_da_loja(self):
        esperado_por_tipo = {"fábrica": "Fabrica", "FABRICA": "Fabrica", "Quiosque": "Loja", "": "Loja"}
        esperados = {}
        for indice, (antes, depois) in enumerate(esperado_por_tipo.items()):
            loja = Loja.objects.create(
                nome_loja=f"L{indice}", cidade="Patos", endereco="Rua", conta=self.conta
            )
            Loja.objects.filter(pk=loja.pk).update(tipo=antes)
            esperados[loja.pk] = depois

        migracao.normalizar_tipo_loja(apps, None)

        for pk, depois in esperados.items():
            self.assertEqual(Loja.objects.get(pk=pk).tipo, depois)

    def test_marca_produtos_pelas_categorias(self):
        esperado_por_categoria = {
            "Salgados grande": True,
            "Esfihas mini": True,
            "FOGAZZAS grande": True,
            "Recheios": False,
            "Mercado": False,
        }
        esperados = {}
        for nome, esperado in esperado_por_categoria.items():
            categoria = Categoria.objects.create(nome=nome, conta=self.conta)
            produto = Produto.objects.create(
                nome_produto=f"P {nome}", categoria=categoria, conta=self.conta
            )
            esperados[produto.pk] = esperado

        migracao.marcar_produtos_da_fabrica(apps, None)

        for pk, esperado in esperados.items():
            self.assertEqual(Produto.objects.get(pk=pk).vem_da_fabrica, esperado)


class CaixaModeloTests(TestCase):
    def test_loja_nasce_como_loja(self):
        loja = Loja.objects.create(
            nome_loja="X", cidade="Patos", endereco="Rua", conta=criar_conta()
        )
        self.assertEqual(loja.tipo, Loja.Tipo.LOJA)

    def test_numero_da_caixa_e_unico_no_pedido(self):
        conta = criar_conta()
        pedido = criar_pedido(criar_loja(conta), criar_produto(conta), da_fabrica=True)
        Caixa.objects.create(pedido=pedido, numero=1, codigo="codigo-1")

        with self.assertRaises(IntegrityError), transaction.atomic():
            Caixa.objects.create(pedido=pedido, numero=1, codigo="codigo-2")

    def test_caixa_nasce_a_caminho(self):
        conta = criar_conta()
        pedido = criar_pedido(criar_loja(conta), criar_produto(conta), da_fabrica=True)
        caixa = Caixa.objects.create(pedido=pedido, numero=1, codigo="codigo-1")
        self.assertEqual(caixa.situacao, Caixa.Situacao.A_CAMINHO)
        self.assertEqual(list(pedido.caixas.all()), [caixa])
