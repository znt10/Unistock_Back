"""Tokens assinados para definir senha (1o acesso e 'esqueci a senha').

Uso unico: o payload carrega um trecho do hash da senha atual. Ao definir a
senha o hash muda, entao o link para de funcionar — um link vazado nao continua
valido pelos 3 dias.
"""

from django.core import signing

SALT_SENHA = "unistock-definir-senha"
VALIDADE_TOKEN_SEGUNDOS = 60 * 60 * 24 * 3  # 3 dias


def _marca_da_senha(usuario):
    """Trecho do hash atual da senha. Muda quando a senha muda."""
    return (usuario.password or "")[-12:]


def gerar_token_senha(usuario):
    return signing.dumps(
        {"user_id": usuario.id, "marca": _marca_da_senha(usuario)},
        salt=SALT_SENHA,
    )


def validar_token_senha(token):
    """Devolve o user_id do token.

    Levanta signing.SignatureExpired se passou da validade, ou
    signing.BadSignature se foi adulterado ou ja foi usado.
    """
    from django.contrib.auth.models import User

    dados = signing.loads(token, salt=SALT_SENHA, max_age=VALIDADE_TOKEN_SEGUNDOS)

    usuario = User.objects.filter(id=dados["user_id"]).first()
    if not usuario or _marca_da_senha(usuario) != dados.get("marca"):
        raise signing.BadSignature("Token ja utilizado ou usuario inexistente.")

    return usuario.id
