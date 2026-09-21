"""Leitura das caixas na loja (parte 3) — fonte unica.

Cada leitura do mesmo QR avanca um passo, decidido aqui pela situacao da
caixa: A_CAMINHO -> CHEGOU (fabrica -1, loja +1) -> ABERTA (continua
contando) -> ACABOU (loja -1). Cada leitura vira uma LeituraCaixa, que e o
que o desfazer usa para voltar exatamente o que ela fez.

Travas sempre na mesma ordem — caixa, pedido, linhas de Estoque por id — para
duas leituras simultaneas nao se travarem uma a outra.
"""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from app.models import Caixa, Estoque, LeituraCaixa, Loja, MovimentacaoEstoque, Pedido
from app.notifications import notificar_estoque_baixo
from app.services.fabrica import fabrica_da_conta

# Menos que isso desde a ultima leitura: provavelmente a mesma caixa lida de
# novo sem querer (a camera le varias vezes por segundo).
JANELA_DE_CONFIRMACAO = timedelta(minutes=2)
# O aviso com "Desfazer" some da tela em ~8 s; a folga cobre internet lenta.
PRAZO_PARA_DESFAZER = timedelta(minutes=10)

S = Caixa.Situacao
PROXIMO_PASSO = {S.A_CAMINHO: S.CHEGOU, S.CHEGOU: S.ABERTA, S.ABERTA: S.ACABOU}
PASSO_ANTERIOR = {S.CHEGOU: S.A_CAMINHO, S.ABERTA: S.CHEGOU, S.ACABOU: S.ABERTA}
CAMPO_DA_DATA = {S.CHEGOU: "chegou_em", S.ABERTA: "aberta_em", S.ACABOU: "acabou_em"}
COMO_FICOU = {S.CHEGOU: "chegou", S.ABERTA: "foi aberta"}


class LeituraRecusada(Exception):
    """Leitura ou desfazer que a regra nao aceita. A view traduz em HTTP."""

    status = 409
    codigo = "recusada"

    def __init__(self, mensagem, **extras):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.extras = extras


class CaixaNaoEncontrada(LeituraRecusada):
    status = 404
    codigo = "nao_encontrada"


class CaixaDeOutraLoja(LeituraRecusada):
    status = 403
    codigo = "outra_loja"


class PrecisaConfirmar(LeituraRecusada):
    codigo = "precisa_confirmar"


class FabricaSemEstoque(LeituraRecusada):
    codigo = "fabrica_sem_estoque"


class LojaZerada(LeituraRecusada):
    codigo = "loja_zerada"


class LeituraNaoEncontrada(LeituraRecusada):
    status = 404
    codigo = "leitura_nao_encontrada"


class LeituraJaDesfeita(LeituraRecusada):
    codigo = "ja_desfeita"


class CaixaLidaDeNovo(LeituraRecusada):
    codigo = "lida_de_novo"


class PrazoDeDesfazerPassou(LeituraRecusada):
    codigo = "prazo"


def loja_do_leitor(usuario):
    """A loja comum de que este usuario e o acesso, ou None.

    Fabrica nao conta: ela nao le as proprias caixas.
    """
    return (
        Loja.objects.filter(responsavel=usuario, ativo=True, is_deleted=False)
        .exclude(tipo=Loja.Tipo.FABRICA)
        .first()
    )


def _conferir_loja(pedido, usuario):
    if pedido.loja.responsavel_id != usuario.id:
        raise CaixaDeOutraLoja(f"Essa caixa é da {pedido.loja.nome_loja}.")


def _caixa_por_codigo(codigo):
    """Leitura sem trava, so para achar a caixa (e, se for o caso, quem travar
    junto com ela — ver _travar_caixas). A decisao de verdade usa sempre as
    linhas devolvidas por _travar_caixas, nunca esta.
    """
    caixa = Caixa.objects.filter(codigo=codigo).first()
    if caixa is None:
        raise CaixaNaoEncontrada("Caixa não encontrada ou pedido cancelado.")
    return caixa


def _travar_caixas(ids):
    """Trava estas caixas juntas, numa unica select_for_update por id.

    `of=("self",)` evita travar Pedido/ItemPedido: quem chama so quer as
    linhas de Caixa, e o join de _candidata_a_fechar nao pode travar o pedido
    antes da hora (ver o docstring do modulo e o comentario em ler_caixa).
    """
    return {
        c.pk: c
        for c in Caixa.objects.select_for_update(of=("self",)).filter(pk__in=ids).order_by("id")
    }


