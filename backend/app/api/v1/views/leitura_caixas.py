"""Endpoints da leitura das caixas na loja (parte 3).

A regra mora em services/leitura_caixas.py; aqui so se traduz para HTTP.
"""

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from app.services.leitura_caixas import (
    LeituraRecusada,
    a_caminho,
    desfazer_leitura,
    detalhe_da_caixa,
    ler_caixa,
    loja_do_leitor,
)


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


class DetalheDaCaixaView(APIView):
    """GET /api/v1/caixas/<codigo>/ — a caixa, para a pagina do link do QR."""

    permission_classes = [IsAuthenticated]

    def get(self, request, codigo):
        try:
            return Response(detalhe_da_caixa(codigo, request.user))
        except LeituraRecusada as erro:
            return responder_recusa(erro)


class ACaminhoView(APIView):
    """GET /api/v1/caixas/a-caminho/ — o que falta chegar para a loja."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        loja = loja_do_leitor(request.user)
        if loja is None:
            return Response(
                {"error": "Só o acesso de uma loja lê caixas.", "codigo": "sem_loja"},
                status=403,
            )
        return Response(a_caminho(loja))
