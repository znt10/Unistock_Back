"""Webhook que recebe mensagens da Evolution API e aciona o bot (app.api.v1.bot).

Comandos por texto (sem acento, case-insensitive):

    catalogo                  lista categorias e produtos
    pedido <cod>x<qtd> ...    abre pedido, ex: "pedido 12x2 7x1"
    confirmar <numero>        marca pedido como entregue
    remover <cod>x<qtd> ...   da baixa manual no estoque, ex: "remover 12x1"
    relatorio                 aponta pro painel — PDF nao vai por aqui

A Evolution API manda todo evento pro mesmo webhook (mensagem recebida,
enviada, status de conexao...); so processamos messages.upsert com
fromMe=false, senao o bot responderia as proprias mensagens.

Reaproveita as views de app.api.v1.bot (ja testadas) chamando-as diretamente
via RequestFactory, com o mesmo BOT_SERVICE_TOKEN que o bot usa — evita
duplicar a regra de negocio (resolucao de loja, validacao de itens, lock de
estoque etc.) num segundo caminho de codigo.
"""

import logging
import re

from django.conf import settings
from django.test import RequestFactory
from django.utils.crypto import constant_time_compare
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from app.services.whatsapp import enviar_mensagem

from .bot import (
    BotCatalogoView,
    BotEstoqueRemoverView,
    BotPedidoConfirmarView,
    BotPedidoView,
    normalizar_telefone,
)

logger = logging.getLogger(__name__)

_factory = RequestFactory()

ITEM_RE = re.compile(r"(\d+)\s*x\s*(\d+)", re.IGNORECASE)

AJUDA = (
    "Nao entendi. Comandos:\n"
    "*catalogo* - ver produtos\n"
    "*pedido 12x2 7x1* - pedir 2 do produto 12 e 1 do produto 7\n"
    "*confirmar 45* - avisar que o pedido 45 chegou\n"
    "*remover 12x1* - dar baixa manual no estoque"
)


def _chamar_view(view_cls, metodo, caminho, telefone=None, itens=None, url_kwargs=None):
    cabecalho = {"HTTP_X_BOT_TOKEN": settings.BOT_SERVICE_TOKEN}
    if metodo == "get":
        params = {"telefone": telefone} if telefone else {}
        request = _factory.get(caminho, data=params, **cabecalho)
    else:
        corpo = {"telefone": telefone}
        if itens is not None:
            corpo["itens"] = itens
        request = _factory.post(caminho, data=corpo, content_type="application/json", **cabecalho)
    return view_cls.as_view()(request, **(url_kwargs or {}))


def _parse_itens(texto):
    return [
        {"codigo": codigo, "quantidade": int(quantidade)}
        for codigo, quantidade in ITEM_RE.findall(texto)
    ]


