from django.contrib.auth.models import User
from django.db import models
from django.db.models import F

from app.models import Estoque, Notificacao, Pedido


def _gerencia_da_loja(loja):
    """Gerentes/admins que acompanham esta loja: os DA EMPRESA dela.

    Antes da camada de Conta isto pegava toda a gerencia do sistema, entao o
    estoque de uma empresa aparecia no sininho das outras. Superuser (dono da
    plataforma) nao tem conta e continua vendo tudo.
    """
    return User.objects.filter(
        groups__name__in=["Gerente", "Admin"], is_active=True
    ).filter(
        models.Q(perfil__conta_id=loja.conta_id) | models.Q(is_superuser=True)
    ).distinct()


def _destinatarios(estoque):
    usuarios = []
    if estoque.loja.responsavel:
        usuarios.append(estoque.loja.responsavel)
    usuarios.extend(_gerencia_da_loja(estoque.loja))
    return list({usuario.id: usuario for usuario in usuarios}.values())


def _publicar(usuarios, estoque, tipo, titulo, mensagem):
    """Uma notificacao por episodio, por usuario, deduplicada pela FK.

    Se ja existe, ATUALIZA a mensagem em vez de pular: o numero pode ter mudado
    e o alerta continuar valendo (3 -> 1 na falta, 100 -> 120 no excesso), e uma
    notificacao presa no numero antigo mente sobre o estado atual.
    """
    for usuario in usuarios:
        existente = Notificacao.objects.filter(
            usuario=usuario, tipo=tipo, estoque=estoque
        ).first()

        if existente:
            if existente.mensagem != mensagem:
                existente.mensagem = mensagem
                existente.lida = False  # numero mudou: volta a pedir atencao
                existente.save(update_fields=["mensagem", "lida", "updated_at"])
            continue

        Notificacao.objects.create(
            usuario=usuario,
            loja=estoque.loja,
            estoque=estoque,
            tipo=tipo,
            titulo=titulo,
            mensagem=mensagem,
        )


def notificar_estoque_excedido(estoque: Estoque, usuario_editor: User | None = None):
    """Alerta de excesso — o espelho de notificar_estoque_baixo.

    Existe por causa de validade, nao de espaco: produto parado demais estraga.
    Some sozinho quando o estoque volta para dentro do teto, igual ao alerta de
    falta, para o sininho nao ficar mentindo.
    """
    if estoque.quantidade_atual <= estoque.quantidade_maxima:
        Notificacao.objects.filter(tipo="estoque_excedido", estoque=estoque).delete()
        return

    usuarios = _destinatarios(estoque)
    if not usuarios:
        return

    _publicar(
        usuarios,
        estoque,
        tipo="estoque_excedido",
        titulo="Estoque acima do maximo",
        mensagem=(
            f"{estoque.produto.nome_produto} passou do maximo na loja "
            f"{estoque.loja.nome_loja}. Atual: {estoque.quantidade_atual}. "
            f"Maximo: {estoque.quantidade_maxima}."
        ),
    )


def notificar_estoque_baixo(estoque: Estoque, usuario_editor: User | None = None):
    if estoque.quantidade_minima <= 0:
        return

    if estoque.quantidade_atual > estoque.quantidade_minima:
        # Recuperou: apaga o alerta do episodio que acabou. Sair sem apagar
        # deixava o sininho mentindo — o EstoqueUpdateSerializer ate limpava,
        # mas somar_itens_no_estoque (pedido entregue, inclusive pelo bot) nao
        # passa por ele, entao justo o caminho que resolve a falta era o que
        # nao limpava.
        Notificacao.objects.filter(tipo="estoque_baixo", estoque=estoque).delete()
        return

    usuarios = _destinatarios(estoque)
    if not usuarios:
        return

    _publicar(
        usuarios,
        estoque,
        tipo="estoque_baixo",
        titulo="Estoque baixo",
        mensagem=(
            f"{estoque.produto.nome_produto} esta com estoque baixo na loja "
            f"{estoque.loja.nome_loja}. Atual: {estoque.quantidade_atual}. "
            f"Minimo: {estoque.quantidade_minima}."
        ),
    )

    # Sem email por produto: o alerta imediato e so in-app (sininho). O email
    # de estoque sai uma vez por dia, no digest das 7h (por loja).


def notificar_estoques_baixos_do_pedido(
    pedido: Pedido,
    usuario_editor: User | None = None,
):
    produtos = pedido.itens.values_list("produto_id", flat=True)
    estoques_baixos = (
        Estoque.objects.filter(
            loja=pedido.loja,
            produto_id__in=produtos,
            quantidade_minima__gt=0,
            quantidade_atual__lte=F("quantidade_minima"),
        )
        .select_related("loja__responsavel", "produto")
    )

    for estoque in estoques_baixos:
        notificar_estoque_baixo(estoque, usuario_editor=usuario_editor)
