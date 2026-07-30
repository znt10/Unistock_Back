"""Regra de negocio do pedido — fonte unica para o site e para o bot.

Mudar o status de um pedido MOVE ESTOQUE: virar ENTREGUE registra uma ENTRADA.
Por isso a regra nao pode morar na view. Duas superficies chegam ate ela hoje —
o site (PATCH /api/v1/pedidos/<public_id>/status/) e o bot de WhatsApp
(POST /api/v1/bot/pedido/<numero>/confirmar/) — e enquanto cada uma tinha a
propria copia elas divergiram: o bot recusava CANCELADO -> ENTREGUE, o site
aceitava e somava no estoque uma entrada que nunca chegou.

Antes desta extracao o bot importava `somar_itens_no_estoque` de dentro de
api/v1/viewsets.py, ou seja, um modulo de API dependia de outro modulo de API.
Agora as duas superficies dependem daqui, e daqui nao se importa nenhuma
delas.
"""

from django.db import transaction

from app.models import Estoque, MovimentacaoEstoque, Pedido
from app.notifications import (
    notificar_estoque_baixo,
    notificar_estoques_baixos_do_pedido,
)

# Para onde cada status pode ir. Tabela em vez de uma sequencia de ifs porque
# a guarda antiga olhava so ENTREGUE e deixava passar todo o resto — inclusive
# ressuscitar um pedido cancelado.
TRANSICOES = {
    Pedido.Status.PENDENTE: {Pedido.Status.ENTREGUE, Pedido.Status.CANCELADO},
    Pedido.Status.ENTREGUE: set(),
    Pedido.Status.CANCELADO: set(),
}


class TransicaoInvalida(Exception):
    """Transicao de status que a regra de negocio nao permite."""


def somar_itens_no_estoque(pedido):
    """Soma os itens do pedido no estoque da loja (pedido ENTREGUE).

    Cria a linha de Estoque se a loja ainda nao tinha aquele produto, e deixa
    o rastro em MovimentacaoEstoque para o historico bater com o saldo.
    """
    for item in pedido.itens.select_related('produto').all():
        estoque, _ = Estoque.objects.get_or_create(
            loja=pedido.loja,
            produto=item.produto,
            defaults={
                'quantidade_atual': 0,
                'quantidade_minima': item.produto.estoque_minimo_sugerido,
            }
        )
        estoque.quantidade_atual += item.quantidade
        estoque.save(update_fields=['quantidade_atual', 'updated_at'])
        MovimentacaoEstoque.objects.create(
            tipo=MovimentacaoEstoque.Tipo.ENTRADA,
            produto=item.produto,
            loja_destino=pedido.loja,
            quantidade=item.quantidade,
            usuario=pedido.responsavel,
        )
        notificar_estoque_baixo(estoque)


def mudar_status(pedido_id, status_novo, *, usuario_editor):
    """Aplica uma transicao de status. Devolve o pedido atualizado.

    Levanta TransicaoInvalida se a transicao nao estiver em TRANSICOES, e
    Pedido.DoesNotExist se o id nao existir — cabe a quem chama traduzir isso
    em resposta HTTP.

    Tudo roda em transaction.atomic() com o pedido travado por
    select_for_update(). O lock nao e opcional: sem ele, dois cliques no site
    (ou o bot repetindo a chamada depois de uma falha de rede) passavam os
    dois pela guarda e o estoque era somado em dobro.

    Repetir o status atual e no-op silencioso, nao erro: o retry do bot
    precisa ser seguro de fazer.
    """
    with transaction.atomic():
        pedido = Pedido.objects.select_for_update().get(pk=pedido_id)
        anterior = pedido.status

        if status_novo == anterior:
            return pedido

        if status_novo not in TRANSICOES[anterior]:
            raise TransicaoInvalida(
                f"Pedido {pedido.id} esta {anterior} e nao pode virar {status_novo}."
            )

        pedido.status = status_novo
        # Salva o status ANTES de mexer no estoque: na ordem inversa, um erro
        # no save deixaria o estoque ja somado e o pedido ainda pendente.
        pedido.save(update_fields=['status', 'updated_at'])

        if status_novo == Pedido.Status.ENTREGUE:
            somar_itens_no_estoque(pedido)

        notificar_estoques_baixos_do_pedido(pedido, usuario_editor=usuario_editor)

    return pedido
