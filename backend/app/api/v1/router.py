from django.urls import path
from rest_framework.routers import DefaultRouter
from .bot import BotCatalogoView, BotContatoView, BotPedidoConfirmarView, BotPedidoView
from .viewsets import EstoqueViewSet, LojaViewSet, PedidoViewSet, ItemPedidoViewSet, ProdutoViewSet, UsuarioViewSet, NotificacaoViewSet, VendaViewSet

router = DefaultRouter()
router.register(r'pedidos', PedidoViewSet)
router.register(r'itens-pedido', ItemPedidoViewSet)
router.register(r'produtos', ProdutoViewSet)
router.register(r'lojas', LojaViewSet)
router.register(r'estoque', EstoqueViewSet)
router.register(r'vendas', VendaViewSet, basename='vendas')
router.register(r'user', UsuarioViewSet)
router.register(r'notificacoes', NotificacaoViewSet, basename='notificacoes')

urlpatterns = router.urls + [
    path('bot/contato/', BotContatoView.as_view(), name='bot-contato'),
    path('bot/catalogo/', BotCatalogoView.as_view(), name='bot-catalogo'),
    path('bot/pedido/', BotPedidoView.as_view(), name='bot-pedido'),
    path('bot/pedido/<int:numero>/confirmar/', BotPedidoConfirmarView.as_view(), name='bot-pedido-confirmar'),
]
