from django.db.models import Q
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from app.models import Estoque, Loja, MovimentacaoEstoque
from app.permissions import (
    IsGerenteOrAdministradorOrResponsavel,
    is_admin,
    is_gerente,
    is_gerente_ou_admin,
)
from ..serializers import (
    EstoqueBaixoSerializer,
    EstoqueCreateSerializer,
    EstoqueSerializer,
    EstoqueUpdateSerializer,
    MovimentacaoEstoqueSerializer,
)


# 🔹 ESTOQUE
# Nao usa ResponsavelOuAdminMixin: o escopo de Estoque e por loja
# (loja__responsavel), nao por campo responsavel proprio, e todos os
# metodos relevantes ja sao definidos localmente abaixo.
class EstoqueViewSet(viewsets.ModelViewSet):
    queryset = Estoque.objects.all()
    serializer_class = EstoqueSerializer
    permission_classes = [IsAuthenticated, IsGerenteOrAdministradorOrResponsavel]
    lookup_field = 'public_id'

    def get_serializer_class(self):
        if self.action == 'create':
            return EstoqueCreateSerializer
        if self.action in ['update', 'partial_update']:
            return EstoqueUpdateSerializer
        return EstoqueSerializer

    def get_queryset(self):
        user = self.request.user
        queryset = Estoque.objects.all()

        if is_admin(user):
            return queryset
        if is_gerente(user):
            return queryset.filter(loja__gerente=user)

        return queryset.filter(loja__responsavel=user)

    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @action(detail=False, methods=['get'], url_path='baixos')
    def baixos(self, request):
        """Produtos no/abaixo do minimo, no escopo do usuario.

        Gerente/admin ve todas as lojas (visao centralizada); responsavel ve
        so as dele — o escopo ja vem do get_queryset.
        """
        estoques = self.get_queryset().baixos()
        return Response(EstoqueBaixoSerializer(estoques, many=True).data)

    def _validar_loja_do_responsavel(self, user, loja):
        if is_admin(user):
            return
        if is_gerente(user):
            if not loja or loja.gerente_id != user.id:
                raise PermissionDenied("Voce so pode editar o estoque das suas lojas.")
            return

        if not loja or loja.responsavel_id != user.id:
            raise PermissionDenied("Voce so pode editar o estoque da sua loja.")

    def perform_create(self, serializer):
        self._validar_loja_do_responsavel(
            self.request.user,
            serializer.validated_data.get('loja')
        )
        serializer.save()

    def perform_update(self, serializer):
        loja = serializer.validated_data.get('loja', serializer.instance.loja)
        self._validar_loja_do_responsavel(self.request.user, loja)
        serializer.save()

    def perform_destroy(self, instance):
        self._validar_loja_do_responsavel(self.request.user, instance.loja)
        instance.delete()


# 🔹 MOVIMENTACAO DE ESTOQUE (historico auditavel, somente leitura)
class MovimentacaoEstoqueViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = MovimentacaoEstoqueSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'public_id'
    queryset = MovimentacaoEstoque.objects.none()  # so via get_queryset

    def get_queryset(self):
        qs = (
            MovimentacaoEstoque.objects
            .select_related('produto', 'loja_origem', 'loja_destino', 'usuario')
            .order_by('-created_at')
        )

        user = self.request.user
        if is_gerente(user) and not is_admin(user):
            minhas = Loja.objects.filter(gerente=user)
            qs = qs.filter(Q(loja_origem__in=minhas) | Q(loja_destino__in=minhas))
        elif not is_gerente_ou_admin(user):
            minhas = Loja.objects.filter(responsavel=user)
            qs = qs.filter(Q(loja_origem__in=minhas) | Q(loja_destino__in=minhas))

        tipo = self.request.query_params.get('tipo')
        if tipo:
            qs = qs.filter(tipo=tipo)
        return qs
