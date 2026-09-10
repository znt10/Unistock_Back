"""Atalhos de cenario para os testes.

Depois da camada de Conta, quase todo teste precisa de uma empresa e de
usuarios vinculados a ela. Sem estes atalhos, cada setUp repetiria as mesmas
cinco linhas — e a chance de um deles esquecer o vinculo (e testar contra um
usuario que nao enxerga nada, achando que testou a regra) e alta.
"""

from django.contrib.auth.models import Group, User

from app.models import Conta, PerfilUsuario


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
