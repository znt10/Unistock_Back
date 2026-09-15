"""Loja que perde o acesso: o que acontece e como ela volta.

`Loja.responsavel` e SET_NULL. Apagar o usuario de acesso no /admin nao da
erro nenhum: a loja fica com email cadastrado e sem login, silenciosamente.
Dois problemas nascem dai, e os dois estao cobertos aqui.
"""

from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from app.models import Loja
from app.notifications.tokens import gerar_token_senha
from app.tests.fabricas import criar_conta, criar_gerente


class LojaSemAcessoTests(APITestCase):
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
        self.acesso_antigo = self.loja.responsavel

    def test_apagar_o_acesso_deixa_a_loja_com_email_e_sem_login(self):
        """O estado de partida do problema — SET_NULL nao avisa ninguem."""
        self.acesso_antigo.delete()
        self.loja.refresh_from_db()

        self.assertIsNone(self.loja.responsavel)
        self.assertEqual(self.loja.email, "lapa@unistock.com")

    def test_link_de_conta_apagada_nao_diz_que_ja_foi_usado(self):
        """A mensagem mandava a pessoa procurar o erro no lugar errado.

        "Link ja utilizado" faz quem recebeu concluir que alguem usou o link —
        quando na verdade a conta deixou de existir. Sao dois problemas com
        solucoes opostas: um pede "esqueci a senha", o outro pede recadastro.
        """
        token = gerar_token_senha(self.acesso_antigo)
        self.acesso_antigo.delete()

        self.client.force_authenticate(None)
        resp = self.client.post(
            f"/api/v1/user/definir-senha/{token}/",
            {"password": "SenhaForte#2026"},
            format="json",
        )

        self.assertEqual(resp.status_code, 400)
        self.assertNotIn("utilizado", resp.data["error"].lower())
        self.assertIn("nao existe", resp.data["error"].lower())

    def test_salvar_a_loja_devolve_o_acesso_perdido(self):
        """Sem isto a loja fica num beco: o acesso so era recriado quando o
        EMAIL mudava, entao editar e salvar sem trocar o email nao adiantava, e
        trocar o email so para recuperar o login e um contorno, nao um
        caminho."""
        self.acesso_antigo.delete()
        self.loja.refresh_from_db()

        self.client.force_authenticate(self.gerente)
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.patch(
                f"/api/v1/lojas/{self.loja.public_id}/",
                {"cidade": "Patos"},
                format="json",
            )

        self.assertEqual(resp.status_code, 200, resp.data)
        self.loja.refresh_from_db()
        self.assertIsNotNone(self.loja.responsavel)
        self.assertEqual(self.loja.responsavel.username, "lapa@unistock.com")
        self.assertTrue(
            self.loja.responsavel.groups.filter(name="Responsavel").exists()
        )

    def test_loja_com_acesso_intacto_nao_ganha_outro(self):
        """A recuperacao so vale para quem perdeu: nada de recriar login a cada
        edicao de cadastro."""
        antes = User.objects.count()

        self.client.patch(
            f"/api/v1/lojas/{self.loja.public_id}/",
            {"cidade": "Campina"},
            format="json",
        )

        self.loja.refresh_from_db()
        self.assertEqual(self.loja.responsavel_id, self.acesso_antigo.id)
        self.assertEqual(User.objects.count(), antes)
