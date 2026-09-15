"""Atalhos de cenario para os testes.

Depois da camada de Conta, quase todo teste precisa de uma empresa e de
usuarios vinculados a ela. Sem estes atalhos, cada setUp repetiria as mesmas
cinco linhas — e a chance de um deles esquecer o vinculo (e testar contra um
usuario que nao enxerga nada, achando que testou a regra) e alta.
"""

from django.contrib.auth.models import Group, User

from app.models import Categoria, Conta, ItemPedido, Loja, PerfilUsuario, Pedido, Produto


def criar_grupos():
    """Os tres papeis do sistema. Idempotente: pode chamar em todo setUp."""
    for nome in ("Admin", "Gerente", "Responsavel"):
        Group.objects.get_or_create(name=nome)


def criar_conta(nome="Empresa Teste"):
    return Conta.objects.create(nome=nome)


def criar_usuario(username, conta=None, grupo=None, senha="123456", **extras):
    """Usuario opcionalmente vinculado a uma conta e a um grupo.

    `conta=None` cria alguem sem empresa — que e exatamente o caso do Admin
    (ve tudo) e o do usuario orfao (nao ve nada). Os dois importam nos testes.
    """
    criar_grupos()
    user = User.objects.create_user(username=username, password=senha, **extras)

    if grupo:
        user.groups.add(Group.objects.get(name=grupo))
    if conta:
        PerfilUsuario.objects.create(user=user, conta=conta)

    return user


def criar_gerente(username, conta, **extras):
    return criar_usuario(username, conta=conta, grupo="Gerente", **extras)


def criar_admin(username="admin@x.com", **extras):
    """Admin nao tem conta de proposito: e o dono da plataforma."""
    return criar_usuario(username, grupo="Admin", **extras)


def criar_responsavel(username, conta, **extras):
    return criar_usuario(username, conta=conta, grupo="Responsavel", **extras)


def vincular(user, conta):
    """Poe um usuario ja existente dentro de uma empresa.

    Separado de criar_usuario para os testes que montam o User a mao (com
    email, first_name, senha especifica) e so precisam do vinculo.
    """
    return PerfilUsuario.objects.create(user=user, conta=conta)


def criar_loja(conta, nome="Lapa", **extras):
    """Loja comum com o proprio acesso (grupo Responsavel), como o cadastro faz."""
    username = f"{nome.lower().replace(' ', '-')}-{conta.pk}@x.com"
    acesso = criar_responsavel(username, conta)
    dados = {"cidade": "Patos", "endereco": "Rua 1", "responsavel": acesso}
    dados.update(extras)
    return Loja.objects.create(nome_loja=nome, conta=conta, **dados)


def criar_fabrica(conta, nome="Fabrica Central", **extras):
    return criar_loja(conta, nome, tipo=Loja.Tipo.FABRICA, **extras)


def criar_produto(conta, nome="Coxinha", categoria="Salgados grande", vem_da_fabrica=True, **extras):
    categoria_obj, _ = Categoria.objects.get_or_create(nome=categoria, conta=conta)
    return Produto.objects.create(
        nome_produto=nome,
        unidade_medida=Produto.UnidadeMedida.CAIXA,
        categoria=categoria_obj,
        conta=conta,
        vem_da_fabrica=vem_da_fabrica,
        **extras,
    )


def criar_pedido(loja, produto, quantidade=3, **extras):
    """Pedido de um produto so, direto no banco (sem passar pela API)."""
    pedido = Pedido.objects.create(responsavel=loja.responsavel, loja=loja, **extras)
    ItemPedido.objects.create(
        pedido=pedido, produto=produto, quantidade=quantidade, responsavel=loja.responsavel
    )
    return pedido
