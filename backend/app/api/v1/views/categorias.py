from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from app.models import Categoria
from app.permissions import IsGerenteOrAdministrador, escopar_por_conta
from ..serializers import CategoriaSerializer
from .conta import conta_do_request


class CategoriaViewSet(viewsets.ModelViewSet):
    queryset = Categoria.objects.all()
    serializer_class = CategoriaSerializer
    lookup_field = "public_id"

    def get_queryset(self):
        # O Responsavel nao precisa mais achar o dono do catalogo dando a
        # volta pela propria loja: ele e membro da conta como qualquer outro.
        return escopar_por_conta(Categoria.objects.all(), self.request.user)

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            # Catalogo interno; leitura exige login (mesma regra de Produto).
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsGerenteOrAdministrador()]

    def get_serializer_context(self):
        """Entrega a conta ao serializer para ele checar nome duplicado.

        So na criacao: na edicao a conta certa e a que a linha ja tem, e
        pedir a do request faria o Admin (que nao tem conta) comparar contra
        nada.
        """
        context = super().get_serializer_context()
        if self.request and self.action == "create":
            context["conta"] = conta_do_request(self.request)
        return context

    def perform_create(self, serializer):
        serializer.save(conta=self.get_serializer_context()["conta"])
