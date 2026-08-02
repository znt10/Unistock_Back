from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from app.models import Loja, Produto
from app.permissions import IsGerenteOrAdministrador, is_admin, is_gerente
from ..serializers import ProdutoSerializer


# 🔹 PRODUTO
class ProdutoViewSet(viewsets.ModelViewSet):
    queryset = Produto.objects.all().order_by('nome_produto')
    serializer_class = ProdutoSerializer
    lookup_field = 'public_id'

    def get_queryset(self):
        user = self.request.user
        queryset = Produto.objects.all().order_by('nome_produto')

        if is_admin(user):
            return queryset
        if is_gerente(user):
            return queryset.filter(gerente=user)

        # Responsavel: catalogo do gerente da propria loja, nao o de outra
        # empresa. Sem loja/gerente atribuido, nao ve nenhum produto.
        loja = Loja.objects.filter(responsavel=user).first()
        if not loja or not loja.gerente_id:
            return queryset.none()
        return queryset.filter(gerente_id=loja.gerente_id)

    def get_permissions(self):
        if self.action == 'list':
            # Catalogo interno; leitura exige login.
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsGerenteOrAdministrador()]

    def perform_create(self, serializer):
        user = self.request.user
        if "gerente" in self.request.data and not is_admin(user):
            raise PermissionDenied("Apenas admin pode definir o gerente do produto.")

        if is_gerente(user) and not is_admin(user) and "gerente" not in self.request.data:
            # Mesmo padrao de Loja: quem cria vira o dono, senao perderia
            # acesso de escrita ao proprio produto logo em seguida.
            serializer.save(gerente=user)
            return

        serializer.save()

    def perform_update(self, serializer):
        if "gerente" in self.request.data:
            raise PermissionDenied(
                "O gerente do produto e definido na criacao e nao pode ser alterado."
            )
        serializer.save()
