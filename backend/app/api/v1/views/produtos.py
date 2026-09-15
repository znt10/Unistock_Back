from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from app.models import Produto
from app.permissions import IsGerenteOrAdministrador, escopar_por_conta
from ..serializers import ProdutoSerializer
from .conta import conta_do_request


# 🔹 PRODUTO
class ProdutoViewSet(viewsets.ModelViewSet):
    queryset = Produto.objects.all().order_by('nome_produto')
    serializer_class = ProdutoSerializer
    lookup_field = 'public_id'

    def get_queryset(self):
        return escopar_por_conta(
            Produto.objects.all().order_by('nome_produto'), self.request.user
        )

    def get_permissions(self):
        if self.action == 'list':
            # Catalogo interno; leitura exige login.
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsGerenteOrAdministrador()]

    def perform_create(self, serializer):
        serializer.save(conta=conta_do_request(self.request))
