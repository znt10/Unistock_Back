from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from app.models import Pedido
from ..serializers import PedidoSerializer, VendaCreateSerializer


class VendaViewSet(viewsets.GenericViewSet):
    queryset = Pedido.objects.all().order_by('-data_pedido')
    serializer_class = VendaCreateSerializer
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pedido = serializer.save()

        return Response(
            {
                "detail": "Venda finalizada com sucesso.",
                "pedido": PedidoSerializer(pedido).data,
            },
            status=status.HTTP_201_CREATED,
        )
