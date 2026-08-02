from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from app.models import Categoria, Loja
from app.permissions import IsGerenteOrAdministrador, is_admin, is_gerente
from ..serializers import CategoriaSerializer


class CategoriaViewSet(viewsets.ModelViewSet):
    queryset = Categoria.objects.all()
    serializer_class = CategoriaSerializer
    lookup_field = "public_id"

    def get_queryset(self):
        user = self.request.user
        queryset = Categoria.objects.all()

        if is_admin(user):
            return queryset
        if is_gerente(user):
            return queryset.filter(gerente=user)

        # Responsavel: catalogo do gerente da propria loja, nao o de outra
        # empresa. Sem loja/gerente atribuido, nao ve nenhuma categoria.
        loja = Loja.objects.filter(responsavel=user).first()
        if not loja or not loja.gerente_id:
            return queryset.none()
        return queryset.filter(gerente_id=loja.gerente_id)

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            # Catalogo interno; leitura exige login (mesma regra de Produto).
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsGerenteOrAdministrador()]

    def perform_create(self, serializer):
        user = self.request.user
        if "gerente" in self.request.data and not is_admin(user):
            raise PermissionDenied("Apenas admin pode definir o gerente da categoria.")

        if is_gerente(user) and not is_admin(user) and "gerente" not in self.request.data:
            serializer.save(gerente=user)
            return

        serializer.save()

    def perform_update(self, serializer):
        if "gerente" in self.request.data:
            raise PermissionDenied(
                "O gerente da categoria e definido na criacao e nao pode ser alterado."
            )
        serializer.save()
