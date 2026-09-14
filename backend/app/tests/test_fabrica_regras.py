from django.test import TestCase
from rest_framework.test import APIClient

from app.permissions import fabrica_do_usuario, is_fabrica
from app.services.fabrica import fabrica_da_conta, segue_fluxo_fabrica
from app.tests.fabricas import (
    criar_conta,
    criar_fabrica,
    criar_gerente,
    criar_loja,
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