def executar_comando(telefone, texto):
    """Roda o comando digitado no WhatsApp e devolve o texto de resposta."""
    texto = (texto or "").strip()
    comando, _, resto = texto.partition(" ")
    comando = comando.strip().lower()

    if comando in ("catalogo", "catálogo", "menu", "produtos"):
        response = _chamar_view(
            BotCatalogoView, "get", "/api/v1/bot/catalogo/", telefone=telefone
        )
        if response.status_code >= 400:
            return f"Nao deu: {response.data.get('error', 'erro desconhecido')}"
        categorias = response.data.get("categorias", [])
        if not categorias:
            return "Catalogo vazio no momento."

        linhas = []
        for categoria in categorias:
            linhas.append(f"*{categoria['nome']}*")
            for produto in categoria["produtos"]:
                # "UNIDADE" e o padrao/generico: so vale mostrar a unidade
                # quando ela diz algo (CAIXA, PACOTE, QUILO, LITRO).
                unidade = produto["unidade"]
                sufixo = f" ({unidade})" if unidade != "UNIDADE" else ""
                linhas.append(f"  {produto['codigo']} - {produto['nome']}{sufixo}")
            linhas.append("")
        return "\n".join(linhas).strip()

    if comando == "pedido":
        itens = _parse_itens(resto)
        if not itens:
            return "Nao entendi os itens. Ex: *pedido 12x2 7x1*"
        response = _chamar_view(
            BotPedidoView, "post", "/api/v1/bot/pedido/", telefone=telefone, itens=itens
        )
        if response.status_code >= 400:
            return f"Nao deu: {response.data.get('error', 'erro desconhecido')}"
        dados = response.data
        return f"Pedido #{dados['numero']} criado para {dados['loja']}. Status: {dados['status']}."

    if comando == "confirmar":
        numero = resto.strip()
        if not numero.isdigit():
            return "Informe o numero do pedido. Ex: *confirmar 45*"
        response = _chamar_view(
            BotPedidoConfirmarView,
            "post",
            f"/api/v1/bot/pedido/{numero}/confirmar/",
            telefone=telefone,
            url_kwargs={"numero": int(numero)},
        )
        if response.status_code >= 400:
            return f"Nao deu: {response.data.get('error', 'erro desconhecido')}"
        return f"Pedido #{response.data['numero']} confirmado como entregue."

    if comando == "remover":
        itens = _parse_itens(resto)
        if not itens:
            return "Nao entendi os itens. Ex: *remover 12x1*"
        response = _chamar_view(
            BotEstoqueRemoverView,
            "post",
            "/api/v1/bot/estoque/remover/",
            telefone=telefone,
            itens=itens,
        )
        if response.status_code >= 400:
            return f"Nao deu: {response.data.get('error', 'erro desconhecido')}"
        linhas = [
            f"{item['produto']}: -{item['quantidade_removida']} (fica {item['quantidade_atual']})"
            for item in response.data["itens"]
        ]
        return "Baixa registrada:\n" + "\n".join(linhas)

    if comando in ("relatorio", "relatório"):
        return "Relatorio em PDF ainda so pelo painel, nao manda por aqui."

    return AJUDA


class EvolutionWebhookView(APIView):
    """POST /api/v1/bot/webhook/<token>/ — recebe eventos da Evolution API."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    def post(self, request, token):
        if not settings.BOT_SERVICE_TOKEN or not settings.EVOLUTION_WEBHOOK_TOKEN:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if not constant_time_compare(token, settings.EVOLUTION_WEBHOOK_TOKEN):
            return Response(status=status.HTTP_403_FORBIDDEN)

        try:
            payload = request.data or {}
        except Exception:
            logger.warning(
                "Webhook Evolution: corpo nao parseou como JSON. Content-Type=%r body=%r",
                request.META.get("CONTENT_TYPE"),
                request.body[:2000],
            )
            return Response(status=status.HTTP_200_OK)

        if not isinstance(payload, dict):
            logger.warning("Webhook Evolution: payload nao e objeto JSON: %r", payload)
            return Response(status=status.HTTP_200_OK)

        evento = str(payload.get("event", "")).lower()
        if evento != "messages.upsert":
            return Response(status=status.HTTP_200_OK)

        dados = payload.get("data") or {}
        chave = dados.get("key") or {}
        if chave.get("fromMe"):
            return Response(status=status.HTTP_200_OK)

        telefone = normalizar_telefone(chave.get("remoteJid"))
        mensagem = dados.get("message") or {}
        texto = (
            mensagem.get("conversation")
            or (mensagem.get("extendedTextMessage") or {}).get("text")
            or ""
        )

        if not telefone or not texto:
            return Response(status=status.HTTP_200_OK)

        try:
            resposta = executar_comando(telefone, texto)
        except Exception:
            logger.exception("Erro processando comando do bot de WhatsApp")
            resposta = "Deu erro por aqui, tenta de novo em instantes."

        enviar_mensagem(telefone, resposta)
        return Response(status=status.HTTP_200_OK)
