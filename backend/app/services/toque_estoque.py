"""Toque de +1/-1 no celular — fonte unica.

Cada toque muda o estoque em um e registra um ToqueEstoque com o significado
(producao na fabrica, correcao no resto). A regra de caixa da loja (-1 que
fecha uma caixa do QR) esta aqui, e tambem o desfazer do toque.

Travas sempre na mesma ordem — caixa, depois linha de Estoque por id.
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from app.models import Caixa, Estoque, Loja, MovimentacaoEstoque, Produto, ToqueEstoque
from app.permissions import get_conta_do_usuario, is_admin, is_gerente
from app.services.fabrica import _caixas, caixas_a_caminho
from app.services.leitura_caixas import PRAZO_PARA_DESFAZER, _linha_da_loja, _somar

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


class ToqueNaoEncontrado(ToqueRecusado):
    status = 404
    codigo = "nao_encontrado"


class ToqueJaDesfeito(ToqueRecusado):
    codigo = "ja_desfeito"


class PrazoPassou(ToqueRecusado):
    codigo = "prazo"


class CaixaMudou(ToqueRecusado):
    codigo = "caixa_mudou"


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


def _caixa_a_encerrar(loja, produto):
    """Caixa da loja que o -1 fecha, ja travada: a ABERTA mais antiga, senao a
    CHEGOU mais antiga. None se nao ha. O estado da caixa decide (mesma regra
    de ler_caixa): produto sem caixas nao acha nenhuma e fica em AJUSTE.

    Tem de rodar ANTES de travar o Estoque (ordem caixa -> estoque).
    """
    caixas = list(
        Caixa.objects.select_for_update(of=("self",))
        .filter(
            situacao__in=[Caixa.Situacao.ABERTA, Caixa.Situacao.CHEGOU],
            pedido__loja=loja,
            pedido__itens__produto=produto,
        )
        .select_related("pedido")
        .order_by("id")
    )
    for situacao, campo in ((Caixa.Situacao.ABERTA, "aberta_em"), (Caixa.Situacao.CHEGOU, "chegou_em")):
        candidatas = [c for c in caixas if c.situacao == situacao]
        if candidatas:
            # sem data (nao deveria ocorrer) vai para o fim; id desempata
            return min(candidatas, key=lambda c: (getattr(c, campo) is None, getattr(c, campo) or 0, c.id))
    return None


def _encerrar_caixa(caixa, loja, produto, usuario):
    """Fecha a caixa e registra a SAIDA de 1. Devolve a movimentacao."""
    caixa.situacao = Caixa.Situacao.ACABOU
    caixa.acabou_em = timezone.now()
    caixa.save(update_fields=["situacao", "acabou_em", "updated_at"])
    return MovimentacaoEstoque.objects.create(
        tipo=T.SAIDA, produto=produto, loja_origem=loja, quantidade=1, usuario=usuario,
    )


def _conferir_baixa(linha, loja, produto):
    """Recusas de tirar 1 da linha (ja travada): zerado e, na fabrica, caixas a caminho."""
    if linha.quantidade_atual < 1:
        raise Zerado("O estoque já está zerado.")
    if loja.tipo == Loja.Tipo.FABRICA:
        a_caminho = caixas_a_caminho(loja, [produto.id]).get(produto.id, 0)
        if linha.quantidade_atual - 1 < a_caminho:
            raise CaixasACaminho(
                f"Tem {a_caminho} {_caixas(a_caminho)} "
                f"{'impressa' if a_caminho == 1 else 'impressas'} a caminho; não dá para baixar mais."
            )


def tocar(loja, produto, delta, usuario):
    """Aplica um toque de +1 ou -1 e devolve o resumo para a tela."""
    _conferir_permissao(loja, usuario)
    _conferir_produto(loja, produto)

    with transaction.atomic():
        caixa = None
        if delta < 0 and loja.tipo != Loja.Tipo.FABRICA:
            caixa = _caixa_a_encerrar(loja, produto)
        linha = _linha_da_loja(loja, produto)
        linha = Estoque.objects.select_for_update(of=("self",)).get(pk=linha.pk)

        if delta < 0:
            _conferir_baixa(linha, loja, produto)

        _somar(linha, delta, usuario)
        situacao_anterior = None
        if caixa is not None:
            situacao_anterior = caixa.situacao
            movimentacao = _encerrar_caixa(caixa, loja, produto, usuario)
            significado = S.FIM_DE_CAIXA
        else:
            movimentacao, significado = _movimentar(loja, produto, delta, usuario)
        toque = ToqueEstoque.objects.create(
            estoque=linha, usuario=usuario, delta=delta,
            significado=significado, movimentacao=movimentacao,
            caixa=caixa, situacao_anterior_da_caixa=situacao_anterior,
        )

    return {
        "toque": str(toque.public_id),
        "produto": produto.nome_produto,
        "quantidade": linha.quantidade_atual,
        "significado": significado,
        "caixa": (
            {"numero": caixa.numero, "total": caixa.pedido.caixas.count()}
            if caixa is not None else None
        ),
    }


def desfazer_toque(toque_id, usuario):
    """Volta um toque dentro do prazo. Nada e apagado: grava o AJUSTE inverso.

    Ordem de trava: caixa (se houver) -> Estoque. A primeira leitura do toque
    e sem trava, so para achar o que travar; e relida (refresh_from_db) depois
    das travas, antes de qualquer decisao.
    """
    with transaction.atomic():
        toque = ToqueEstoque.objects.select_related("estoque__loja", "estoque__produto").filter(
            public_id=toque_id
        ).first()
        if toque is None:
            raise ToqueNaoEncontrado("Toque não encontrado.")
        if toque.usuario_id != usuario.id:
            raise SemPermissao("Só quem tocou pode desfazer.")

        caixa = None
        if toque.caixa_id:
            caixa = Caixa.objects.select_for_update(of=("self",)).get(pk=toque.caixa_id)
        linha = Estoque.objects.select_for_update(of=("self",)).get(pk=toque.estoque_id)
        loja, produto = toque.estoque.loja, toque.estoque.produto
        toque.refresh_from_db()

        if toque.desfeito_em is not None:
            raise ToqueJaDesfeito("Esse toque já foi desfeito.")
        agora = timezone.now()
        if agora - toque.created_at > PRAZO_PARA_DESFAZER:
            raise PrazoPassou("Passou o prazo para desfazer esse toque.")
        if toque.significado == S.FIM_DE_CAIXA and caixa.situacao != Caixa.Situacao.ACABOU:
            raise CaixaMudou("Essa caixa mudou depois do toque.")

        inverso = -toque.delta
        if inverso < 0:
            _conferir_baixa(linha, loja, produto)

        _somar(linha, inverso, usuario)
        if toque.significado == S.FIM_DE_CAIXA:
            caixa.situacao = toque.situacao_anterior_da_caixa
            caixa.acabou_em = None
            caixa.save(update_fields=["situacao", "acabou_em", "updated_at"])
        MovimentacaoEstoque.objects.create(
            tipo=T.AJUSTE, produto=produto, loja_origem=loja,
            quantidade=inverso, usuario=usuario,
        )
        toque.desfeito_em = agora
        toque.save(update_fields=["desfeito_em"])

    return {"produto": produto.nome_produto, "quantidade": linha.quantidade_atual}


def itens_da_minha_loja(loja):
    """Lista da tela do celular: produtos da loja com a quantidade e, na
    fabrica, o que foi produzido hoje. Duas consultas fixas, sem N+1."""
    fabrica = loja.tipo == Loja.Tipo.FABRICA
    produtos = Produto.objects.filter(conta_id=loja.conta_id, is_deleted=False).select_related("categoria")
    if fabrica:
        produtos = produtos.filter(vem_da_fabrica=True)

    linhas = dict(
        Estoque.objects.filter(loja=loja).values_list("produto_id", "quantidade_atual")
    )

    hoje = {}
    if fabrica:
        # dia local (America/Sao_Paulo), nao o dia em UTC
        inicio = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
        fim = inicio + timedelta(days=1)
        hoje = dict(
            ToqueEstoque.objects.filter(
                estoque__loja=loja, significado=S.PRODUCAO, desfeito_em__isnull=True,
                created_at__gte=inicio, created_at__lt=fim,
            )
            .values("estoque__produto_id")
            .annotate(total=Sum("delta"))
            .values_list("estoque__produto_id", "total")
        )

    itens = []
    for produto in produtos:
        categoria = produto.categoria
        itens.append({
            "produto": str(produto.public_id),
            "produto_nome": produto.nome_produto,
            "categoria": categoria.nome if categoria else "Sem categoria",
            "categoria_ordem": categoria.ordem if categoria else 999,
            "quantidade": linhas.get(produto.id, 0),
            "hoje": hoje.get(produto.id, 0) if fabrica else None,
        })
    itens.sort(key=lambda i: (i["categoria_ordem"], i["categoria"], i["produto_nome"]))
    return itens
