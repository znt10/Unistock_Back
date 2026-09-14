"""Regras da fabrica — fonte unica.

A fabrica e uma Loja com tipo Fabrica, uma por empresa. Daqui saem as
perguntas "qual e a fabrica desta empresa?" e "este produto segue o fluxo das
caixas?", e as acoes da fabrica (imprimir etiquetas, registrar producao).

Fora das views pelo mesmo motivo de services/pedidos.py: o site, o bot e a
leitura das caixas (parte 3) precisam da mesma resposta.
"""

import secrets
from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import Count
from rest_framework.exceptions import ValidationError

from app.models import Caixa, Conta, Estoque, ItemPedido, Loja, MovimentacaoEstoque, Pedido
from app.notifications import notificar_estoque_baixo


def fabrica_da_conta(conta_id):
    """A fabrica ativa desta empresa, ou None."""
    return (
        Loja.objects.filter(
            conta_id=conta_id, tipo=Loja.Tipo.FABRICA, ativo=True, is_deleted=False
        )
        .order_by("id")
        .first()
    )


def segue_fluxo_fabrica(produto):
    """True se pedidos novos deste produto seguem o fluxo das caixas.

    A segunda condicao e o interruptor de implantacao: a migracao ja marca os
    salgados como vem_da_fabrica, e nada muda na operacao ate alguem
    cadastrar a fabrica.
    """
    return bool(produto.vem_da_fabrica) and fabrica_da_conta(produto.conta_id) is not None


def conferir_fabrica_unica(conta_id, tipo, ativo, loja=None):
    """Recusa uma segunda fabrica ativa na mesma empresa.

    Na aplicacao, e nao no banco: o MySQL nao aplica UniqueConstraint com
    condition (o Django so avisa, W036). A trava na linha da Conta faz dois
    cadastros simultaneos passarem aqui um de cada vez — por isso quem chama
    precisa estar dentro de transaction.atomic().
    """
    if tipo != Loja.Tipo.FABRICA or not ativo:
        return

    Conta.objects.select_for_update().filter(pk=conta_id).first()

    outras = Loja.objects.filter(
        conta_id=conta_id, tipo=Loja.Tipo.FABRICA, ativo=True, is_deleted=False
    )
    if loja is not None:
        outras = outras.exclude(pk=loja.pk)

    existente = outras.first()
    if existente:
        raise ValidationError(
            {"tipo": f"Esta empresa já tem uma fábrica: {existente.nome_loja}."}
        )


class ProducaoInvalida(Exception):
    """Producao que a regra nao aceita (ex.: produto que nao vem da fabrica)."""


@dataclass
class ResultadoDaImpressao:
    impressos: list = field(default_factory=list)
    recusados: list = field(default_factory=list)


def gerar_codigo_caixa():
    """12 caracteres aleatorios para o QR (ver Caixa.codigo)."""
    return secrets.token_urlsafe(9)


def _caixas(quantidade):
    return "caixa" if quantidade == 1 else "caixas"


def caixas_a_caminho(fabrica, produto_ids):
    """Caixas impressas e ainda nao lidas, por produto.

    Continuam no estoque da fabrica (so saem ao ser lidas na loja), entao o
    disponivel para imprimir e o estoque menos elas.
    """
    linhas = (
        Caixa.objects.filter(
            situacao=Caixa.Situacao.A_CAMINHO,
            pedido__da_fabrica=True,
            pedido__loja__conta_id=fabrica.conta_id,
            pedido__itens__produto_id__in=list(produto_ids),
        )
        .values("pedido__itens__produto_id")
        .annotate(total=Count("id"))
    )
    return {linha["pedido__itens__produto_id"]: linha["total"] for linha in linhas}


def disponivel_por_produto(fabrica):
    estoques = list(
        Estoque.objects.filter(loja=fabrica)
        .select_related("produto")
        .order_by("produto__nome_produto")
    )
    a_caminho = caixas_a_caminho(fabrica, [estoque.produto_id for estoque in estoques])

    resultado = []
    for estoque in estoques:
        caminho = a_caminho.get(estoque.produto_id, 0)
        resultado.append({
            "produto": str(estoque.produto.public_id),
            "produto_nome": estoque.produto.nome_produto,
            "estoque": estoque.quantidade_atual,
            "a_caminho": caminho,
            "disponivel": max(estoque.quantidade_atual - caminho, 0),
        })
    return resultado


