"""Toque de +1/-1 no celular — fonte unica.

Cada toque muda o estoque em um e registra um ToqueEstoque com o significado
(producao na fabrica, correcao no resto). A regra de caixa da loja (-1 que
fecha uma caixa do QR) e do desfazer ficam nas proximas etapas.

Travas sempre na mesma ordem — caixa, depois linha de Estoque por id.
"""

from django.db import transaction

from app.models import Estoque, Loja, MovimentacaoEstoque, ToqueEstoque
from app.permissions import get_conta_do_usuario, is_admin, is_gerente
from app.services.fabrica import caixas_a_caminho
from app.services.leitura_caixas import _linha_da_loja, _somar

S = ToqueEstoque.Significado
T = MovimentacaoEstoque.Tipo


class ToqueRecusado(Exception):
    """Toque que a regra nao aceita. A view traduz em HTTP."""

    status = 409
    codigo = "recusado"

    def __init__(self, mensagem, **extras):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.extras = extras


class SemPermissao(ToqueRecusado):
    status = 403
    codigo = "sem_permissao"


class ProdutoInvalido(ToqueRecusado):
    status = 400
    codigo = "produto_invalido"


class Zerado(ToqueRecusado):
    codigo = "zerado"


class CaixasACaminho(ToqueRecusado):
    codigo = "a_caminho"


def _conferir_permissao(loja, usuario):
    if is_admin(usuario):
        return
    if is_gerente(usuario):
        conta = get_conta_do_usuario(usuario)
        if conta is not None and loja.conta_id == conta.id:
            return
    elif loja.responsavel_id == usuario.id:
        return
    raise SemPermissao("Você só mexe no estoque da sua loja.")


def _conferir_produto(loja, produto):
    if produto.conta_id != loja.conta_id:
        raise ProdutoInvalido("Esse produto não é desta conta.")
    if loja.tipo == Loja.Tipo.FABRICA and not produto.vem_da_fabrica:
        raise ProdutoInvalido("Esse produto não vem da fábrica.")


def _movimentar(loja, produto, delta, usuario):
    """Cria a movimentacao do toque e devolve (movimentacao, significado)."""
    if loja.tipo == Loja.Tipo.FABRICA and delta > 0:
        return (
            MovimentacaoEstoque.objects.create(
                tipo=T.ENTRADA, produto=produto, loja_destino=loja,
                quantidade=1, usuario=usuario,
            ),
            S.PRODUCAO,
        )
    return (
        MovimentacaoEstoque.objects.create(
            tipo=T.AJUSTE, produto=produto, loja_origem=loja,
            quantidade=delta, usuario=usuario,
        ),
        S.CORRECAO,
    )


def tocar(loja, produto, delta, usuario):
    """Aplica um toque de +1 ou -1 e devolve o resumo para a tela."""
    _conferir_permissao(loja, usuario)
    _conferir_produto(loja, produto)

    with transaction.atomic():
        linha = _linha_da_loja(loja, produto)
        linha = Estoque.objects.select_for_update(of=("self",)).get(pk=linha.pk)

        if delta < 0:
            if linha.quantidade_atual < 1:
                raise Zerado("O estoque já está zerado.")
            if loja.tipo == Loja.Tipo.FABRICA:
                a_caminho = caixas_a_caminho(loja, [produto.id]).get(produto.id, 0)
                if linha.quantidade_atual - 1 < a_caminho:
                    raise CaixasACaminho(
                        f"Tem {a_caminho} caixas impressas a caminho; não dá para baixar mais."
                    )

        _somar(linha, delta, usuario)
        movimentacao, significado = _movimentar(loja, produto, delta, usuario)
        toque = ToqueEstoque.objects.create(
            estoque=linha, usuario=usuario, delta=delta,
            significado=significado, movimentacao=movimentacao,
        )

    return {
        "toque": str(toque.public_id),
        "produto": produto.nome_produto,
        "quantidade": linha.quantidade_atual,
        "significado": significado,
        "caixa": None,
    }
