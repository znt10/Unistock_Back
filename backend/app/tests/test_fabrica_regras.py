from django.test import TestCase
from rest_framework.test import APIClient

from app.models import ItemPedido, Loja, Pedido, Produto
from app.permissions import fabrica_do_usuario, is_fabrica
from app.services.fabrica import fabrica_da_conta, segue_fluxo_fabrica
from app.tests.fabricas import (
    criar_conta,
    criar_fabrica,
    criar_gerente,
    criar_loja,
    criar_pedido,
    criar_produto,
)


class QuemEAFabricaTests(TestCase):
    def setUp(self):
        self.conta = criar_conta("Empresa A")
        self.fabrica = criar_fabrica(self.conta)
        self.lapa = criar_loja(self.conta, "Lapa")
        self.coxinha = criar_produto(self.conta)
        self.detergente = criar_produto(
            self.conta, "Detergente", "Mercado", vem_da_fabrica=False
        )

    def test_fabrica_da_conta(self):
        self.assertEqual(fabrica_da_conta(self.conta.id), self.fabrica)

    def test_fabrica_inativa_nao_conta(self):
        self.fabrica.ativo = False
        self.fabrica.save()
        self.assertIsNone(fabrica_da_conta(self.conta.id))

    def test_outra_empresa_nao_ve_esta_fabrica(self):
        self.assertIsNone(fabrica_da_conta(criar_conta("Empresa B").id))

    def test_produto_da_fabrica_so_segue_o_fluxo_com_fabrica_cadastrada(self):
        self.assertTrue(segue_fluxo_fabrica(self.coxinha))
        self.fabrica.ativo = False
        self.fabrica.save()
        self.assertFalse(segue_fluxo_fabrica(self.coxinha))

    def test_produto_que_nao_vem_da_fabrica_nunca_segue(self):
        self.assertFalse(segue_fluxo_fabrica(self.detergente))

    def test_is_fabrica(self):
        self.assertTrue(is_fabrica(self.fabrica.responsavel))
        self.assertEqual(fabrica_do_usuario(self.fabrica.responsavel), self.fabrica)
        self.assertFalse(is_fabrica(self.lapa.responsavel))
        self.assertFalse(is_fabrica(criar_gerente("g@x.com", self.conta)))

    def test_fabrica_apagada_fica_invisivel_para_as_duas_perguntas(self):
        # ativo continua True (soft_delete nao mexe nele) — quem barra e o
        # is_deleted, que as duas funcoes precisam checar igual.
        self.fabrica.is_deleted = True
        self.fabrica.save()
        self.assertIsNone(fabrica_da_conta(self.conta.id))
        self.assertFalse(is_fabrica(self.fabrica.responsavel))

    def test_me_expoe_o_tipo_da_loja(self):
        client = APIClient()
        client.force_authenticate(self.fabrica.responsavel)
        resposta = client.get("/api/v1/user/me/")
        self.assertEqual(resposta.data["loja"]["tipo"], "Fabrica")


