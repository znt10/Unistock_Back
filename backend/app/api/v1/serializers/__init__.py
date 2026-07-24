"""Serializers da API v1, organizados por dominio.

Este pacote substitui o antigo modulo unico serializers.py; todos os
nomes continuam importaveis de `app.api.v1.serializers`.
"""

from .estoque import (
    EstoqueCreateSerializer,
    EstoqueSerializer,
    EstoqueUpdateSerializer,
    EstoqueWriteSerializer,
)
from .lojas import LojaSerializer
from .movimentacoes import MovimentacaoEstoqueSerializer
from .notificacoes import NotificacaoSerializer
from .pedidos import (
    ItemPedidoSerializer,
    PedidoCreateSerializer,
    PedidoSerializer,
    PedidoUpdateSerializer,
    PedidoWriteSerializer,
)
from .preferencias import PreferenciaNotificacaoSerializer
from .produtos import ProdutoSerializer
from .usuarios import UsuarioSerializer
from .vendas import VendaCreateSerializer, VendaItemSerializer

__all__ = [
    "EstoqueCreateSerializer",
    "EstoqueSerializer",
    "EstoqueUpdateSerializer",
    "EstoqueWriteSerializer",
    "ItemPedidoSerializer",
    "LojaSerializer",
    "MovimentacaoEstoqueSerializer",
    "NotificacaoSerializer",
    "PedidoCreateSerializer",
    "PedidoSerializer",
    "PedidoUpdateSerializer",
    "PedidoWriteSerializer",
    "PreferenciaNotificacaoSerializer",
    "ProdutoSerializer",
    "UsuarioSerializer",
    "VendaCreateSerializer",
    "VendaItemSerializer",
]
