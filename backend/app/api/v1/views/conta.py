"""Em qual Conta um request escreve.

Ler e simetrico (escopar_por_conta resolve para todo mundo), mas escrever nao:
quem tem conta escreve na propria e ponto; o Admin nao tem conta nenhuma e
pode escrever em qualquer uma, entao precisa dizer em qual.
"""

from django.core.exceptions import ValidationError as ErroDeConversao
from rest_framework.exceptions import PermissionDenied, ValidationError

from app.models import Conta
from app.permissions import get_conta_do_usuario, is_admin


def conta_do_request(request):
    """A Conta em que este request pode criar. Nunca confia no corpo sozinho.

    Para quem tem perfil, o campo "conta" do corpo e simplesmente ignorado —
    e o que impede alguem de criar loja ou produto dentro da empresa de
    outro mandando um id na mao.
    """
    conta = get_conta_do_usuario(request.user)
    if conta:
        return conta

    if not is_admin(request.user):
        raise PermissionDenied(
            "Seu usuario nao esta vinculado a nenhuma empresa. "
            "Peca a um admin para vincular voce a uma conta."
        )

    informada = request.data.get("conta")
    if not informada:
        raise ValidationError(
            {"conta": "Admin precisa informar em qual empresa esta cadastrando."}
        )

    try:
        return Conta.objects.get(public_id=informada)
    # ErroDeConversao: um public_id malformado estoura no conversor do
    # UUIDField antes de virar consulta, e sairia como 500 sem isto.
    except (Conta.DoesNotExist, ErroDeConversao, ValueError, TypeError):
        raise ValidationError({"conta": "Empresa nao encontrada."})
