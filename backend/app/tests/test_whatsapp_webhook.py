from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import override_settings
from rest_framework.test import APITestCase

from app.models import Categoria, Estoque, Loja, Pedido, Produto

TOKEN = "token-de-teste"
WEBHOOK_TOKEN = "webhook-secreto"
URL = f"/api/v1/bot/webhook/{WEBHOOK_TOKEN}/"
TELEFONE_LOJA = "5583999998888"


def evento_mensagem(texto, telefone=TELEFONE_LOJA, from_me=False):
    return {
        "event": "messages.upsert",
        "data": {
            "key": {"remoteJid": f"{telefone}@s.whatsapp.net", "fromMe": from_me},
            "message": {"conversation": texto},
        },
    }


@override_settings(BOT_SERVICE_TOKEN=TOKEN, EVOLUTION_WEBHOOK_TOKEN=WEBHOOK_TOKEN)
@patch("app.api.v1.whatsapp_webhook.enviar_mensagem")
class WebhookEvolutionTests(APITestCase):
    def setUp(self):
        self.responsavel = User.objects.create_user(
            username="joao@email.com",
            email="joao@email.com",
            password="123456",
            first_name="Joao",
        )
        self.loja = Loja.objects.create(
            nome_loja="Loja Centro",
            cidade="Patos",
            endereco="Rua A, 1",
            responsavel=self.responsavel,
            telefone_whatsapp=TELEFONE_LOJA,
        )
        self.categoria = Categoria.objects.get_or_create(nome="Salgados grande")[0]
        self.coxinha = Produto.objects.create(
            nome_produto="Coxinha",
            unidade_medida=Produto.UnidadeMedida.CAIXA,
            quantidade_por_embalagem=30,
            categoria=self.categoria,
        )

    # --- controle de acesso ---

    def test_token_errado_403(self, enviar_mensagem):
        response = self.client.post(
            "/api/v1/bot/webhook/errado/", evento_mensagem("catalogo"), format="json"
        )
        self.assertEqual(response.status_code, 403)
        enviar_mensagem.assert_not_called()

    @override_settings(EVOLUTION_WEBHOOK_TOKEN="")
    def test_webhook_desligado_sem_config_404(self, enviar_mensagem):
        response = self.client.post(URL, evento_mensagem("catalogo"), format="json")
        self.assertEqual(response.status_code, 404)
        enviar_mensagem.assert_not_called()

    # --- filtros de evento ---

    def test_ignora_evento_diferente_de_messages_upsert(self, enviar_mensagem):
        payload = {"event": "connection.update", "data": {}}
        response = self.client.post(URL, payload, format="json")
        self.assertEqual(response.status_code, 200)
        enviar_mensagem.assert_not_called()

    def test_ignora_mensagem_propria_from_me(self, enviar_mensagem):
        response = self.client.post(
            URL, evento_mensagem("catalogo", from_me=True), format="json"
        )
        self.assertEqual(response.status_code, 200)
        enviar_mensagem.assert_not_called()

    def test_ignora_mensagem_sem_texto(self, enviar_mensagem):
        payload = {
            "event": "messages.upsert",
            "data": {
                "key": {"remoteJid": f"{TELEFONE_LOJA}@s.whatsapp.net", "fromMe": False},
                "message": {},
            },
        }
        response = self.client.post(URL, payload, format="json")
        self.assertEqual(response.status_code, 200)
        enviar_mensagem.assert_not_called()

    # --- comandos ---

    def test_comando_catalogo_responde_produtos(self, enviar_mensagem):
        response = self.client.post(URL, evento_mensagem("catalogo"), format="json")
        self.assertEqual(response.status_code, 200)
        enviar_mensagem.assert_called_once()
        telefone, texto = enviar_mensagem.call_args[0]
        self.assertEqual(telefone, TELEFONE_LOJA)
        self.assertIn("Coxinha", texto)

    def test_comando_desconhecido_manda_ajuda(self, enviar_mensagem):
        response = self.client.post(URL, evento_mensagem("blablabla"), format="json")
        self.assertEqual(response.status_code, 200)
        telefone, texto = enviar_mensagem.call_args[0]
        self.assertIn("Nao entendi", texto)

    def test_comando_pedido_cria_e_responde(self, enviar_mensagem):
        response = self.client.post(
            URL, evento_mensagem(f"pedido {self.coxinha.id}x2"), format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Pedido.objects.filter(loja=self.loja).exists())
        telefone, texto = enviar_mensagem.call_args[0]
        self.assertEqual(telefone, TELEFONE_LOJA)
        self.assertIn("Pedido #", texto)

    def test_comando_pedido_sem_itens_pede_pra_repetir(self, enviar_mensagem):
        response = self.client.post(URL, evento_mensagem("pedido"), format="json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Pedido.objects.filter(loja=self.loja).exists())
        telefone, texto = enviar_mensagem.call_args[0]
        self.assertIn("Nao entendi os itens", texto)

    def test_comando_confirmar_marca_entregue(self, enviar_mensagem):
        pedido = Pedido.objects.create(
            responsavel=self.responsavel, loja=self.loja, status=Pedido.Status.PENDENTE,
        )
        response = self.client.post(
            URL, evento_mensagem(f"confirmar {pedido.id}"), format="json"
        )
        self.assertEqual(response.status_code, 200)
        pedido.refresh_from_db()
        self.assertEqual(pedido.status, Pedido.Status.ENTREGUE)
        telefone, texto = enviar_mensagem.call_args[0]
        self.assertIn("confirmado", texto)

    def test_comando_remover_da_baixa(self, enviar_mensagem):
        estoque = Estoque.objects.create(
            produto=self.coxinha, loja=self.loja, quantidade_atual=10, quantidade_minima=2,
        )
        response = self.client.post(
            URL, evento_mensagem(f"remover {self.coxinha.id}x3"), format="json"
        )
        self.assertEqual(response.status_code, 200)
        estoque.refresh_from_db()
        self.assertEqual(estoque.quantidade_atual, 7)
        telefone, texto = enviar_mensagem.call_args[0]
        self.assertIn("Baixa registrada", texto)

    def test_comando_de_telefone_desconhecido_avisa_erro(self, enviar_mensagem):
        response = self.client.post(
            URL,
            evento_mensagem(f"pedido {self.coxinha.id}x1", telefone="550000000000"),
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        telefone, texto = enviar_mensagem.call_args[0]
        self.assertEqual(telefone, "550000000000")
        self.assertIn("Nao deu", texto)
