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

from app.models import Caixa, Estoque, LeituraCaixa, MovimentacaoEstoque, Pedido
from app.notifications import (
    notificar_estoque_baixo,
    notificar_estoques_baixos_do_pedido,
)
from app.permissions import is_gerente_ou_admin

# Para onde cada status pode ir. Tabela em vez de uma sequencia de ifs porque
# a guarda antiga olhava so ENTREGUE e deixava passar todo o resto — inclusive
# ressuscitar um pedido cancelado.
TRANSICOES = {
    Pedido.Status.PENDENTE: {Pedido.Status.ENTREGUE, Pedido.Status.CANCELADO},
    # PENDENTE -> EM_ENTREGA acontece ao imprimir as etiquetas, e
    # EM_ENTREGA -> ENTREGUE ao ler a ultima caixa: nenhuma das duas passa por
    # aqui. Por este caminho (site e bot), de EM_ENTREGA so se cancela.
    Pedido.Status.EM_ENTREGA: {Pedido.Status.CANCELADO},
    Pedido.Status.ENTREGUE: set(),
    Pedido.Status.CANCELADO: set(),
}

MENSAGEM_PEDIDO_DA_FABRICA = "Esse pedido é confirmado lendo as etiquetas das caixas no app."


class TransicaoInvalida(Exception):
    """Transicao de status que a regra de negocio nao permite."""


def _conferir_cancelamento_em_entrega(pedido, usuario):
    """Cancelar o que ja saiu da fabrica: so gerencia, e so sem caixa lida.

    Caixa lida ja moveu estoque. Cancelar por cima deixaria o estoque da loja
    com caixas de um pedido que "nao existe".
    """
    if not is_gerente_ou_admin(usuario):
        raise TransicaoInvalida("Só a gerência cancela um pedido que já saiu da fábrica.")
    if pedido.caixas.exclude(situacao=Caixa.Situacao.A_CAMINHO).exists():
        raise TransicaoInvalida(
            "Esse pedido já tem caixa lida na loja e não pode ser cancelado."
        )


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
                # A linha nasce com o teto sugerido do produto; quem sabe o
                # giro da loja ajusta depois na tela da loja. Nunca fica nula:
                # o banco exige maximo > minimo.
                'quantidade_maxima': max(
                    item.produto.estoque_maximo_sugerido,
                    item.produto.estoque_minimo_sugerido + 1,
                ),
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

        if pedido.da_fabrica and status_novo != Pedido.Status.CANCELADO:
            # Sem esta guarda, "confirmar" somava o pedido inteiro no estoque
            # por cima do que as leituras das caixas ja somaram.
            raise TransicaoInvalida(MENSAGEM_PEDIDO_DA_FABRICA)

        if status_novo not in TRANSICOES[anterior]:
            raise TransicaoInvalida(
                f"Pedido {pedido.id} esta {anterior} e nao pode virar {status_novo}."
            )

        if anterior == Pedido.Status.EM_ENTREGA:
            _conferir_cancelamento_em_entrega(pedido, usuario_editor)

        pedido.status = status_novo
        # Salva o status ANTES de mexer no estoque: na ordem inversa, um erro
        # no save deixaria o estoque ja somado e o pedido ainda pendente.
        pedido.save(update_fields=['status', 'updated_at'])

        if anterior == Pedido.Status.EM_ENTREGA:
            # So cancela sem caixa lida (ver _conferir_cancelamento_em_entrega),
            # entao toda LeituraCaixa destas caixas ja foi desfeita — apaga
            # antes para o PROTECT da FK nao barrar o delete das caixas.
            LeituraCaixa.objects.filter(caixa__pedido=pedido).delete()
            # Uma leitura de OUTRO pedido pode ter fechado uma caixa deste
            # pedido junto (caixa_fechada, tambem PROTECT); essas leituras
            # ja foram desfeitas por construcao (senao a caixa fechada nao
            # estaria A_CAMINHO e o cancelamento acima ja teria sido
            # recusado). Nao apaga: e historico do outro pedido, so solta a
            # referencia.
            LeituraCaixa.objects.filter(caixa_fechada__pedido=pedido).update(caixa_fechada=None)
            pedido.caixas.all().delete()

        if status_novo == Pedido.Status.ENTREGUE:
            somar_itens_no_estoque(pedido)

        notificar_estoques_baixos_do_pedido(pedido, usuario_editor=usuario_editor)

    return pedido
