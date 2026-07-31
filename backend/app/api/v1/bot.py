"""Endpoints de servico para o bot de WhatsApp.

Chamados pelo webhook da Evolution API (app.api.v1.whatsapp_webhook), que
autentica aqui com um token de servico (header X-Bot-Token, valor em
BOT_SERVICE_TOKEN no .env) e informa o telefone de quem mandou a mensagem.

O numero de WhatsApp e DA LOJA (Loja.telefone_whatsapp), nao do responsavel:
o Django resolve telefone -> loja e cria o pedido em nome do responsavel
atual da loja, aplicando as mesmas regras de negocio do site
(serializers/notificacoes existentes).
"""

import re
from datetime import date
from types import SimpleNamespace

from django.conf import settings
from django.db import transaction
from django.utils.crypto import constant_time_compare
from rest_framework import status
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from app.models import Categoria, Estoque, Loja, MovimentacaoEstoque, Pedido, Produto
from app.notifications import notificar_estoque_baixo
from app.relatorios.pedidos_pdf import gerar_relatorio_pedidos_pdf
from app.services.pedidos import TransicaoInvalida, mudar_status
from .serializers import PedidoCreateSerializer


def normalizar_telefone(valor):
    return re.sub(r"\D", "", str(valor or ""))


def eh_gerente(telefone):
    """True se o telefone for o do gerente configurado (GERENTE_WHATSAPP)."""
    numero = normalizar_telefone(settings.GERENTE_WHATSAPP)
    return bool(numero) and normalizar_telefone(telefone) == numero


def notificacao_gerente(loja, pedido):
    """Bloco pronto pro bot Node avisar o gerente, ou None se não há gerente."""
    numero = normalizar_telefone(settings.GERENTE_WHATSAPP)
    if not numero:
        return None
    linhas = [
        f"• {item.quantidade}x {item.produto.nome_produto}"
        for item in pedido.itens.all()
    ]
    mensagem = f"🧾 Novo pedido #{pedido.id} — {loja.nome_loja}\n" + "\n".join(linhas)
    return {"telefone": numero, "mensagem": mensagem}


class BotTokenPermission(BasePermission):
    message = "Token de servico invalido."

    def has_permission(self, request, view):
        token = settings.BOT_SERVICE_TOKEN
        recebido = request.headers.get("X-Bot-Token", "")
        # Token vazio no ambiente = bot desativado (nega tudo).
        return bool(token) and constant_time_compare(recebido, token)


class BotAPIView(APIView):
    authentication_classes = []
    permission_classes = [BotTokenPermission]
    # Canal de servico confiavel (token) — fora do throttle anonimo global.
    throttle_classes = []

    def resolver_loja(self, telefone):
        """Telefone do WhatsApp da loja -> Loja ativa, ou None."""
        telefone = normalizar_telefone(telefone)
        if not telefone:
            return None

        return (
            Loja.objects.select_related("responsavel")
            .filter(telefone_whatsapp=telefone, ativo=True, is_deleted=False)
            .first()
        )

    def erro_loja(self):
        return Response(
            {"error": "Numero nao cadastrado como WhatsApp de nenhuma loja ativa."},
            status=status.HTTP_404_NOT_FOUND,
        )

    def erro_sem_responsavel(self):
        return Response(
            {"error": "A loja nao tem responsavel cadastrado; pedidos indisponiveis."},
            status=status.HTTP_409_CONFLICT,
        )


class BotContatoView(BotAPIView):
    """GET /api/v1/bot/contato/?telefone=... — identifica a loja que esta falando."""

    def get(self, request):
        loja = self.resolver_loja(request.query_params.get("telefone"))

        if not loja:
            return self.erro_loja()

        responsavel = loja.responsavel
        return Response({
            "loja": {"id": str(loja.public_id), "nome": loja.nome_loja},
            "responsavel": (
                (responsavel.first_name or responsavel.username)
                if responsavel else None
            ),
        })


class BotCatalogoView(BotAPIView):
    """GET /api/v1/bot/catalogo/ — categorias e produtos para o menu do bot.

    Usa o id inteiro do produto como codigo digitavel no chat.
    """

    def get(self, request):
        produtos = (
            Produto.objects.filter(is_deleted=False)
            .select_related("categoria")
            .order_by("nome_produto")
        )
        por_categoria = {}
        for produto in produtos:
            por_categoria.setdefault(produto.categoria_id, []).append({
                "codigo": produto.id,
                "nome": produto.nome_produto,
                "unidade": produto.unidade_medida,
                "quantidade_por_embalagem": produto.quantidade_por_embalagem,
            })

        categorias_com_produtos = Categoria.objects.filter(id__in=por_categoria.keys())

        categorias = [
            {
                "codigo": indice + 1,
                "categoria": str(categoria.public_id),
                "nome": categoria.nome,
                "produtos": por_categoria[categoria.id],
            }
            for indice, categoria in enumerate(categorias_com_produtos)
        ]

        return Response({"categorias": categorias})