class UmaFabricaPorEmpresaTests(TestCase):
    def setUp(self):
        self.conta = criar_conta("Empresa A")
        self.gerente = criar_gerente("ger@x.com", self.conta)
        self.fabrica = criar_fabrica(self.conta)
        self.client = APIClient()
        self.client.force_authenticate(self.gerente)

    def dados(self, **extras):
        base = {"nome_loja": "Fabrica 2", "tipo": "Fabrica", "cidade": "Patos", "endereco": "Rua 2"}
        base.update(extras)
        return base

    def test_segunda_fabrica_ativa_e_recusada(self):
        resposta = self.client.post("/api/v1/lojas/", self.dados(), format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("já tem uma fábrica: Fabrica Central", str(resposta.data))

    def test_segunda_fabrica_inativa_passa(self):
        resposta = self.client.post("/api/v1/lojas/", self.dados(ativo=False), format="json")
        self.assertEqual(resposta.status_code, 201, resposta.data)

    def test_outra_empresa_pode_ter_a_propria_fabrica(self):
        conta_b = criar_conta("Empresa B")
        client = APIClient()
        client.force_authenticate(criar_gerente("ger-b@x.com", conta_b))
        resposta = client.post("/api/v1/lojas/", self.dados(), format="json")
        self.assertEqual(resposta.status_code, 201, resposta.data)

    def test_transformar_loja_em_fabrica_e_recusado(self):
        lapa = criar_loja(self.conta, "Lapa")
        resposta = self.client.patch(
            f"/api/v1/lojas/{lapa.public_id}/", {"tipo": "Fabrica"}, format="json"
        )
        self.assertEqual(resposta.status_code, 400)

    def test_editar_a_propria_fabrica_passa(self):
        resposta = self.client.patch(
            f"/api/v1/lojas/{self.fabrica.public_id}/", {"cidade": "Recife"}, format="json"
        )
        self.assertEqual(resposta.status_code, 200, resposta.data)


class ProdutoVemDaFabricaNaApiTests(TestCase):
    def setUp(self):
        self.conta = criar_conta("Empresa A")
        self.client = APIClient()
        self.client.force_authenticate(criar_gerente("ger@x.com", self.conta))
        self.coxinha = criar_produto(self.conta, vem_da_fabrica=False)

    def test_criar_com_vem_da_fabrica_grava(self):
        resposta = self.client.post(
            "/api/v1/produtos/",
            {
                "nome_produto": "Pastel",
                "unidade_medida": Produto.UnidadeMedida.UNIDADE,
                "categoria": str(self.coxinha.categoria.public_id),
                "vem_da_fabrica": True,
            },
            format="json",
        )
        self.assertEqual(resposta.status_code, 201, resposta.data)
        self.assertTrue(resposta.data["vem_da_fabrica"])
        self.assertTrue(Produto.objects.get(nome_produto="Pastel").vem_da_fabrica)

    def test_leitura_devolve_o_campo(self):
        resposta = self.client.get(f"/api/v1/produtos/{self.coxinha.public_id}/")
        self.assertIs(resposta.data["vem_da_fabrica"], False)
        lista = self.client.get("/api/v1/produtos/").data
        itens = lista.get("results", lista)
        self.assertIn("vem_da_fabrica", itens[0])

    def test_patch_liga_e_desliga(self):
        url = f"/api/v1/produtos/{self.coxinha.public_id}/"
        resposta = self.client.patch(url, {"vem_da_fabrica": True}, format="json")
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.coxinha.refresh_from_db()
        self.assertTrue(self.coxinha.vem_da_fabrica)

        self.client.patch(url, {"vem_da_fabrica": False}, format="json")
        self.coxinha.refresh_from_db()
        self.assertFalse(self.coxinha.vem_da_fabrica)


class SoGerenciaMudaTipoEAtivoTests(TestCase):
    def setUp(self):
        self.conta = criar_conta("Empresa A")
        self.lapa = criar_loja(self.conta, "Lapa")
        self.client = APIClient()

    def url(self, loja):
        return f"/api/v1/lojas/{loja.public_id}/"

    def test_loja_nao_vira_fabrica_pelo_proprio_login(self):
        self.client.force_authenticate(self.lapa.responsavel)
        resposta = self.client.patch(self.url(self.lapa), {"tipo": "Fabrica"}, format="json")
        self.assertEqual(resposta.status_code, 403)
        self.lapa.refresh_from_db()
        self.assertEqual(self.lapa.tipo, Loja.Tipo.LOJA)
        self.assertIsNone(fabrica_da_conta(self.conta.id))

    def test_loja_nao_se_desativa_pelo_proprio_login(self):
        self.client.force_authenticate(self.lapa.responsavel)
        resposta = self.client.patch(self.url(self.lapa), {"ativo": False}, format="json")
        self.assertEqual(resposta.status_code, 403)
        self.lapa.refresh_from_db()
        self.assertTrue(self.lapa.ativo)

    def test_fabrica_nao_vira_loja_nem_se_desativa(self):
        fabrica = criar_fabrica(self.conta)
        self.client.force_authenticate(fabrica.responsavel)

        resposta = self.client.patch(self.url(fabrica), {"tipo": "Loja"}, format="json")
        self.assertEqual(resposta.status_code, 403)
        resposta = self.client.patch(self.url(fabrica), {"ativo": False}, format="json")
        self.assertEqual(resposta.status_code, 403)

        fabrica.refresh_from_db()
        self.assertEqual(fabrica.tipo, Loja.Tipo.FABRICA)
        self.assertTrue(fabrica.ativo)

    def test_reenviar_o_valor_atual_passa(self):
        self.client.force_authenticate(self.lapa.responsavel)
        resposta = self.client.patch(
            self.url(self.lapa),
            {"tipo": "Loja", "ativo": True, "cidade": "Recife"},
            format="json",
        )
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.lapa.refresh_from_db()
        self.assertEqual(self.lapa.cidade, "Recife")

    def test_gerente_muda_tipo_e_ativo(self):
        self.client.force_authenticate(criar_gerente("ger@x.com", self.conta))
        resposta = self.client.patch(self.url(self.lapa), {"tipo": "Fabrica"}, format="json")
        self.assertEqual(resposta.status_code, 200, resposta.data)
        resposta = self.client.patch(self.url(self.lapa), {"ativo": False}, format="json")
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.lapa.refresh_from_db()
        self.assertEqual(self.lapa.tipo, Loja.Tipo.FABRICA)
        self.assertFalse(self.lapa.ativo)


class ItemDePedidoDaFabricaImpressoTests(TestCase):
    def setUp(self):
        self.conta = criar_conta("Empresa A")
        criar_fabrica(self.conta)
        self.lapa = criar_loja(self.conta, "Lapa")
        self.coxinha = criar_produto(self.conta)
        self.client = APIClient()
        self.client.force_authenticate(self.lapa.responsavel)

    def item(self, **extras_pedido):
        pedido = criar_pedido(self.lapa, self.coxinha, quantidade=3, **extras_pedido)
        return pedido.itens.get()

    def url(self, item):
        return f"/api/v1/itens-pedido/{item.public_id}/"

    def test_pedido_da_fabrica_em_entrega_recusa_patch_e_delete(self):
        item = self.item(da_fabrica=True, status=Pedido.Status.EM_ENTREGA)

        resposta = self.client.patch(self.url(item), {"quantidade": 5}, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("só pode ser alterado enquanto está pendente", str(resposta.data))

        resposta = self.client.delete(self.url(item))
        self.assertEqual(resposta.status_code, 400)

        item.refresh_from_db()
        self.assertEqual(item.quantidade, 3)
        self.assertTrue(ItemPedido.objects.filter(pk=item.pk).exists())

    def test_pedido_da_fabrica_pendente_ainda_edita(self):
        item = self.item(da_fabrica=True)
        resposta = self.client.patch(self.url(item), {"quantidade": 5}, format="json")
        self.assertEqual(resposta.status_code, 200, resposta.data)
        item.refresh_from_db()
        self.assertEqual(item.quantidade, 5)
        self.assertEqual(self.client.delete(self.url(item)).status_code, 204)

    def test_pedido_comum_em_entrega_segue_como_antes(self):
        item = self.item(status=Pedido.Status.EM_ENTREGA)
        resposta = self.client.patch(self.url(item), {"quantidade": 5}, format="json")
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertEqual(self.client.delete(self.url(item)).status_code, 204)


class LoginNaoMostraFabricaInativaTests(TestCase):
    def setUp(self):
        self.conta = criar_conta("Empresa A")
        self.fabrica = criar_fabrica(self.conta)
        self.fabrica.responsavel.set_password("senha-forte-123")
        self.fabrica.responsavel.save()

    def me(self):
        client = APIClient()
        client.force_authenticate(self.fabrica.responsavel)
        return client.get("/api/v1/user/me/").data["loja"]

    def login(self):
        return APIClient().post(
            "/login/",
            {"email": self.fabrica.responsavel.username, "password": "senha-forte-123"},
            format="json",
        ).data["user"]["loja"]

    def test_fabrica_ativa_aparece_como_fabrica(self):
        self.assertEqual(self.me()["tipo"], "Fabrica")
        self.assertEqual(self.login()["tipo"], "Fabrica")

    def test_fabrica_inativa_nao_aparece_como_fabrica(self):
        self.fabrica.ativo = False
        self.fabrica.save()
        me = self.me()
        self.assertEqual(me["tipo"], "Loja")
        # A loja continua vinculada (id/nome), so o tipo deixa de dizer fabrica.
        self.assertEqual(me["nome"], self.fabrica.nome_loja)
        self.assertEqual(self.login()["tipo"], "Loja")

    def test_fabrica_apagada_nao_aparece_como_fabrica(self):
        self.fabrica.is_deleted = True
        self.fabrica.save()
        self.assertEqual(self.me()["tipo"], "Loja")
