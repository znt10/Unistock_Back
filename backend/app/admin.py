from django.contrib import admin

from .models import (
    Categoria,
    Conta,
    Estoque,
    ItemPedido,
    Loja,
    Notificacao,
    Pedido,
    PerfilUsuario,
    Produto,
)
from .permissions import get_conta_do_usuario


class EscopoPorContaMixin:
    """Limita o /admin a conta de quem esta olhando.

    Antes disto qualquer is_staff enxergava as tres empresas juntas. O
    superuser continua vendo tudo — e o dono da plataforma; quem tem perfil ve
    so a propria conta; quem nao tem nem uma coisa nem outra nao ve nada.
    Mesma regra da API, tirada da mesma funcao, para as duas portas nao
    responderem coisas diferentes.
    """

    # O caminho da conta a partir deste model. Loja/Categoria/Produto tem a FK
    # direto; quem so alcanca via loja sobrescreve (ex.: "loja__conta").
    campo_da_conta = "conta"

    def get_queryset(self, request):
        queryset = super().get_queryset(request)

        if request.user.is_superuser:
            return queryset

        conta = get_conta_do_usuario(request.user)
        if not conta:
            return queryset.none()

        return queryset.filter(**{self.campo_da_conta: conta})


class PerfilUsuarioInline(admin.TabularInline):
    """Os membros da empresa, editaveis na propria tela dela.

    E a resposta visual pro caso que originou a Conta: colocar o segundo
    gerente numa empresa e adicionar uma linha aqui, nao mexer em cada loja e
    cada produto um por um.
    """

    model = PerfilUsuario
    extra = 1
    autocomplete_fields = ("user",)


@admin.register(Conta)
class ContaAdmin(admin.ModelAdmin):
    list_display = ("nome", "slug", "ativo")
    list_filter = ("ativo",)
    search_fields = ("nome", "slug")
    # O slug entra em URL e log; editar a mao quebraria link ja distribuido.
    readonly_fields = ("slug",)
    inlines = [PerfilUsuarioInline]


@admin.register(PerfilUsuario)
class PerfilUsuarioAdmin(admin.ModelAdmin):
    list_display = ("user", "conta")
    list_filter = ("conta",)
    search_fields = ("user__username", "user__email", "conta__nome")
    autocomplete_fields = ("user", "conta")
    list_select_related = ("user", "conta")


@admin.register(Loja)
class LojaAdmin(EscopoPorContaMixin, admin.ModelAdmin):
    list_display = ("nome_loja", "conta", "cidade", "ativo")
    list_filter = ("conta", "ativo")
    search_fields = ("nome_loja", "cidade")
    autocomplete_fields = ("conta",)
    list_select_related = ("conta",)


@admin.register(Categoria)
class CategoriaAdmin(EscopoPorContaMixin, admin.ModelAdmin):
    list_display = ("nome", "conta", "ordem")
    list_filter = ("conta",)
    search_fields = ("nome",)
    autocomplete_fields = ("conta",)
    list_select_related = ("conta",)


@admin.register(Produto)
class ProdutoAdmin(EscopoPorContaMixin, admin.ModelAdmin):
    list_display = ("nome_produto", "conta", "categoria")
    list_filter = ("conta", "categoria")
    search_fields = ("nome_produto",)
    autocomplete_fields = ("conta", "categoria")
    list_select_related = ("conta", "categoria")


@admin.register(Pedido)
class PedidoAdmin(EscopoPorContaMixin, admin.ModelAdmin):
    # Pedido nao tem FK de conta: a dele e a da loja. Uma fonte de verdade so.
    campo_da_conta = "loja__conta"
    list_display = ("id", "loja", "responsavel", "status", "data_pedido")
    list_filter = ("status",)
    list_select_related = ("loja", "responsavel")


@admin.register(Estoque)
class EstoqueAdmin(EscopoPorContaMixin, admin.ModelAdmin):
    campo_da_conta = "loja__conta"
    list_display = ("produto", "loja", "quantidade_atual", "quantidade_minima")
    list_select_related = ("produto", "loja")


admin.site.register(ItemPedido)
admin.site.register(Notificacao)
