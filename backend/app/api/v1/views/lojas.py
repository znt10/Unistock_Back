from django.db.models import ProtectedError
from rest_framework import status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from app.models import Loja
from app.permissions import (
    IsGerenteOrAdministrador,
    IsGerenteOrAdministradorOrResponsavel,
    is_admin,
    is_gerente,
)
from ..serializers import LojaSerializer


# 🔹 LOJA
class LojaViewSet(viewsets.ModelViewSet):
    queryset = Loja.objects.all().order_by('id')
    serializer_class = LojaSerializer
    lookup_field = 'public_id'

    def get_queryset(self):
        user = self.request.user
        queryset = Loja.objects.all().order_by('id')

        if is_gerente(user) and not is_admin(user):
            return queryset.filter(gerente=user)

        # Admin e Responsavel mantem o comportamento atual (sem filtro aqui —
        # Responsavel e limitado por has_object_permission na escrita e pelo
        # front so mostrar a loja dele).
        return queryset

    def get_permissions(self):
        if self.action == 'list':
            # Dados de loja (endereco, responsavel) nao sao publicos.
            return [IsAuthenticated()]
        if self.action == 'create':
            # Criar loja e coisa de gerente/admin.
            return [IsAuthenticated(), IsGerenteOrAdministrador()]
        # Editar/apagar: gerente/admin, ou o responsavel na propria loja.
        return [IsAuthenticated(), IsGerenteOrAdministradorOrResponsavel()]

    def perform_create(self, serializer):
        user = self.request.user
        if "gerente" in self.request.data and not is_admin(user):
            raise PermissionDenied("Apenas admin pode definir o gerente da loja.")

        if is_gerente(user) and not is_admin(user) and "gerente" not in self.request.data:
            # Gerente que cria a loja vira o dono dela por padrao — sem isso
            # ele perderia acesso de escrita a propria loja logo em seguida.
            # Admin pode reatribuir depois pelo dashboard.
            serializer.save(gerente=user)
            return

        serializer.save()

    def perform_update(self, serializer):
        user = self.request.user
        if "gerente" in self.request.data and not is_admin(user):
            raise PermissionDenied("Apenas admin pode definir o gerente da loja.")
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        # MovimentacaoEstoque protege a loja (on_delete=PROTECT) pra nao perder
        # o historico auditavel. Sem isso, a exclusao estourava um 500 cru do
        # banco em vez de dizer o motivo.
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {
                    "error": (
                        "Esta loja tem historico de movimentacao de estoque e "
                        "nao pode ser excluida. Edite a loja e marque-a como "
                        "inativa em vez de exclui-la."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )
