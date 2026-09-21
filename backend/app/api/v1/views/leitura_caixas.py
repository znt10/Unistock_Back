"""Endpoints da leitura das caixas na loja (parte 3).

A regra mora em services/leitura_caixas.py; aqui so se traduz para HTTP.
"""

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from app.services.leitura_caixas import LeituraRecusada, desfazer_leitura, ler_caixa


def responder_recusa(erro):
    return Response(
        {"error": erro.mensagem, "codigo": erro.codigo, **erro.extras},
        status=erro.status,
    )


class LerCaixaView(APIView):
    """POST /api/v1/caixas/<codigo>/ler/ — aplica o proximo passo da caixa."""

    permission_classes = [IsAuthenticated]

    def post(self, request, codigo):
        # So aceita confirmacao explicita (JSON true); qualquer outra coisa
        # (string "false", numero, ausente) conta como nao confirmado.
        confirmar = request.data.get("confirmar") is True
        try:
            return Response(ler_caixa(codigo, request.user, confirmar=confirmar))
        except LeituraRecusada as erro:
            return responder_recusa(erro)


class DesfazerLeituraView(APIView):
    """POST /api/v1/leituras/<id>/desfazer/ — volta o que a leitura fez."""

    permission_classes = [IsAuthenticated]

    def post(self, request, leitura_id):
        try:
            return Response(desfazer_leitura(leitura_id, request.user))
        except LeituraRecusada as erro:
            return responder_recusa(erro)
