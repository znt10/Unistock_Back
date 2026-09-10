"""Handler de excecoes da API.

Existe por um motivo so hoje: devolver o aviso de teto de estoque com os
numeros como numeros. O handler padrao do DRF passa todo valor por
ErrorDetail, que e uma subclasse de str — util para mensagens de validacao,
atrapalhado para um payload que o front usa para fazer conta.
"""

from rest_framework.response import Response
from rest_framework.views import exception_handler as handler_padrao

from app.services.estoque_teto import ExcessoDeEstoque


def tratar(exc, context):
    if isinstance(exc, ExcessoDeEstoque):
        return Response(exc.payload, status=409)

    return handler_padrao(exc, context)
