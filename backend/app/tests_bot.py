from unittest import skipUnless

from django.contrib.auth.models import User
from django.test import override_settings
from rest_framework.test import APITestCase

from app.models import Estoque, Loja, Pedido, Produto

try:
    import weasyprint  # noqa: F401
    HAS_WEASYPRINT = True
except Exception:
    HAS_WEASYPRINT = False

TOKEN = "token-de-teste"
HEADERS = {"HTTP_X_BOT_TOKEN": TOKEN}
TELEFONE_LOJA = "5583999998888"
TELEFONE_GERENTE = "5583911112222"


@override_settings(BOT_SERVICE_TOKEN=TOKEN)
class BotApiTests(APITestCase):
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
        self.coxinha = Produto.objects.create(
            nome_produto="Coxinha",
            unidade_medida=Produto.UnidadeMedida.CAIXA,
            quantidade_por_embalagem=30,
            categoria=Produto.Categoria.SALGADOS_GDE,
        )
        self.coca = Produto.objects.create(
            nome_produto="Coca 2L",
            unidade_medida=Produto.UnidadeMedida.UNIDADE,
            categoria=Produto.Categoria.MERCADO,
        )

    # --- autenticacao de servico ---

    def test_sem_token_nega(self):
        response = self.client.get("/api/v1/bot/catalogo/")
        self.assertEqual(response.status_code, 403)

    def test_token_errado_nega(self):
        response = self.client.get(
            "/api/v1/bot/catalogo/", HTTP_X_BOT_TOKEN="errado"
        )
        self.assertEqual(response.status_code, 403)

    @override_settings(BOT_SERVICE_TOKEN="")
    def test_token_vazio_no_ambiente_nega_tudo(self):
        response = self.client.get("/api/v1/bot/catalogo/", **HEADERS)
        self.assertEqual(response.status_code, 403)

    # --- contato (telefone da loja) ---

    def test_telefone_da_loja_resolve(self):
        response = self.client.get(
            "/api/v1/bot/contato/",
            {"telefone": "+55 (83) 99999-8888"},  # normalizacao de formato
            **HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["loja"]["nome"], "Loja Centro")
        self.assertEqual(response.data["responsavel"], "Joao")

    def test_telefone_desconhecido_404(self):
        response = self.client.get(
            "/api/v1/bot/contato/", {"telefone": "550000000000"}, **HEADERS
        )
        self.assertEqual(response.status_code, 404)

    def test_loja_inativa_404(self):
        self.loja.ativo = False
        self.loja.save()
        response = self.client.get(
            "/api/v1/bot/contato/", {"telefone": TELEFONE_LOJA}, **HEADERS
        )
        self.assertEqual(response.status_code, 404)

    # --- catalogo ---

    def test_catalogo_agrupa_por_categoria(self):
        response = self.client.get("/api/v1/bot/catalogo/", **HEADERS)
        self.assertEqual(response.status_code, 200)

        categorias = {c["categoria"]: c for c in response.data["categorias"]}
        self.assertIn("SALGADOS_GDE", categorias)
        produto = categorias["SALGADOS_GDE"]["produtos"][0]
        self.assertEqual(produto["codigo"], self.coxinha.id)
        self.assertEqual(produto["unidade"], "CAIXA")

    # --- pedido ---

    def test_cria_pedido_pendente_em_nome_do_responsavel(self):
        response = self.client.post(
            "/api/v1/bot/pedido/",
            {
                "telefone": TELEFONE_LOJA,
                "itens": [
                    {"codigo": self.coxinha.id, "quantidade": 3},
                    {"codigo": self.coca.id, "quantidade": 6},
                ],
            },
            format="json",
            **HEADERS,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "PENDENTE")

        pedido = Pedido.objects.get(id=response.data["numero"])
        self.assertEqual(pedido.loja, self.loja)
        self.assertEqual(pedido.responsavel, self.responsavel)
        self.assertEqual(pedido.itens.count(), 2)

    def test_loja_sem_responsavel_409(self):
        self.loja.responsavel = None
        self.loja.save()
        response = self.client.post(
            "/api/v1/bot/pedido/",
            {
                "telefone": TELEFONE_LOJA,
                "itens": [{"codigo": self.coxinha.id, "quantidade": 1}],
            },
            format="json",
            **HEADERS,
        )
        self.assertEqual(response.status_code, 409)

    def test_pedido_sem_itens_400(self):
        response = self.client.post(
            "/api/v1/bot/pedido/",
            {"telefone": TELEFONE_LOJA, "itens": []},
            format="json",
            **HEADERS,
        )
        self.assertEqual(response.status_code, 400)

    def test_pedido_codigo_invalido_400(self):
        response = self.client.post(
            "/api/v1/bot/pedido/",
            {"telefone": TELEFONE_LOJA, "itens": [{"codigo": 99999, "quantidade": 1}]},
            format="json",
            **HEADERS,
        )
        self.assertEqual(response.status_code, 400)

    # --- confirmacao de recebimento ---

    def test_confirmar_marca_entregue_e_soma_estoque(self):
        criado = self.client.post(
            "/api/v1/bot/pedido/",
            {
                "telefone": TELEFONE_LOJA,
                "itens": [{"codigo": self.coxinha.id, "quantidade": 3}],
            },
            format="json",
            **HEADERS,
        )
        numero = criado.data["numero"]

        response = self.client.post(
            f"/api/v1/bot/pedido/{numero}/confirmar/",
            {"telefone": TELEFONE_LOJA},
            format="json",
            **HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "ENTREGUE")

        estoque = Estoque.objects.get(loja=self.loja, produto=self.coxinha)
        self.assertEqual(estoque.quantidade_atual, 3)

        # Confirmar de novo nao soma duas vezes
        self.client.post(
            f"/api/v1/bot/pedido/{numero}/confirmar/",
            {"telefone": TELEFONE_LOJA},
            format="json",
            **HEADERS,
        )
        estoque.refresh_from_db()
        self.assertEqual(estoque.quantidade_atual, 3)

    def test_confirmar_pedido_cancelado_e_recusado(self):
        """A guarda so olhava ENTREGUE: um pedido CANCELADO virava entregue e
        entrava no estoque como uma ENTRADA que nunca aconteceu."""
        pedido = Pedido.objects.create(
            responsavel=self.responsavel, loja=self.loja,
            status=Pedido.Status.CANCELADO,
        )

        response = self.client.post(
            f"/api/v1/bot/pedido/{pedido.id}/confirmar/",
            {"telefone": TELEFONE_LOJA},
            format="json",
            **HEADERS,
        )

        self.assertEqual(response.status_code, 409, response.data)
        pedido.refresh_from_db()
        self.assertEqual(pedido.status, Pedido.Status.CANCELADO)

    def test_confirmar_pedido_de_outra_loja_404(self):
        outro_user = User.objects.create_user(username="maria@email.com", password="123456")
        outra_loja = Loja.objects.create(
            nome_loja="Loja Sul", cidade="Patos", endereco="Rua B, 2",
            responsavel=outro_user,
            telefone_whatsapp="5583988887777",
        )
        pedido_alheio = Pedido.objects.create(responsavel=outro_user, loja=outra_loja)

        response = self.client.post(
            f"/api/v1/bot/pedido/{pedido_alheio.id}/confirmar/",
            {"telefone": TELEFONE_LOJA},
            format="json",
            **HEADERS,
        )
        self.assertEqual(response.status_code, 404)

    # --- relatorio PDF: exclusivo do gerente ---

    def test_relatorio_loja_nao_autorizada_403(self):
        # Sem gerente configurado, ninguém (nem a loja) acessa o relatório.
        response = self.client.get(
            "/api/v1/bot/relatorio/", {"telefone": TELEFONE_LOJA}, **HEADERS
        )
        self.assertEqual(response.status_code, 403)

    @override_settings(GERENTE_WHATSAPP=TELEFONE_GERENTE)
    def test_relatorio_loja_bloqueada_mesmo_com_gerente_403(self):
        # Loja continua sem acesso mesmo havendo gerente.
        response = self.client.get(
            "/api/v1/bot/relatorio/", {"telefone": TELEFONE_LOJA}, **HEADERS
        )
        self.assertEqual(response.status_code, 403)

    @override_settings(GERENTE_WHATSAPP=TELEFONE_GERENTE)
    def test_relatorio_data_invalida_400(self):
        response = self.client.get(
            "/api/v1/bot/relatorio/",
            {"telefone": TELEFONE_GERENTE, "data": "2026-13-40"},
            **HEADERS,
        )
        self.assertEqual(response.status_code, 400)

    # --- gerente (recebe pedidos + relatorio de todas as lojas) ---

    @override_settings(GERENTE_WHATSAPP=TELEFONE_GERENTE)
    def test_pedido_notifica_gerente(self):
        response = self.client.post(
            "/api/v1/bot/pedido/",
            {"telefone": TELEFONE_LOJA, "itens": [{"codigo": self.coxinha.id, "quantidade": 3}]},
            format="json",
            **HEADERS,
        )
        self.assertEqual(response.status_code, 201)
        notif = response.data["notificar_gerente"]
        self.assertEqual(notif["telefone"], TELEFONE_GERENTE)
        self.assertIn("Coxinha", notif["mensagem"])

    @override_settings(GERENTE_WHATSAPP="")
    def test_pedido_sem_gerente_nao_notifica(self):
        response = self.client.post(
            "/api/v1/bot/pedido/",
            {"telefone": TELEFONE_LOJA, "itens": [{"codigo": self.coxinha.id, "quantidade": 1}]},
            format="json",
            **HEADERS,
        )
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("notificar_gerente", response.data)

    @override_settings(GERENTE_WHATSAPP=TELEFONE_GERENTE)
    @skipUnless(HAS_WEASYPRINT, "weasyprint não instalado neste ambiente")
    def test_gerente_recebe_relatorio_de_todas_as_lojas(self):
        Pedido.objects.create(responsavel=self.responsavel, loja=self.loja)
        response = self.client.get(
            "/api/v1/bot/relatorio/",
            {"telefone": "+55 (83) 91111-2222"},  # gerente em formato humano
            **HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

    # --- serializer da loja aceita os campos novos ---

    def test_loja_serializer_normaliza_telefone(self):
        from app.api.v1.serializers import LojaSerializer

        serializer = LojaSerializer(
            instance=self.loja,
            data={"telefone_whatsapp": "+55 (83) 98888-0000"},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(
            serializer.validated_data["telefone_whatsapp"], "5583988880000"
        )
