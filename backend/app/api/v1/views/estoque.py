from django.core.exceptions import ValidationError
from django.db.models import Q
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from app.models import Estoque, Loja, MovimentacaoEstoque, Produto
from app.permissions import (
    IsGerenteOrAdministradorOrResponsavel,
    escopar_por_conta,
    get_conta_do_usuario,
    is_admin,
    is_gerente,
    is_gerente_ou_admin,
)
from app.services.fabrica import segue_fluxo_fabrica
from app.services.toque_estoque import ToqueRecusado, desfazer_toque, itens_da_minha_loja, tocar as tocar_no_estoque
from ..serializers import (
    EstoqueBaixoSerializer,
    EstoqueCreateSerializer,
    EstoqueSerializer,
    EstoqueUpdateSerializer,
    MovimentacaoEstoqueSerializer,
)

MENSAGEM_ESTOQUE_DA_FABRICA = (
    "Esse produto é da fábrica: o estoque dele muda lendo as etiquetas das caixas."
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

        # O Responsavel continua vendo so a LOJA dele, nao a conta inteira:
        # ele opera um balcao, nao administra a empresa. Para os demais, o
        # escopo e a conta — Estoque chega nela pela loja, sem FK propria.
        if not is_admin(user) and not is_gerente(user):
            return Estoque.objects.filter(loja__responsavel=user)

        return escopar_por_conta(Estoque.objects.all(), user, campo="loja__conta")

    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @action(detail=False, methods=['get'], url_path='baixos')
    def baixos(self, request):
        """Produtos no/abaixo do minimo, no escopo do usuario.

        Admin ve todas as lojas; gerente ve so as suas; responsavel ve so a
        dele — o escopo ja vem do get_queryset.
        """
        estoques = self.get_queryset().baixos()
        return Response(EstoqueBaixoSerializer(estoques, many=True).data)

    @action(detail=False, methods=['get'], url_path='excedidos')
    def excedidos(self, request):
        """Produtos ACIMA do maximo, no mesmo escopo.

        O motivo de existir e validade, nao espaco: parado demais estraga. Sai
        pelo mesmo serializer da falta — a tela mostra as duas listas com as
        mesmas colunas, e quem le compara sem trocar de vocabulario.
        """
        estoques = self.get_queryset().excedidos()
        return Response(EstoqueBaixoSerializer(estoques, many=True).data)

    @action(detail=False, methods=['get'], url_path='minha-loja')
    def minha_loja(self, request):
        """Lista da tela do celular: Estoque da loja ou Producao do dia da fabrica."""
        loja = Loja.objects.filter(
            responsavel=request.user, ativo=True, is_deleted=False
        ).first()
        if loja is None:
            return Response(
                {'error': 'Você não tem uma loja para mexer no estoque.', 'codigo': 'sem_loja'},
                status=403,
            )
        return Response({
            'loja': {
                'id': str(loja.public_id),
                'nome': loja.nome_loja,
                'fabrica': loja.tipo == Loja.Tipo.FABRICA,
            },
            'itens': itens_da_minha_loja(loja),
        })

    @action(detail=False, methods=['post'], url_path='tocar')
    def tocar(self, request):
        """Toque de +1/-1 no celular. A regra mora em services/toque_estoque.py."""
        delta = request.data.get('delta')
        if isinstance(delta, bool) or delta not in (1, -1):
            return Response(
                {'error': 'O toque é +1 ou −1.', 'codigo': 'delta_invalido'}, status=400
            )
        try:
            loja = Loja.objects.get(
                public_id=request.data.get('loja'), is_deleted=False, ativo=True
            )
            produto = Produto.objects.get(public_id=request.data.get('produto'), is_deleted=False)
        except (Loja.DoesNotExist, Produto.DoesNotExist, ValidationError, ValueError):
            return Response(
                {'error': 'Loja ou produto não encontrado.', 'codigo': 'nao_encontrado'},
                status=404,
            )
        try:
            return Response(tocar_no_estoque(loja, produto, delta, request.user))
        except ToqueRecusado as erro:
            return Response(
                {'error': erro.mensagem, 'codigo': erro.codigo, **erro.extras},
                status=erro.status,
            )

    def _validar_loja_do_responsavel(self, user, loja):
        if is_admin(user):
            return
        if is_gerente(user):
            conta = get_conta_do_usuario(user)
            if not loja or not conta or loja.conta_id != conta.id:
                raise PermissionDenied("Voce so pode editar o estoque das suas lojas.")
            return

        if not loja or loja.responsavel_id != user.id:
            raise PermissionDenied("Voce so pode editar o estoque da sua loja.")

    def _validar_quantidade_de_produto_da_fabrica(self, user, produto, nova, anterior):
        """Responsavel nao mexe na QUANTIDADE de produto que segue as caixas.

        So a quantidade: minimo, maximo e estado nao desencontram o numero de
        caixas do estoque. A gerencia continua podendo corrigir.
        """
        if is_gerente_ou_admin(user):
            return
        if nova is None or nova == anterior:
            return
        if segue_fluxo_fabrica(produto):
            raise PermissionDenied(MENSAGEM_ESTOQUE_DA_FABRICA)

    def perform_create(self, serializer):
        self._validar_loja_do_responsavel(
            self.request.user,
            serializer.validated_data.get('loja')
        )
        self._validar_quantidade_de_produto_da_fabrica(
            self.request.user,
            serializer.validated_data['produto'],
            serializer.validated_data.get('quantidade_atual'),
            0,
        )
        serializer.save()

    def perform_update(self, serializer):
        loja = serializer.validated_data.get('loja', serializer.instance.loja)
        self._validar_loja_do_responsavel(self.request.user, loja)
        self._validar_quantidade_de_produto_da_fabrica(
            self.request.user,
            serializer.validated_data.get('produto', serializer.instance.produto),
            serializer.validated_data.get('quantidade_atual'),
            serializer.instance.quantidade_atual,
        )
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
        if not is_admin(user):
            # Movimentacao aponta para DUAS lojas (origem e destino), e uma
            # transferencia entre contas diferentes tem que aparecer para as
            # duas — por isso o OR, e nao um filtro unico de conta.
            if is_gerente(user):
                minhas = escopar_por_conta(Loja.objects.all(), user)
            else:
                minhas = Loja.objects.filter(responsavel=user)
            qs = qs.filter(Q(loja_origem__in=minhas) | Q(loja_destino__in=minhas))

        tipo = self.request.query_params.get('tipo')
        if tipo:
            qs = qs.filter(tipo=tipo)

        loja = self.request.query_params.get('loja')
        if loja:
            qs = qs.filter(
                Q(loja_origem__public_id=loja) | Q(loja_destino__public_id=loja)
            )

        return qs


class DesfazerToqueView(APIView):
    """POST /api/v1/toques/<id>/desfazer/ — volta um toque de +1/-1 (ate 10 min)."""

    permission_classes = [IsAuthenticated]

    def post(self, request, toque_id):
        try:
            return Response(desfazer_toque(toque_id, request.user))
        except ToqueRecusado as erro:
            return Response(
                {'error': erro.mensagem, 'codigo': erro.codigo, **erro.extras},
                status=erro.status,
            )
