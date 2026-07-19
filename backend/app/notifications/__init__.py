from django.contrib.auth.models import User
from django.db.models import F

from app.models import Estoque, Notificacao, Pedido


def _is_gerente_ou_admin(user):
    if not user or not user.is_authenticated:
        return False

    return (
        user.is_superuser
        or user.groups.filter(name="Admin").exists()
        or user.groups.filter(name="Gerente").exists()
    )


def notificar_estoque_baixo(estoque: Estoque, usuario_editor: User | None = None):
    if estoque.quantidade_minima <= 0:
        return

    if estoque.quantidade_atual > estoque.quantidade_minima:
        return

    usuarios = []
    if estoque.loja.responsavel:
        usuarios.append(estoque.loja.responsavel)

    if _is_gerente_ou_admin(usuario_editor):
        usuarios.append(usuario_editor)

    usuarios = list({usuario.id: usuario for usuario in usuarios}.values())
    if not usuarios:
        return

    titulo = "Estoque baixo"
    mensagem = (
        f"{estoque.produto.nome_produto} esta com estoque baixo na loja "
        f"{estoque.loja.nome_loja}. Atual: {estoque.quantidade_atual}. "
        f"Minimo: {estoque.quantidade_minima}."
    )

    notificados = []
    for usuario in usuarios:
        # Uma notificacao por episodio de estoque baixo (lida ou nao); quando o
        # estoque recupera, o EstoqueUpdateSerializer apaga as do episodio e um
        # novo episodio volta a notificar. Dedup pela FK do estoque.
        ja_existe = Notificacao.objects.filter(
            usuario=usuario,
            tipo="estoque_baixo",
            estoque=estoque,
        ).exists()

        if ja_existe:
            continue

        Notificacao.objects.create(
            usuario=usuario,
            loja=estoque.loja,
            estoque=estoque,
            tipo="estoque_baixo",
            titulo=titulo,
            mensagem=mensagem,
        )
        notificados.append(usuario.id)

    if notificados:
        # Email assincrono via Celery, so para quem ganhou notificacao nova.
        from app.notifications.tasks import enviar_alerta_estoque_baixo

        enviar_alerta_estoque_baixo.delay(estoque.id, notificados)


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
