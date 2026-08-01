from django.urls import path
from rest_framework.routers import DefaultRouter
from .bot import BotCatalogoView, BotContatoView, BotEstoqueRemoverView, BotPedidoConfirmarView, BotPedidoView, BotRelatorioView
from .whatsapp_webhook import EvolutionWebhookView
from .views import CategoriaViewSet, EstoqueViewSet, LojaViewSet, MovimentacaoEstoqueViewSet, PedidoViewSet, ItemPedidoViewSet, PreferenciaNotificacaoViewSet, ProdutoViewSet, UsuarioViewSet, NotificacaoViewSet, VendaViewSet

router = DefaultRouter()
router.register(r'pedidos', PedidoViewSet)
router.register(r'itens-pedido', ItemPedidoViewSet)
router.register(r'produtos', ProdutoViewSet)
router.register(r'categorias', CategoriaViewSet)
router.register(r'lojas', LojaViewSet)
router.register(r'estoque', EstoqueViewSet)
router.register(r'vendas', VendaViewSet, basename='vendas')
router.register(r'user', UsuarioViewSet)
router.register(r'notificacoes', NotificacaoViewSet, basename='notificacoes')
router.register(r'preferencias-notificacao', PreferenciaNotificacaoViewSet, basename='preferencias-notificacao')
router.register(r'movimentacoes', MovimentacaoEstoqueViewSet, basename='movimentacoes')

urlpatterns = router.urls + [
    path('bot/contato/', BotContatoView.as_view(), name='bot-contato'),
    path('bot/catalogo/', BotCatalogoView.as_view(), name='bot-catalogo'),
    path('bot/pedido/', BotPedidoView.as_view(), name='bot-pedido'),
    path('bot/pedido/<int:numero>/confirmar/', BotPedidoConfirmarView.as_view(), name='bot-pedido-confirmar'),
    path('bot/estoque/remover/', BotEstoqueRemoverView.as_view(), name='bot-estoque-remover'),
    path('bot/relatorio/', BotRelatorioView.as_view(), name='bot-relatorio'),
    path('bot/webhook/<str:token>/', EvolutionWebhookView.as_view(), name='bot-webhook'),
]