def _candidata_a_fechar(caixa, pedido, produto):
    """Outra caixa ABERTA do mesmo produto, na mesma loja — leitura sem trava.

    So descobre quem e a candidata para travar junto (ver _travar_caixas); a
    decisao de fechar ou nao usa a linha ja travada, em _abrir.
    """
    return (
        Caixa.objects.filter(
            situacao=S.ABERTA,
            pedido__loja=pedido.loja,
            pedido__itens__produto=produto,
        )
        .exclude(pk=caixa.pk)
        .order_by("aberta_em", "id")
        .first()
    )


def _pedido_travado(caixa):
    return (
        Pedido.objects.select_for_update(of=("self",))
        .select_related("loja")
        .get(pk=caixa.pedido_id)
    )


def _produto(pedido):
    # Pedido da fabrica tem um item so (parte 2).
    return pedido.itens.select_related("produto").get().produto


def _ultima_leitura_valida(caixa):
    return caixa.leituras.filter(desfeita_em__isnull=True).order_by("-created_at", "-id").first()


def _estoques_travados(produto, lojas):
    """Linhas de Estoque deste produto nestas lojas, travadas por id."""
    linhas = (
        Estoque.objects.select_for_update(of=("self",))
        .filter(produto=produto, loja__in=[loja for loja in lojas if loja])
        .order_by("id")
    )
    return {linha.loja_id: linha for linha in linhas}


def _linha_da_loja(loja, produto):
    """Linha de Estoque da loja, criada na primeira chegada.

    Mesmos padroes de somar_itens_no_estoque: minimo e teto sugeridos do
    produto, e o banco exige maximo > minimo.
    """
    linha, _ = Estoque.objects.get_or_create(
        loja=loja,
        produto=produto,
        defaults={
            "quantidade_atual": 0,
            "quantidade_minima": produto.estoque_minimo_sugerido,
            "quantidade_maxima": max(
                produto.estoque_maximo_sugerido, produto.estoque_minimo_sugerido + 1
            ),
        },
    )
    return linha


def _somar(linha, quantidade, usuario):
    linha.quantidade_atual += quantidade
    linha.save(update_fields=["quantidade_atual", "updated_at"])
    notificar_estoque_baixo(linha, usuario_editor=usuario)


def _baixar_na_loja(loja, produto, usuario):
    """Loja -1 com SAIDA (caixa acabou)."""
    linha = _estoques_travados(produto, [loja]).get(loja.id)
    if linha is None or linha.quantidade_atual < 1:
        raise LojaZerada("O estoque da loja já está zerado para esse produto. Avise a gerência.")
    _somar(linha, -1, usuario)
    MovimentacaoEstoque.objects.create(
        tipo=MovimentacaoEstoque.Tipo.SAIDA,
        produto=produto, loja_origem=loja, quantidade=1, usuario=usuario,
    )


def _chegar(pedido, produto, usuario):
    """Fabrica -1, loja +1, TRANSFERENCIA."""
    fabrica = fabrica_da_conta(pedido.loja.conta_id)
    linhas = _estoques_travados(produto, [fabrica, pedido.loja])
    linha_fabrica = linhas.get(fabrica.id) if fabrica else None
    if linha_fabrica is None or linha_fabrica.quantidade_atual < 1:
        raise FabricaSemEstoque("O estoque da fábrica não tem essa caixa. Avise a gerência.")

    linha_loja = linhas.get(pedido.loja_id) or _linha_da_loja(pedido.loja, produto)
    _somar(linha_fabrica, -1, usuario)
    _somar(linha_loja, 1, usuario)
    MovimentacaoEstoque.objects.create(
        tipo=MovimentacaoEstoque.Tipo.TRANSFERENCIA,
        produto=produto, loja_origem=fabrica, loja_destino=pedido.loja,
        quantidade=1, usuario=usuario,
    )


def _abrir(pedido, produto, usuario, agora, candidata):
    """Abre esta caixa; se a candidata (ja travada por _travar_caixas) ainda
    estiver ABERTA, fecha a antiga. Devolve a caixa fechada (ou None).

    A candidata foi achada por uma leitura sem trava (_candidata_a_fechar) e
    pode ter mudado entre aquela leitura e a trava — por isso so fecha se,
    ja travada, ainda estiver ABERTA.
    """
    if candidata is None or candidata.situacao != S.ABERTA:
        return None

    _baixar_na_loja(pedido.loja, produto, usuario)
    candidata.situacao = S.ACABOU
    candidata.acabou_em = agora
    candidata.save(update_fields=["situacao", "acabou_em", "updated_at"])
    return candidata


