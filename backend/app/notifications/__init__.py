from django.contrib.auth.models import User
from django.db.models import F

from app.models import Estoque, Notificacao, Pedido


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

    usuarios = []
    if estoque.loja.responsavel:
        usuarios.append(estoque.loja.responsavel)

    # Gerente/admin acompanha o estoque baixo de TODAS as lojas, tenha editado
    # ou nao: e a visao centralizada dele.
    usuarios.extend(
        User.objects.filter(
            groups__name__in=["Gerente", "Admin"], is_active=True
        ).distinct()
    )

    usuarios = list({usuario.id: usuario for usuario in usuarios}.values())
    if not usuarios:
        return

    titulo = "Estoque baixo"
    mensagem = (
        f"{estoque.produto.nome_produto} esta com estoque baixo na loja "
        f"{estoque.loja.nome_loja}. Atual: {estoque.quantidade_atual}. "
        f"Minimo: {estoque.quantidade_minima}."
    )

    for usuario in usuarios:
        # Uma notificacao por episodio de estoque baixo (lida ou nao); quando o
        # estoque recupera, o EstoqueUpdateSerializer apaga as do episodio e um
        # novo episodio volta a notificar. Dedup pela FK do estoque.
        #
        # Se ja existe, ATUALIZA a mensagem em vez de pular: o estoque pode ter
        # mudado e continuado baixo (3 -> 1), e uma notificacao presa no numero
        # antigo mente sobre o estado atual. Atualizar mantem uma so notificacao
        # (sem spam) com o valor certo.
        existente = Notificacao.objects.filter(
            usuario=usuario,
            tipo="estoque_baixo",
            estoque=estoque,
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
            tipo="estoque_baixo",
            titulo=titulo,
            mensagem=mensagem,
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
