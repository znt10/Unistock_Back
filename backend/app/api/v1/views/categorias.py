from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from app.models import Categoria
from app.permissions import IsGerenteOrAdministrador
from ..serializers import CategoriaSerializer


class CategoriaViewSet(viewsets.ModelViewSet):
    queryset = Categoria.objects.all()
    serializer_class = CategoriaSerializer
    lookup_field = "public_id"

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            # Catalogo interno; leitura exige login (mesma regra de Produto).
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsGerenteOrAdministrador()]