def descrever_caixa(caixa, pedido):
    """O que a tela mostra de uma caixa."""
    caixas = list(pedido.caixas.values_list("situacao", flat=True))
    return {
        "codigo": caixa.codigo,
        "situacao": caixa.situacao,
        "proximo": PROXIMO_PASSO.get(caixa.situacao),
        "numero": caixa.numero,
        "total": len(caixas),
        "produto_nome": _produto(pedido).nome_produto,
        "loja_nome": pedido.loja.nome_loja,
        "pedido": str(pedido.public_id),
        "pedido_numero": pedido.id,
        "caixas_chegaram": sum(1 for situacao in caixas if situacao != S.A_CAMINHO),
        "caixas_total": len(caixas),
    }


def ler_caixa(codigo, usuario, confirmar=False):
    """Aplica o proximo passo da caixa. Ver o docstring do modulo.

    A ordem de trava (caixa -> pedido -> Estoque) tem uma dobra: quando a
    leitura vai abrir a caixa (CHEGOU -> ABERTA), a caixa que pode fechar
    junto (mesmo produto, mesma loja, ainda ABERTA) tambem e uma Caixa —
    entao as duas travam juntas, numa unica select_for_update por id, antes
    do pedido. Quem ela e, descobrimos com uma leitura sem trava primeiro
    (_candidata_a_fechar); a decisao real usa a linha ja travada.
    """
    with transaction.atomic():
        pre_caixa = _caixa_por_codigo(codigo)
        pre_pedido = Pedido.objects.select_related("loja").get(pk=pre_caixa.pedido_id)

        ids_para_travar = {pre_caixa.pk}
        if pre_caixa.situacao == S.CHEGOU:
            produto_pre = _produto(pre_pedido)
            candidata_pre = _candidata_a_fechar(pre_caixa, pre_pedido, produto_pre)
            if candidata_pre:
                ids_para_travar.add(candidata_pre.pk)

        travadas = _travar_caixas(ids_para_travar)
        caixa = travadas[pre_caixa.pk]

        if caixa.situacao == S.CHEGOU and len(travadas) == 1:
            # Raro: a caixa estava A_CAMINHO na leitura sem trava (chegou
            # entre uma leitura e a outra) e virou CHEGOU so agora, entao a
            # candidata nao entrou na trava acima. Trava so ela agora —
            # excecao aceita a ordem (caixa depois de caixa, mas as duas
            # antes do pedido, entao a regra caixa->pedido->estoque continua
            # valendo).
            produto_pre = _produto(pre_pedido)
            candidata_pre = _candidata_a_fechar(caixa, pre_pedido, produto_pre)
            if candidata_pre:
                travadas = _travar_caixas({caixa.pk, candidata_pre.pk})
                caixa = travadas[caixa.pk]

        pedido = _pedido_travado(caixa)
        _conferir_loja(pedido, usuario)

        if caixa.situacao == S.ACABOU:
            return {
                "leitura": None,
                "ja_acabou": True,
                "caixa": descrever_caixa(caixa, pedido),
                "caixa_fechada": None,
            }

        proximo = PROXIMO_PASSO[caixa.situacao]
        agora = timezone.now()
        ultima = _ultima_leitura_valida(caixa)
        if ultima and not confirmar and agora - ultima.created_at < JANELA_DE_CONFIRMACAO:
            raise PrecisaConfirmar(
                f"Essa caixa {COMO_FICOU[caixa.situacao]} agora. Marcar como {proximo}?",
                proximo=proximo,
            )

        produto = _produto(pedido)
        caixa_fechada = None
        if proximo == S.CHEGOU:
            _chegar(pedido, produto, usuario)
        elif proximo == S.ABERTA:
            candidata = next((c for pk, c in travadas.items() if pk != caixa.pk), None)
            caixa_fechada = _abrir(pedido, produto, usuario, agora, candidata)
        else:
            _baixar_na_loja(pedido.loja, produto, usuario)

        caixa.situacao = proximo
        setattr(caixa, CAMPO_DA_DATA[proximo], agora)
        caixa.save(update_fields=["situacao", CAMPO_DA_DATA[proximo], "updated_at"])

        if proximo == S.CHEGOU and not pedido.caixas.filter(situacao=S.A_CAMINHO).exists():
            # Direto, e nao por mudar_status: site e bot continuam proibidos de
            # entregar pedido da fabrica (ver TRANSICOES em services/pedidos.py).
            pedido.status = Pedido.Status.ENTREGUE
            pedido.save(update_fields=["status", "updated_at"])

        leitura = LeituraCaixa.objects.create(
            caixa=caixa, passo=proximo, usuario=usuario, caixa_fechada=caixa_fechada
        )

        return {
            "leitura": str(leitura.public_id),
            "ja_acabou": False,
            "caixa": descrever_caixa(caixa, pedido),
            # A caixa fechada pode ser de outro pedido: descrita com o dela.
            "caixa_fechada": (
                descrever_caixa(caixa_fechada, caixa_fechada.pedido) if caixa_fechada else None
            ),
        }


