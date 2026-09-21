"""Endpoints da leitura das caixas na loja (parte 3).

A regra mora em services/leitura_caixas.py; aqui so se traduz para HTTP.
"""

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from app.services.leitura_caixas import LeituraRecusada, ler_caixa


def responder_recusa(erro):
    return Response(
        {"error": erro.mensagem, "codigo": erro.codigo, **erro.extras},
        status=erro.status,
    )


class LerCaixaView(APIView):
    """POST /api/v1/caixas/<codigo>/ler/ — aplica o proximo passo da caixa."""

    permission_classes = [IsAuthenticated]

    def post(self, request, codigo):
        confirmar = bool(request.data.get("confirmar", False))
        try:
            return Response(ler_caixa(codigo, request.user, confirmar=confirmar))
        except LeituraRecusada as erro:
            return responder_recusa(erro)
