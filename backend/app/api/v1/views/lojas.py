from django.db import transaction
from django.db.models import ProtectedError
from rest_framework import status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from app.models import Loja
from app.permissions import (
    IsGerenteOrAdministrador,
    IsGerenteOrAdministradorOrResponsavel,
    escopar_por_conta,
)
from app.services.fabrica import conferir_fabrica_unica
from ..serializers import LojaSerializer
from .conta import conta_do_request


# 🔹 LOJA
class LojaViewSet(viewsets.ModelViewSet):
    queryset = Loja.objects.all().order_by('id')
    serializer_class = LojaSerializer
    lookup_field = 'public_id'

    def get_queryset(self):
        # Uma regra so para os tres papeis. Antes da camada de Conta, o
        # Responsavel recebia a lista inteira e o isolamento dependia do front
        # nao mostrar as outras lojas — agora ele ve as da conta dele, como
        # todo mundo.
        return escopar_por_conta(
            Loja.objects.all().order_by('id'), self.request.user
        )

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
        # A conta NUNCA vem do corpo do request: e sempre a de quem esta
        # logado. Isso apaga o par de guardas que existia aqui ("so admin
        # define o gerente" / "o gerente nao muda depois") e, junto com elas,
        # a chance de alguem criar loja na empresa de outro.
        conta = conta_do_request(self.request)
        dados = serializer.validated_data
        with transaction.atomic():
            conferir_fabrica_unica(
                conta.id, dados.get("tipo", Loja.Tipo.LOJA), dados.get("ativo", True)
            )
            serializer.save(conta=conta)

    def perform_update(self, serializer):
        loja = serializer.instance
        dados = serializer.validated_data
        with transaction.atomic():
            conferir_fabrica_unica(
                loja.conta_id,
                dados.get("tipo", loja.tipo),
                dados.get("ativo", loja.ativo),
                loja=loja,
            )
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