def registrar_producao(fabrica, produto, caixas, usuario):
    """A fabrica produziu: soma no estoque dela e deixa o rastro (ENTRADA).

    Nao e ajuste manual — e o trabalho normal da fabrica, por isso nao passa
    pela regra que tira do Responsavel a edicao de quantidade.
    """
    if produto.conta_id != fabrica.conta_id or not produto.vem_da_fabrica:
        raise ProducaoInvalida("Esse produto não vem da fábrica.")

    with transaction.atomic():
        estoque, _ = Estoque.objects.select_for_update().get_or_create(
            loja=fabrica,
            produto=produto,
            defaults={
                "quantidade_atual": 0,
                "quantidade_minima": produto.estoque_minimo_sugerido,
                # Mesmo piso de somar_itens_no_estoque: o banco exige maximo > minimo.
                "quantidade_maxima": max(
                    produto.estoque_maximo_sugerido,
                    produto.estoque_minimo_sugerido + 1,
                ),
            },
        )
        estoque.quantidade_atual += caixas
        estoque.save(update_fields=["quantidade_atual", "updated_at"])
        MovimentacaoEstoque.objects.create(
            tipo=MovimentacaoEstoque.Tipo.ENTRADA,
            produto=produto,
            loja_destino=fabrica,
            quantidade=caixas,
            usuario=usuario,
        )
        notificar_estoque_baixo(estoque, usuario_editor=usuario)

    return estoque


def _recusa(pedido_id, numero, motivo, faltam=None):
    return {"pedido": str(pedido_id), "numero": numero, "motivo": motivo, "faltam": faltam}


def imprimir_etiquetas(fabrica, pedido_ids):
    """Cria as caixas dos pedidos escolhidos e muda eles para EM_ENTREGA.

    Pedido sem estoque disponivel fica PENDENTE e volta em `recusados`; os
    outros imprimem normalmente.

    Duas travas: nos pedidos (dois cliques nao criam caixas em dobro) e nas
    linhas de estoque da fabrica (dois pedidos do mesmo produto nao passam
    juntos pela conta do disponivel). Ordenadas por id para nao dar deadlock.
    """
    resultado = ResultadoDaImpressao()
    pedido_ids = [str(pedido_id) for pedido_id in pedido_ids]

    with transaction.atomic():
        pedidos = list(
            Pedido.objects.select_for_update()
            .filter(public_id__in=pedido_ids, loja__conta_id=fabrica.conta_id)
            .order_by("id")
        )
        encontrados = {str(pedido.public_id) for pedido in pedidos}
        for pedido_id in pedido_ids:
            if pedido_id not in encontrados:
                resultado.recusados.append(_recusa(pedido_id, None, "Pedido não encontrado."))

        candidatos = []
        for pedido in pedidos:
            if not pedido.da_fabrica:
                resultado.recusados.append(_recusa(pedido.public_id, pedido.id, "Não é pedido da fábrica."))
            elif pedido.status == Pedido.Status.EM_ENTREGA:
                resultado.recusados.append(_recusa(pedido.public_id, pedido.id, "Já impresso, use Reimprimir."))
            elif pedido.status != Pedido.Status.PENDENTE:
                resultado.recusados.append(_recusa(pedido.public_id, pedido.id, "Pedido não está pendente."))
            else:
                candidatos.append(pedido)

        itens = {
            item.pedido_id: item
            for item in ItemPedido.objects.filter(pedido__in=candidatos).select_related("produto")
        }
        produto_ids = sorted({item.produto_id for item in itens.values()})
        estoques = {
            estoque.produto_id: estoque
            for estoque in Estoque.objects.select_for_update()
            .filter(loja=fabrica, produto_id__in=produto_ids)
            .order_by("id")
        }
        a_caminho = caixas_a_caminho(fabrica, produto_ids)

        for pedido in candidatos:
            item = itens[pedido.id]
            estoque = estoques.get(item.produto_id)
            disponivel = (estoque.quantidade_atual if estoque else 0) - a_caminho.get(item.produto_id, 0)

            if item.quantidade > disponivel:
                faltam = item.quantidade - max(disponivel, 0)
                resultado.recusados.append(_recusa(
                    pedido.public_id,
                    pedido.id,
                    f"Faltam {faltam} {_caixas(faltam)} de {item.produto.nome_produto} no estoque da fábrica.",
                    faltam,
                ))
                continue

            Caixa.objects.bulk_create([
                Caixa(pedido=pedido, numero=numero, codigo=gerar_codigo_caixa())
                for numero in range(1, item.quantidade + 1)
            ])
            a_caminho[item.produto_id] = a_caminho.get(item.produto_id, 0) + item.quantidade
            pedido.status = Pedido.Status.EM_ENTREGA
            pedido.save(update_fields=["status", "updated_at"])
            resultado.impressos.append(pedido)

    return resultado


def caixas_para_etiqueta(fabrica, pedido_ids):
    """Caixas A_CAMINHO destes pedidos, prontas para o PDF.

    So as a caminho: etiqueta de caixa ja lida nao tem mais o que fazer. E o
    que torna "reimprimir" seguro — gera de novo as mesmas etiquetas, sem
    criar caixa.
    """
    return list(
        Caixa.objects.filter(
            pedido__public_id__in=[str(pedido_id) for pedido_id in pedido_ids],
            pedido__da_fabrica=True,
            pedido__loja__conta_id=fabrica.conta_id,
            situacao=Caixa.Situacao.A_CAMINHO,
        )
        .select_related("pedido__loja")
        .prefetch_related("pedido__itens__produto")
        .order_by("pedido_id", "numero")
    )
