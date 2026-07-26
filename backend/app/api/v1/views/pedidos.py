from datetime import datetime, time

from django.utils.timezone import make_aware
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from app.models import ItemPedido, Pedido
from app.permissions import (
    IsGerenteOrAdministradorOrResponsavel,
    is_gerente_ou_admin,
)
from app.services.pedidos import TransicaoInvalida, mudar_status
from ..mixins import ResponsavelOuAdminMixin
from ..serializers import (
    ItemPedidoSerializer,
    PedidoCreateSerializer,
    PedidoSerializer,
    PedidoUpdateSerializer,
)


# 🔹 ITEM PEDIDO
class ItemPedidoViewSet(ResponsavelOuAdminMixin,viewsets.ModelViewSet):
    queryset = ItemPedido.objects.all()
    serializer_class = ItemPedidoSerializer
    permission_classes = [IsAuthenticated,IsGerenteOrAdministradorOrResponsavel]
    lookup_field = 'public_id'

    def get_queryset(self):
        user = self.request.user

        if is_gerente_ou_admin(user):
            return ItemPedido.objects.all()

        # Mesma regra de tenancy do PedidoViewSet: escopo pela loja do usuario
        return ItemPedido.objects.filter(pedido__loja__responsavel=user)



# 🔹 PEDIDO
class PedidoViewSet( viewsets.ModelViewSet):
    queryset = Pedido.objects.all().order_by('-data_pedido')
    serializer_class = PedidoSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'public_id'

    def get_serializer_class(self):
        if self.action == 'create':
            return PedidoCreateSerializer
        if self.action in ['update', 'partial_update']:
            return PedidoUpdateSerializer
        return PedidoSerializer

    def get_queryset(self):
        user = self.request.user
        queryset = Pedido.objects.all().order_by('-data_pedido')


        if not is_gerente_ou_admin(user):
            queryset = queryset.filter(loja__in=user.loja_set.all())

        status = self.request.query_params.get('status')
        data = self.request.query_params.get('data')
        loja = self.request.query_params.get('loja')

        if status:
            queryset = queryset.filter(status=status)

        if loja:
            queryset = queryset.filter(loja__public_id=loja)

        if data:
            data_inicio = make_aware(
                datetime.combine(
                    datetime.strptime(data, "%Y-%m-%d").date(),
                    time.min
                )
            )

            data_fim = make_aware(
                datetime.combine(
                    datetime.strptime(data, "%Y-%m-%d").date(),
                    time.max
                )
            )

            queryset = queryset.filter(
                data_pedido__range=(data_inicio, data_fim)
            )

        return queryset

    @action(detail=True, methods=['patch'], url_path='status')
    def atualizar_status(self, request, public_id=None):
        pedido = self.get_object()
        status_novo = request.data.get('status')

        status_validos = [choice[0] for choice in Pedido.Status.choices]
        if status_novo not in status_validos:
            return Response(
                {"status": f"Status inválido. Use: {', '.join(status_validos)}."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # A regra (quais transicoes valem, lock, soma no estoque) vive em
        # services/pedidos.py, que o bot tambem usa. Aqui so se traduz HTTP.
        try:
            pedido = mudar_status(
                pedido.pk, status_novo, usuario_editor=request.user
            )
        except TransicaoInvalida as erro:
            return Response(
                {"status": str(erro)}, status=status.HTTP_409_CONFLICT
            )

        return Response(self.get_serializer(pedido).data)
