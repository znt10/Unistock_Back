from django.contrib import admin

from .models import  Categoria, Loja, Produto, Pedido, ItemPedido, Estoque, Notificacao


class RestringeGerenteAoGrupoMixin:
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # A API ja recusa (validate_gerente) um usuario que nao e do grupo
        # Gerente, mas o /admin do Django nao passa por ali — sem isto,
        # qualquer usuario aparecia no seletor e podia ser salvo como gerente.
        if db_field.name == "gerente":
            kwargs["queryset"] = db_field.related_model.objects.filter(
                groups__name="Gerente"
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class LojaAdmin(RestringeGerenteAoGrupoMixin, admin.ModelAdmin):
    pass


class CategoriaAdmin(RestringeGerenteAoGrupoMixin, admin.ModelAdmin):
    list_filter = ["gerente"]


class ProdutoAdmin(RestringeGerenteAoGrupoMixin, admin.ModelAdmin):
    list_filter = ["gerente", "categoria"]


admin.site.register(Loja, LojaAdmin)

admin.site.register(Categoria, CategoriaAdmin)

admin.site.register(Produto, ProdutoAdmin)

admin.site.register(Pedido)

admin.site.register(ItemPedido)
admin.site.register(Estoque)   
admin.site.register(Notificacao)

