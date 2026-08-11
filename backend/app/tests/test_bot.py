from unittest import skipUnless

from django.contrib.auth.models import Group, User
from django.test import override_settings
from rest_framework.test import APITestCase

from app.models import (
    Categoria,
    Estoque,
    Loja,
    MovimentacaoEstoque,
    Pedido,
    PreferenciaNotificacao,
    Produto,
)

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
        Group.objects.get_or_create(name="Gerente")
        self.gerente = User.objects.create_user(
            username="gerente@email.com", email="gerente@email.com", password="123456",
        )
        self.gerente.groups.add(Group.objects.get(name="Gerente"))

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
            gerente=self.gerente,
            telefone_whatsapp=TELEFONE_LOJA,
        )
        self.cat_salgados = Categoria.objects.get_or_create(
            nome="Salgados grande", gerente=self.gerente
        )[0]
        self.cat_mercado = Categoria.objects.get_or_create(
            nome="Mercado", gerente=self.gerente
        )[0]
        self.coxinha = Produto.objects.create(
            nome_produto="Coxinha",
            unidade_medida=Produto.UnidadeMedida.CAIXA,
            quantidade_por_embalagem=30,
            categoria=self.cat_salgados,
            gerente=self.gerente,
        )
        self.coca = Produto.objects.create(
            nome_produto="Coca 2L",
            unidade_medida=Produto.UnidadeMedida.UNIDADE,
            categoria=self.cat_mercado,
            gerente=self.gerente,
        )

    def _dar_whatsapp_ao_gerente(self, telefone=TELEFONE_GERENTE):
        return PreferenciaNotificacao.objects.create(
            usuario=self.gerente, telefone_whatsapp=telefone, whatsapp_ativo=True
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
        response = self.client.get(
            "/api/v1/bot/catalogo/", {"telefone": TELEFONE_LOJA}, **HEADERS
        )
        self.assertEqual(response.status_code, 200)

        categorias = {c["nome"]: c for c in response.data["categorias"]}
        self.assertIn("Salgados grande", categorias)
        produto = categorias["Salgados grande"]["produtos"][0]
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

    def test_item_malformado_da_400_e_nao_500(self):
        """O corpo vem do que a loja digitou no WhatsApp: nao da pra confiar."""
        for itens in ([["nao sou objeto"]], [[{"codigo": "abc", "quantidade": 1}]]):
            with self.subTest(itens=itens):
                response = self.client.post(
                    "/api/v1/bot/pedido/",
                    {"telefone": TELEFONE_LOJA, "itens": itens[0]},
                    format="json",
                    **HEADERS,
                )
                self.assertEqual(response.status_code, 400, response.data)

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

    # --- remocao manual de estoque ---

    def test_remove_estoque_da_baixa_e_registra_movimentacao(self):
        estoque = Estoque.objects.create(
            produto=self.coxinha, loja=self.loja,
            quantidade_atual=10, quantidade_minima=2,
        )
        response = self.client.post(
            "/api/v1/bot/estoque/remover/",
            {"telefone": TELEFONE_LOJA, "itens": [{"codigo": self.coxinha.id, "quantidade": 3}]},
            format="json",
            **HEADERS,
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["itens"][0]["quantidade_atual"], 7)

        estoque.refresh_from_db()
        self.assertEqual(estoque.quantidade_atual, 7)

        mov = MovimentacaoEstoque.objects.get(tipo=MovimentacaoEstoque.Tipo.SAIDA)
        self.assertEqual(mov.produto, self.coxinha)
        self.assertEqual(mov.loja_origem, self.loja)
        self.assertEqual(mov.quantidade, 3)

    def test_remove_estoque_agrega_itens_com_mesmo_codigo(self):
        Estoque.objects.create(
            produto=self.coxinha, loja=self.loja,
            quantidade_atual=10, quantidade_minima=2,
        )
        response = self.client.post(
            "/api/v1/bot/estoque/remover/",
            {
                "telefone": TELEFONE_LOJA,
                "itens": [
                    {"codigo": self.coxinha.id, "quantidade": 3},
                    {"codigo": self.coxinha.id, "quantidade": 2},
                ],
            },
            format="json",
            **HEADERS,
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["itens"]), 1)
        self.assertEqual(response.data["itens"][0]["quantidade_removida"], 5)

    def test_remove_estoque_insuficiente_409(self):
        Estoque.objects.create(
            produto=self.coxinha, loja=self.loja,
            quantidade_atual=2, quantidade_minima=2,
        )
        response = self.client.post(
            "/api/v1/bot/estoque/remover/",
            {"telefone": TELEFONE_LOJA, "itens": [{"codigo": self.coxinha.id, "quantidade": 5}]},
            format="json",
            **HEADERS,
        )
        self.assertEqual(response.status_code, 409, response.data)

        estoque = Estoque.objects.get(produto=self.coxinha, loja=self.loja)
        self.assertEqual(estoque.quantidade_atual, 2)

    def test_remove_estoque_produto_sem_estoque_cadastrado_409(self):
        response = self.client.post(
            "/api/v1/bot/estoque/remover/",
            {"telefone": TELEFONE_LOJA, "itens": [{"codigo": self.coxinha.id, "quantidade": 1}]},
            format="json",
            **HEADERS,
        )
        self.assertEqual(response.status_code, 409, response.data)

    def test_remove_estoque_produto_nao_encontrado_400(self):
        response = self.client.post(
            "/api/v1/bot/estoque/remover/",
            {"telefone": TELEFONE_LOJA, "itens": [{"codigo": 99999, "quantidade": 1}]},
            format="json",
            **HEADERS,
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_remove_estoque_item_malformado_da_400_e_nao_500(self):
        for itens in ([["nao sou objeto"]], [[{"codigo": "abc", "quantidade": 1}]]):
            with self.subTest(itens=itens):
                response = self.client.post(
                    "/api/v1/bot/estoque/remover/",
                    {"telefone": TELEFONE_LOJA, "itens": itens[0]},
                    format="json",
                    **HEADERS,
                )
                self.assertEqual(response.status_code, 400, response.data)

    def test_remove_estoque_quantidade_invalida_400(self):
        Estoque.objects.create(
            produto=self.coxinha, loja=self.loja,
            quantidade_atual=10, quantidade_minima=2,
        )
        for quantidade in (0, -1, "abc"):
            with self.subTest(quantidade=quantidade):
                response = self.client.post(
                    "/api/v1/bot/estoque/remover/",
                    {"telefone": TELEFONE_LOJA, "itens": [{"codigo": self.coxinha.id, "quantidade": quantidade}]},
                    format="json",
                    **HEADERS,
                )
                self.assertEqual(response.status_code, 400, response.data)

    def test_remove_estoque_so_afeta_a_loja_do_telefone(self):
        """So o numero de WhatsApp DA LOJA pode dar baixa no estoque dela —
        nao ha campo de loja no corpo, so o telefone resolve quem esta mexendo."""
        outro_user = User.objects.create_user(username="maria@email.com", password="123456")
        outra_loja = Loja.objects.create(
            nome_loja="Loja Sul", cidade="Patos", endereco="Rua B, 2",
            responsavel=outro_user,
            telefone_whatsapp="5583988887777",
        )
        Estoque.objects.create(
            produto=self.coxinha, loja=self.loja,
            quantidade_atual=10, quantidade_minima=2,
        )
        estoque_outra_loja = Estoque.objects.create(
            produto=self.coxinha, loja=outra_loja,
            quantidade_atual=10, quantidade_minima=2,
        )

        response = self.client.post(
            "/api/v1/bot/estoque/remover/",
            {"telefone": TELEFONE_LOJA, "itens": [{"codigo": self.coxinha.id, "quantidade": 3}]},
            format="json",
            **HEADERS,
        )
        self.assertEqual(response.status_code, 200, response.data)

        estoque_outra_loja.refresh_from_db()
        self.assertEqual(estoque_outra_loja.quantidade_atual, 10)

    def test_remove_estoque_telefone_desconhecido_404(self):
        response = self.client.post(
            "/api/v1/bot/estoque/remover/",
            {"telefone": "550000000000", "itens": [{"codigo": self.coxinha.id, "quantidade": 1}]},
            format="json",
            **HEADERS,
        )
        self.assertEqual(response.status_code, 404)

    def test_remove_estoque_sem_itens_400(self):
        response = self.client.post(
            "/api/v1/bot/estoque/remover/",
            {"telefone": TELEFONE_LOJA, "itens": []},
            format="json",
            **HEADERS,
        )
        self.assertEqual(response.status_code, 400)

    # --- relatorio PDF: exclusivo do gerente ---

    def test_relatorio_loja_nao_autorizada_403(self):
        # Sem gerente configurado, ninguém (nem a loja) acessa o relatório.
        response = self.client.get(
            "/api/v1/bot/relatorio/", {"telefone": TELEFONE_LOJA}, **HEADERS
        )
        self.assertEqual(response.status_code, 403)

    def test_relatorio_loja_bloqueada_mesmo_com_gerente_403(self):
        # Loja continua sem acesso mesmo havendo gerente.
        self._dar_whatsapp_ao_gerente()
        response = self.client.get(
            "/api/v1/bot/relatorio/", {"telefone": TELEFONE_LOJA}, **HEADERS
        )
        self.assertEqual(response.status_code, 403)

    def test_relatorio_data_invalida_400(self):
        self._dar_whatsapp_ao_gerente()
        response = self.client.get(
            "/api/v1/bot/relatorio/",
            {"telefone": TELEFONE_GERENTE, "data": "2026-13-40"},
            **HEADERS,
        )
        self.assertEqual(response.status_code, 400)

    # --- gerente (recebe pedidos + relatorio de todas as lojas) ---

    def test_pedido_notifica_gerente(self):
        self._dar_whatsapp_ao_gerente()
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

    def test_pedido_sem_gerente_nao_notifica(self):
        # Gerente existe (self.gerente), mas nunca configurou o proprio
        # WhatsApp em Preferencias — sem PreferenciaNotificacao, nao ha pra
        # onde mandar.
        response = self.client.post(
            "/api/v1/bot/pedido/",
            {"telefone": TELEFONE_LOJA, "itens": [{"codigo": self.coxinha.id, "quantidade": 1}]},
            format="json",
            **HEADERS,
        )
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("notificar_gerente", response.data)

    @skipUnless(HAS_WEASYPRINT, "weasyprint não instalado neste ambiente")
    def test_gerente_recebe_relatorio_de_todas_as_lojas(self):
        self._dar_whatsapp_ao_gerente()
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
