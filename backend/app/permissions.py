"""Regras de acesso do Unistock — fonte unica.

Quem pode o que se decide aqui, e em mais lugar nenhum. As classes DRF sao so
a interface para o framework: a regra em si sao as funcoes de modulo, para que
codigo fora de request (tasks do Celery, comandos, o bot) faca a mesma pergunta
sem inventar a propria resposta.

Antes disso a mesma regra vivia em tres copias (aqui, em api/v1/viewsets.py e
em notifications/__init__.py) e o papel do usuario em duas (aqui e em
views.py). Tres lugares para mudar quando a regra mudasse, e nada garantindo
que os tres mudassem juntos.
"""

from rest_framework.permissions import BasePermission, SAFE_METHODS

from app.models import Loja

# Quem enxerga todas as lojas.
GRUPOS_GERENCIA = ("Admin", "Gerente")


def is_admin(user):
    """True so para Admin de verdade (superuser ou grupo Admin) — sem Gerente.

    Diferenca de is_gerente_ou_admin: esta e para os pontos onde Gerente NAO
    pode agir como admin (criar outro gerente, ver todos os usuarios, mudar
    o gerente de uma loja).
    """
    if not user or not user.is_authenticated:
        return False

    return user.is_superuser or user.groups.filter(name="Admin").exists()


def is_gerente(user):
    """True se o usuario e Gerente (independente de ter lojas atribuidas)."""
    if not user or not user.is_authenticated:
        return False

    return user.groups.filter(name="Gerente").exists()


def is_gerente_ou_admin(user):
    """True se o usuario tem visao de todas as lojas.

    Aceita None e AnonymousUser: tambem e chamada fora de request (digest das
    7h), onde nao ha garantia de existir usuario.

    NAO olha is_active de proposito: quem barra conta desativada e o login.
    Mudar isso e decisao de produto, nao detalhe de implementacao.
    """
    return is_admin(user) or is_gerente(user)


def lojas_do_gerente(user):
    """Lojas que este Gerente administra (Loja.gerente=user). Admin: todas."""
    if is_admin(user):
        return Loja.objects.all()
    if is_gerente(user):
        return Loja.objects.filter(gerente=user)
    return Loja.objects.none()


def is_responsavel(user):
    """True se o usuario e o acesso de uma loja (ve so o que e dela)."""
    if not user or not user.is_authenticated:
        return False

    return user.groups.filter(name="Responsavel").exists()


def get_user_group_name(user):
    """Papel do usuario para a interface: Admin, Gerente, Responsavel ou None.

    Admin ganha de qualquer outro grupo. Para os demais o desempate e
    `groups.first()` SEM order_by, ou seja: quem esta em dois grupos recebe um
    papel que depende da ordem que o banco devolver. Comportamento antigo,
    mantido de proposito aqui — trocar por prioridade explicita muda o que a
    tela mostra para essas pessoas e precisa ser decidido, nao herdado.
    """
    if user.is_superuser or user.groups.filter(name="Admin").exists():
        return "Admin"

    group = user.groups.first()
    return group.name if group else None


class IsGerenteOrAdministrador(BasePermission):
    """Rotas exclusivas da gerencia (ex: relatorio global de pedidos)."""

    def has_permission(self, request, view):
        return is_gerente_ou_admin(request.user)


class IsGerenteOrAdministradorOrResponsavel(BasePermission):
    """NAO e a regra acima com um grupo a mais — e outra regra.

    Leitura: qualquer autenticado passa. O isolamento por loja na leitura vive
    no get_queryset de cada viewset, nao aqui; as duas pontas precisam ser
    lidas juntas.

    Escrita: Admin em qualquer loja; Gerente so nas lojas atribuidas a ele
    (Loja.gerente); responsavel so na propria.
    """

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        if request.method in SAFE_METHODS:
            return True

        return is_gerente_ou_admin(user) or is_responsavel(user)

    def has_object_permission(self, request, view, obj):
        user = request.user

        if request.method in SAFE_METHODS:
            return True

        if is_admin(user):
            return True

        if is_gerente(user):
            loja = obj if isinstance(obj, Loja) else getattr(obj, "loja", None)
            return loja is not None and loja.gerente_id == user.id

        if is_responsavel(user):
            # Objeto com FK de loja (Estoque, Pedido): tem que ser de uma loja
            # dele. Objeto sem essa FK (a propria Loja): tem que ser ele o
            # responsavel.
            if hasattr(obj, "loja"):
                return user.loja_set.filter(id=obj.loja_id).exists()

            return obj.responsavel == user

        return False
