from datetime import datetime, time

from django.db.models import Count, Q
from django.utils.timezone import make_aware
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from app.models import Caixa, ItemPedido, Pedido
from app.permissions import (
    IsGerenteOrAdministradorOrResponsavel,
    escopar_por_conta,
    fabrica_do_usuario,
    is_admin,
    is_gerente,
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

        if not is_admin(user) and not is_gerente(user):
            # Mesma regra de tenancy do PedidoViewSet: escopo pela loja do usuario
            return ItemPedido.objects.filter(pedido__loja__responsavel=user)

        return escopar_por_conta(
            ItemPedido.objects.all(), user, campo="pedido__loja__conta"
        )



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

        if is_admin(user) or is_gerente(user):
            queryset = escopar_por_conta(queryset, user, campo="loja__conta")
        else:
            fabrica = fabrica_do_usuario(user)
            if fabrica:
                # A fabrica ve o que tem que separar (pedidos da fabrica da
                # empresa dela) e os que ela mesma fez de outros produtos.
                queryset = queryset.filter(
                    Q(da_fabrica=True, loja__conta_id=fabrica.conta_id) | Q(loja=fabrica)
                )
            else:
                queryset = queryset.filter(loja__in=user.loja_set.all())

        queryset = queryset.select_related("loja", "responsavel").annotate(
            caixas_total_anotado=Count("caixas", distinct=True),
            caixas_chegaram_anotado=Count(
                "caixas",
                filter=~Q(caixas__situacao=Caixa.Situacao.A_CAMINHO),
                distinct=True,
            ),
        )

        status = self.request.query_params.get('status')
        data = self.request.query_params.get('data')
        loja = self.request.query_params.get('loja')
        da_fabrica = self.request.query_params.get('da_fabrica')

        if status:
            queryset = queryset.filter(status=status)

        if loja:
            queryset = queryset.filter(loja__public_id=loja)

        if da_fabrica in ('true', 'false'):
            queryset = queryset.filter(da_fabrica=(da_fabrica == 'true'))

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

    def _bloquear_fabrica_em_pedido_alheio(self, pedido):
        # A fabrica enxerga os pedidos das lojas para separar, nao para
        # cancelar ou editar: isso continua com a loja e a gerencia.
        fabrica = fabrica_do_usuario(self.request.user)
        if fabrica and pedido.loja_id != fabrica.id:
            raise PermissionDenied("A fábrica não altera pedidos das lojas.")

    def perform_update(self, serializer):
        self._bloquear_fabrica_em_pedido_alheio(serializer.instance)
        serializer.save()

    def perform_destroy(self, instance):
        self._bloquear_fabrica_em_pedido_alheio(instance)
        if instance.caixas.exists():
            # Caixa protege o pedido (PROTECT); sem isto sairia um 500 cru.
            raise PermissionDenied(
                "Pedido com etiquetas impressas não pode ser apagado. Peça à gerência para cancelar."
            )
        instance.delete()

    @action(detail=True, methods=['patch'], url_path='status')
    def atualizar_status(self, request, public_id=None):
        pedido = self.get_object()
        self._bloquear_fabrica_em_pedido_alheio(pedido)
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
