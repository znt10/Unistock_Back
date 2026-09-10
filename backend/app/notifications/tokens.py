"""Tokens assinados para definir senha (1o acesso e 'esqueci a senha').

Uso unico: o payload carrega uma marca derivada da senha atual. Ao definir a
senha a marca muda, entao o link para de funcionar — um link vazado nao continua
valido pelos 3 dias.
"""

from django.core import signing
from django.utils.crypto import salted_hmac

SALT_SENHA = "unistock-definir-senha"
VALIDADE_TOKEN_SEGUNDOS = 60 * 60 * 24 * 3  # 3 dias


def _marca_da_senha(usuario):
    """Marca derivada da senha atual, para invalidar o token quando ela muda.

    HMAC em vez de um pedaco do hash: o payload do token e assinado mas NAO e
    criptografado (base64 legivel), entao nao pode carregar material do hash da
    senha. Mesma ideia do PasswordResetTokenGenerator do Django.
    """
    return salted_hmac(
        "unistock-marca-senha", usuario.password or ""
    ).hexdigest()[:12]


def gerar_token_senha(usuario):
    return signing.dumps(
        {"user_id": usuario.id, "marca": _marca_da_senha(usuario)},
        salt=SALT_SENHA,
    )


class ContaInexistente(Exception):
    """A assinatura confere, mas o usuario do token nao existe mais.

    Separado de BadSignature porque as duas situacoes pedem coisas OPOSTAS de
    quem recebeu o link: token usado pede "esqueci a senha"; conta apagada
    pede recadastro. Tratar as duas com a mesma mensagem manda a pessoa
    procurar o problema no lugar errado.
    """


def validar_token_senha(token):
    """Devolve o user_id do token.

    Levanta signing.SignatureExpired se passou da validade, ContaInexistente
    se o usuario foi apagado, ou signing.BadSignature se foi adulterado ou ja
    foi usado.
    """
    from django.contrib.auth.models import User

    dados = signing.loads(token, salt=SALT_SENHA, max_age=VALIDADE_TOKEN_SEGUNDOS)

    usuario = User.objects.filter(id=dados["user_id"]).first()
    if not usuario:
        raise ContaInexistente(dados["user_id"])

    if _marca_da_senha(usuario) != dados.get("marca"):
        raise signing.BadSignature("Token ja utilizado.")

    return usuario.id