class BotPedidoView(BotAPIView):
    """POST /api/v1/bot/pedido/ — cria pedido PENDENTE para a loja do telefone.

    Body: {"telefone": "...", "itens": [{"codigo": <id produto>, "quantidade": n}]}
    """

    def post(self, request):
        loja = self.resolver_loja(request.data.get("telefone"))

        if not loja:
            return self.erro_loja()

        if not loja.responsavel:
            return self.erro_sem_responsavel()

        itens_brutos = request.data.get("itens") or []
        if not isinstance(itens_brutos, list) or not itens_brutos:
            return Response(
                {"error": "Informe ao menos um item."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        itens = []
        for item in itens_brutos:
            # O corpo vem do bot, que repassa o que a loja digitou no WhatsApp:
            # item pode nao ser objeto, e codigo pode nao ser numero. Sem esta
            # guarda dava AttributeError/ValueError e virava 500.
            if not isinstance(item, dict):
                return Response(
                    {"error": "Cada item precisa ter codigo e quantidade."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            codigo = item.get("codigo")
            quantidade = item.get("quantidade")

            try:
                codigo = int(codigo)
            except (TypeError, ValueError):
                return Response(
                    {"error": f"Codigo de produto invalido: {codigo!r}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            produto = Produto.objects.filter(id=codigo, is_deleted=False).first()
            if not produto:
                return Response(
                    {"error": f"Produto de codigo {codigo} nao encontrado."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            itens.append({
                "produto": str(produto.public_id),
                "quantidade": quantidade,
            })

        serializer = PedidoCreateSerializer(
            data={"loja": str(loja.public_id), "itens": itens},
            # PedidoCreateSerializer so usa request.user do contexto.
            context={"request": SimpleNamespace(user=loja.responsavel)},
        )
        serializer.is_valid(raise_exception=True)
        pedido = serializer.save()

        resposta = {
            "pedido": str(pedido.public_id),
            "numero": pedido.id,
            "status": pedido.status,
            "loja": loja.nome_loja,
        }
        notificar = notificacao_gerente(loja, pedido)
        if notificar:
            resposta["notificar_gerente"] = notificar

        return Response(resposta, status=status.HTTP_201_CREATED)


class BotPedidoConfirmarView(BotAPIView):
    """POST /api/v1/bot/pedido/<numero>/confirmar/ — a loja avisou que chegou.

    Body: {"telefone": "..."}. Marca ENTREGUE e soma o estoque (logica do site).
    """

    def post(self, request, numero):
        loja = self.resolver_loja(request.data.get("telefone"))

        if not loja:
            return self.erro_loja()

        # Leitura so para distinguir 404 de 409; o trabalho de verdade e feito
        # em mudar_status, que re-busca o pedido ja com o lock.
        if not Pedido.objects.filter(id=numero, loja=loja).exists():
            return Response(
                {"error": f"Pedido {numero} nao encontrado para a sua loja."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            pedido = mudar_status(
                numero,
                Pedido.Status.ENTREGUE,
                usuario_editor=loja.responsavel,
            )
        except TransicaoInvalida as erro:
            return Response(
                {"error": str(erro)}, status=status.HTTP_409_CONFLICT
            )

        return Response({"numero": pedido.id, "status": pedido.status})


class BotEstoqueRemoverView(BotAPIView):
    """POST /api/v1/bot/estoque/remover/ — da baixa manual no estoque da loja.

    Body: {"telefone": "...", "itens": [{"codigo": <id produto>, "quantidade": n}]}

    Para perda, quebra ou consumo interno reportado pelo WhatsApp — nao passa
    por pedido nem pelo PDV. Registra MovimentacaoEstoque tipo SAIDA.
    """

    @transaction.atomic
    def post(self, request):
        loja = self.resolver_loja(request.data.get("telefone"))

        if not loja:
            return self.erro_loja()

        itens_brutos = request.data.get("itens") or []
        if not isinstance(itens_brutos, list) or not itens_brutos:
            return Response(
                {"error": "Informe ao menos um item."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Mesma guarda robusta do BotPedidoView: o corpo vem do que a loja
        # digitou no WhatsApp, entao codigo/quantidade podem vir em qualquer
        # formato. Agrega por produto para nao dar baixa duas vezes se o
        # mesmo codigo aparecer repetido no pedido.
        produtos_por_id = {}
        quantidades_por_produto = {}
        for item in itens_brutos:
            if not isinstance(item, dict):
                return Response(
                    {"error": "Cada item precisa ter codigo e quantidade."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            codigo = item.get("codigo")
            try:
                codigo = int(codigo)
            except (TypeError, ValueError):
                return Response(
                    {"error": f"Codigo de produto invalido: {codigo!r}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                quantidade = int(item.get("quantidade"))
            except (TypeError, ValueError):
                quantidade = None
            if not quantidade or quantidade <= 0:
                return Response(
                    {"error": f"Quantidade invalida para o codigo {codigo}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            produto = Produto.objects.filter(id=codigo, is_deleted=False).first()
            if not produto:
                return Response(
                    {"error": f"Produto de codigo {codigo} nao encontrado."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            produtos_por_id[produto.id] = produto
            quantidades_por_produto[produto.id] = (
                quantidades_por_produto.get(produto.id, 0) + quantidade
            )

        # Lock nas linhas de estoque envolvidas antes de validar disponibilidade:
        # sem isso, duas remocoes concorrentes (ex.: bot repetindo apos falha de
        # rede) poderiam passar as duas pela checagem e deixar o saldo negativo.
        estoques = {
            estoque.produto_id: estoque
            for estoque in Estoque.objects.select_for_update()
            .filter(loja=loja, produto_id__in=produtos_por_id, is_deleted=False)
        }

        for produto_id, quantidade in quantidades_por_produto.items():
            estoque = estoques.get(produto_id)
            disponivel = estoque.quantidade_atual if estoque else 0
            if disponivel < quantidade:
                return Response(
                    {
                        "error": (
                            f"Estoque insuficiente de "
                            f"{produtos_por_id[produto_id].nome_produto}: "
                            f"disponivel {disponivel}, solicitado {quantidade}."
                        )
                    },
                    status=status.HTTP_409_CONFLICT,
                )

        itens_removidos = []
        for produto_id, quantidade in quantidades_por_produto.items():
            estoque = estoques[produto_id]
            estoque.quantidade_atual -= quantidade
            estoque.save(update_fields=["quantidade_atual", "updated_at"])
            MovimentacaoEstoque.objects.create(
                tipo=MovimentacaoEstoque.Tipo.SAIDA,
                produto=produtos_por_id[produto_id],
                loja_origem=loja,
                quantidade=quantidade,
                usuario=loja.responsavel,
            )
            notificar_estoque_baixo(estoque, usuario_editor=loja.responsavel)
            itens_removidos.append({
                "produto": produtos_por_id[produto_id].nome_produto,
                "quantidade_removida": quantidade,
                "quantidade_atual": estoque.quantidade_atual,
            })

        return Response({"itens": itens_removidos}, status=status.HTTP_200_OK)


class BotRelatorioView(BotAPIView):
    """GET /api/v1/bot/relatorio/?telefone=...&periodo=dia|semana|mes&data=AAAA-MM-DD

    Exclusivo do gerente (telefone == GERENTE_WHATSAPP): devolve o PDF de pedidos
    de TODAS as lojas (o bot Node reenvia como documento no WhatsApp). Qualquer
    outro telefone recebe 403. `periodo` default "dia"; `data` opcional escolhe um
    dia/semana/mês específico (default = hoje).
    """

    def get(self, request):
        # Só o gerente vê PDF. Loja nenhuma acessa o relatório.
        if not eh_gerente(request.query_params.get("telefone")):
            return Response(
                {"error": "Apenas o gerente pode gerar o relatório."},
                status=status.HTTP_403_FORBIDDEN,
            )

        periodo = request.query_params.get("periodo", "dia")
        if periodo not in ("dia", "semana", "mes"):
            periodo = "dia"

        data_ref = None
        data_str = request.query_params.get("data")
        if data_str:
            try:
                data_ref = date.fromisoformat(data_str)
            except ValueError:
                return Response(
                    {"error": "Data inválida; use AAAA-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Gerente sempre recebe o relatório de TODAS as lojas.
        return gerar_relatorio_pedidos_pdf(periodo, data_ref)