def _repor_na_loja(loja, produto, usuario):
    """Loja +1 com ENTRADA (volta de um ACABOU)."""
    linha = _estoques_travados(produto, [loja]).get(loja.id) or _linha_da_loja(loja, produto)
    _somar(linha, 1, usuario)
    MovimentacaoEstoque.objects.create(
        tipo=MovimentacaoEstoque.Tipo.ENTRADA,
        produto=produto, loja_destino=loja, quantidade=1, usuario=usuario,
    )


def _devolver_para_fabrica(pedido, produto, usuario):
    """Loja -1, fabrica +1, TRANSFERENCIA no sentido contrario da chegada."""
    fabrica = fabrica_da_conta(pedido.loja.conta_id)
    if fabrica is None:
        raise FabricaSemEstoque("A empresa não tem fábrica ativa. Avise a gerência.")
    linhas = _estoques_travados(produto, [fabrica, pedido.loja])
    linha_loja = linhas.get(pedido.loja_id)
    if linha_loja is None or linha_loja.quantidade_atual < 1:
        raise LojaZerada("O estoque da loja já está zerado para esse produto. Avise a gerência.")

    linha_fabrica = linhas.get(fabrica.id) or _linha_da_loja(fabrica, produto)
    _somar(linha_loja, -1, usuario)
    _somar(linha_fabrica, 1, usuario)
    MovimentacaoEstoque.objects.create(
        tipo=MovimentacaoEstoque.Tipo.TRANSFERENCIA,
        produto=produto, loja_origem=pedido.loja, loja_destino=fabrica,
        quantidade=1, usuario=usuario,
    )


def desfazer_leitura(leitura_id, usuario):
    """Volta exatamente o que uma leitura fez. Nada e apagado.

    Ordem de trava: caixa (e a caixa_fechada junto, se houver) -> pedido ->
    Estoque. A leitura em si e lida sem trava — so o public_id (uuid), sem
    concorrencia real em cima dela — e relida depois das travas para pegar um
    desfazer concorrente.
    """
    with transaction.atomic():
        leitura = LeituraCaixa.objects.filter(public_id=leitura_id).first()
        if leitura is None:
            raise LeituraNaoEncontrada("Leitura não encontrada.")

        ids_para_travar = {leitura.caixa_id}
        if leitura.caixa_fechada_id:
            ids_para_travar.add(leitura.caixa_fechada_id)
        travadas = _travar_caixas(ids_para_travar)
        caixa = travadas[leitura.caixa_id]

        pedido = _pedido_travado(caixa)
        _conferir_loja(pedido, usuario)
        # Relida depois das travas: outra requisicao pode ter desfeito antes.
        leitura.refresh_from_db()

        if leitura.desfeita_em is not None:
            raise LeituraJaDesfeita("Essa leitura já foi desfeita.")
        if _ultima_leitura_valida(caixa).pk != leitura.pk:
            raise CaixaLidaDeNovo("Essa caixa já foi lida de novo.")
        agora = timezone.now()
        if agora - leitura.created_at > PRAZO_PARA_DESFAZER:
            raise PrazoDeDesfazerPassou("Passou o prazo para desfazer essa leitura.")

        produto = _produto(pedido)
        if leitura.passo == S.CHEGOU:
            _devolver_para_fabrica(pedido, produto, usuario)
            if pedido.status == Pedido.Status.ENTREGUE:
                pedido.status = Pedido.Status.EM_ENTREGA
                pedido.save(update_fields=["status", "updated_at"])
        elif leitura.passo == S.ACABOU:
            _repor_na_loja(pedido.loja, produto, usuario)

        reaberta = None
        if leitura.caixa_fechada_id:
            reaberta = travadas[leitura.caixa_fechada_id]
            _repor_na_loja(pedido.loja, produto, usuario)
            reaberta.situacao = S.ABERTA
            reaberta.acabou_em = None
            reaberta.save(update_fields=["situacao", "acabou_em", "updated_at"])

        campo = CAMPO_DA_DATA[leitura.passo]
        caixa.situacao = PASSO_ANTERIOR[leitura.passo]
        setattr(caixa, campo, None)
        caixa.save(update_fields=["situacao", campo, "updated_at"])

        leitura.desfeita_em = agora
        leitura.save(update_fields=["desfeita_em", "updated_at"])

        return {
            "caixa": descrever_caixa(caixa, pedido),
            "caixa_reaberta": descrever_caixa(reaberta, reaberta.pedido) if reaberta else None,
        }
