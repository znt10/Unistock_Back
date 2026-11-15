from django.db.models import Count, Max
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from app.models import Caixa, Estoque, Pedido
from app.permissions import escopar_por_conta


def versao(queryset):
    """Contagem + ultimo updated_at: muda ao criar, editar e tambem ao apagar.

    So o updated_at nao bastaria, porque apagar uma linha nao mexe no maior
    updated_at das que sobram. Inclui as soft-deletadas de proposito (o
    soft_delete passa pelo save, entao muda o updated_at).
    """
    dados = queryset.aggregate(n=Count("id"), u=Max("updated_at"))
    ultimo = dados["u"].isoformat() if dados["u"] else ""
    return f"{dados['n']}:{ultimo}"


class MudancasView(APIView):
    """GET /api/v1/mudancas/ — o front consulta a cada 5s para atualizar ao vivo.

    A resposta e opaca: o front so compara com a anterior e, se um grupo
    mudou, recarrega as telas dele. A conta inteira, e nao so a loja do
    usuario: uma loja as vezes recarrega por mudanca de outra, o que e barato
    e mantem a regra igual para todos os papeis.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        pedidos = escopar_por_conta(Pedido.objects.all(), user, "loja__conta")
        caixas = escopar_por_conta(Caixa.objects.all(), user, "pedido__loja__conta")
        estoque = escopar_por_conta(Estoque.objects.all(), user, "loja__conta")

        return Response({
            # Ler uma caixa nem sempre mexe no Pedido, mas muda o
            # "chegaram 2 de 3" que as telas de pedido mostram.
            "pedidos": f"{versao(pedidos)}|{versao(caixas)}",
            "estoque": versao(estoque),
        })
