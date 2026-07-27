from django.contrib import admin

from .models import  Categoria, Loja, Produto, Pedido, ItemPedido, Estoque, Notificacao

admin.site.register(Loja)

admin.site.register(Categoria)

admin.site.register(Produto)

admin.site.register(Pedido)

admin.site.register(ItemPedido)
admin.site.register(Estoque)   
admin.site.register(Notificacao)

