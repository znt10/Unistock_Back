"""Views da API v1, um modulo por dominio.

Reexporta todos os nomes para que router.py e os testes importem de
app.api.v1.views sem conhecer o modulo interno de cada viewset.
"""

# Reexport direto de app.permissions: tests/test_permissoes.py confere com
# assertIs que estes nomes sao os mesmos objetos de la.
from app.permissions import get_user_group_name, is_gerente_ou_admin
from .categorias import CategoriaViewSet
from .estoque import EstoqueViewSet, MovimentacaoEstoqueViewSet
from .lojas import LojaViewSet
from .notificacoes import NotificacaoViewSet, PreferenciaNotificacaoViewSet
from .pedidos import ItemPedidoViewSet, PedidoViewSet
from .produtos import ProdutoViewSet
from .usuarios import UsuarioViewSet
from .vendas import VendaViewSet

__all__ = [
    "CategoriaViewSet",
    "EstoqueViewSet",
    "ItemPedidoViewSet",
    "LojaViewSet",
    "MovimentacaoEstoqueViewSet",
    "NotificacaoViewSet",
    "PedidoViewSet",
    "PreferenciaNotificacaoViewSet",
    "ProdutoViewSet",
    "UsuarioViewSet",
    "VendaViewSet",
    "get_user_group_name",
    "is_gerente_ou_admin",
]
