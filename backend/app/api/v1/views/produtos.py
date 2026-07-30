from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from app.models import Produto
from app.permissions import IsGerenteOrAdministrador
from ..serializers import ProdutoSerializer


# 🔹 PRODUTO
class ProdutoViewSet(viewsets.ModelViewSet):
    queryset = Produto.objects.all().order_by('nome_produto')
    serializer_class = ProdutoSerializer
    lookup_field = 'public_id'

    def get_permissions(self):
        if self.action == 'list':
            # Catalogo interno; leitura exige login.
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsGerenteOrAdministrador()]
