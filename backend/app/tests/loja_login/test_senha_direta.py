"""Gerente/Admin define a senha da loja direto na tela de editar, sem
depender do link por email.

Existe para agilizar quem cadastra muitas lojas de uma vez: digita a senha e
passa pra loja na hora, em vez de esperar o email chegar. O link por email
continua sendo o caminho padrao (campo em branco) e o unico jeito pra
`esqueci a senha`.
"""

from unittest.mock import patch

from rest_framework.test import APITestCase

from app.models import Loja
from app.tests.fabricas import criar_conta, criar_gerente, criar_responsavel


class SenhaDefinidaNaCriacaoTests(APITestCase):
    def setUp(self):
        self.conta = criar_conta("Empresa A")
        self.gerente = criar_gerente("ger@x.com", self.conta)
        self.client.force_authenticate(self.gerente)

    @patch("app.notifications.tasks.enviar_email_definir_senha.delay")
    def test_senha_no_cadastro_cria_acesso_ativo_sem_email(self, enviar_email):
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(
                "/api/v1/lojas/",
                {
                    "nome_loja": "Lapa", "cidade": "Patos", "endereco": "Rua 1",
                    "email": "lapa@unistock.com",
                    "senha_acesso": "SenhaForte#2026",
                },
                format="json",
            )

        self.assertEqual(resp.status_code, 201, resp.data)
        loja = Loja.objects.get(nome_loja="Lapa")
        acesso = loja.responsavel

        self.assertIsNotNone(acesso)
        self.assertTrue(acesso.is_active)
        self.assertTrue(acesso.check_password("SenhaForte#2026"))
        enviar_email.assert_not_called()

    def test_sem_senha_continua_o_fluxo_de_email(self):
        """O padrao nao muda: campo em branco e o comportamento de sempre."""
        from django.core import mail

        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(
                "/api/v1/lojas/",
                {
                    "nome_loja": "Lapa", "cidade": "Patos", "endereco": "Rua 1",
                    "email": "lapa@unistock.com",
                },
                format="json",
            )

        self.assertEqual(resp.status_code, 201, resp.data)
        acesso = Loja.objects.get(nome_loja="Lapa").responsavel
        self.assertFalse(acesso.is_active)
        self.assertFalse(acesso.has_usable_password())
        self.assertEqual(len(mail.outbox), 1)

    def test_senha_sem_email_e_recusada(self):
        resp = self.client.post(
            "/api/v1/lojas/",
            {
                "nome_loja": "Lapa", "cidade": "Patos", "endereco": "Rua 1",
                "senha_acesso": "SenhaForte#2026",
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn("senha_acesso", resp.data)

    def test_senha_fraca_e_recusada(self):
        resp = self.client.post(
            "/api/v1/lojas/",
            {
                "nome_loja": "Lapa", "cidade": "Patos", "endereco": "Rua 1",
                "email": "lapa@unistock.com",
                "senha_acesso": "123",
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn("senha_acesso", resp.data)
        self.assertFalse(Loja.objects.filter(nome_loja="Lapa").exists())

    def test_responsavel_nao_pode_definir_senha_de_outra_loja(self):
        """O campo e' de gerencia — a loja nao mexe no proprio acesso por
        aqui (ela tem o fluxo normal de troca de senha, logada)."""
        outra_loja = Loja.objects.create(
            nome_loja="Alvo", cidade="Patos", endereco="Rua 2",
            conta=self.conta, email="alvo@unistock.com",
        )
        dono = criar_responsavel("dono@x.com", self.conta)
        self.client.force_authenticate(dono)

        resp = self.client.patch(
            f"/api/v1/lojas/{outra_loja.public_id}/",
            {"senha_acesso": "SenhaForte#2026"},
            format="json",
        )

        self.assertEqual(resp.status_code, 403)


class SenhaDefinidaNaEdicaoTests(APITestCase):
    def setUp(self):
        self.conta = criar_conta("Empresa A")
        self.gerente = criar_gerente("ger@x.com", self.conta)
        self.client.force_authenticate(self.gerente)

        self.client.post(
            "/api/v1/lojas/",
            {
                "nome_loja": "Lapa", "cidade": "Patos", "endereco": "Rua 1",
                "email": "lapa@unistock.com",
            },
            format="json",
        )
        self.loja = Loja.objects.get(nome_loja="Lapa")
        self.acesso = self.loja.responsavel

    def test_definir_senha_de_acesso_ja_existente_ativa_a_conta(self):
        """Loja cadastrada pelo fluxo normal (inativa, sem senha), o gerente
        decide resetar direto em vez de esperar o email."""
        self.assertFalse(self.acesso.is_active)

        resp = self.client.patch(
            f"/api/v1/lojas/{self.loja.public_id}/",
            {"senha_acesso": "OutraSenha#2026"},
            format="json",
        )

        self.assertEqual(resp.status_code, 200, resp.data)
        self.acesso.refresh_from_db()
        self.assertTrue(self.acesso.is_active)
        self.assertTrue(self.acesso.check_password("OutraSenha#2026"))

    def test_campo_em_branco_nao_mexe_na_senha_existente(self):
        self.acesso.set_password("SenhaOriginal#2026")
        self.acesso.is_active = True
        self.acesso.save()

        resp = self.client.patch(
            f"/api/v1/lojas/{self.loja.public_id}/",
            {"cidade": "Campina"},
            format="json",
        )

        self.assertEqual(resp.status_code, 200, resp.data)
        self.acesso.refresh_from_db()
        self.assertTrue(self.acesso.check_password("SenhaOriginal#2026"))

    def test_loja_que_perdeu_o_acesso_ganha_um_novo_ja_com_a_senha(self):
        """Combina com a recuperacao de acesso apagado: se a loja nao tem
        responsavel, definir senha aqui recria o login pronto pra usar."""
        self.acesso.delete()
        self.loja.refresh_from_db()
        self.assertIsNone(self.loja.responsavel)

        resp = self.client.patch(
            f"/api/v1/lojas/{self.loja.public_id}/",
            {"senha_acesso": "SenhaNova#2026"},
            format="json",
        )

        self.assertEqual(resp.status_code, 200, resp.data)
        self.loja.refresh_from_db()
        novo_acesso = self.loja.responsavel
        self.assertIsNotNone(novo_acesso)
        self.assertEqual(novo_acesso.username, "lapa@unistock.com")
        self.assertTrue(novo_acesso.is_active)
        self.assertTrue(novo_acesso.check_password("SenhaNova#2026"))
