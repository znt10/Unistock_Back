"""Endpoints da fabrica: etiquetas, producao e disponivel.

A regra mora em services/fabrica.py; aqui so se resolve SOBRE QUAL fabrica o
usuario age e se traduz para HTTP.
"""

import uuid

from django.http import HttpResponse
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from app.models import Produto
from app.permissions import fabrica_do_usuario, get_conta_do_usuario, is_gerente
from app.relatorios.etiquetas_pdf import gerar_pdf_das_etiquetas
from app.services.fabrica import (
    ProducaoInvalida,
    caixas_para_etiqueta,
    disponivel_por_produto,
    fabrica_da_conta,
    imprimir_etiquetas,
    registrar_producao,
)


class FabricaAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def fabrica(self, request):
        """O acesso da fabrica age na propria; o gerente, na da empresa dele.

        Admin nao tem empresa, entao nao tem fabrica implicita.
        """
        fabrica = fabrica_do_usuario(request.user)
        if fabrica:
            return fabrica

        if is_gerente(request.user):
            conta = get_conta_do_usuario(request.user)
            fabrica = fabrica_da_conta(conta.id) if conta else None
            if fabrica:
                return fabrica
            raise PermissionDenied("Esta empresa não tem fábrica cadastrada.")

        raise PermissionDenied("Só a fábrica ou a gerência da empresa acessam a fábrica.")


class ImprimirEtiquetasSerializer(serializers.Serializer):
    pedidos = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False, max_length=200
    )


class ProducaoSerializer(serializers.Serializer):
    produto = serializers.UUIDField()
    caixas = serializers.IntegerField(min_value=1, max_value=10000)


class FabricaEtiquetasView(FabricaAPIView):
    """POST /api/v1/fabrica/etiquetas/ — cria as caixas dos pedidos escolhidos."""

    def post(self, request):
        fabrica = self.fabrica(request)
        entrada = ImprimirEtiquetasSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)

        resultado = imprimir_etiquetas(fabrica, entrada.validated_data["pedidos"])

        return Response({
            "impressos": [
                {"pedido": str(pedido.public_id), "numero": pedido.id, "caixas": pedido.caixas.count()}
                for pedido in resultado.impressos
            ],
            "recusados": resultado.recusados,
        })


class FabricaProducaoView(FabricaAPIView):
    """POST /api/v1/fabrica/producao/ — soma caixas produzidas no estoque da fabrica."""

    def post(self, request):
        fabrica = self.fabrica(request)
        entrada = ProducaoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)

        produto = Produto.objects.filter(
            public_id=entrada.validated_data["produto"],
            conta_id=fabrica.conta_id,
            is_deleted=False,
        ).first()
        if not produto:
            return Response({"error": "Produto não encontrado."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            estoque = registrar_producao(
                fabrica, produto, entrada.validated_data["caixas"], request.user
            )
        except ProducaoInvalida as erro:
            return Response({"error": str(erro)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "produto": str(produto.public_id),
                "produto_nome": produto.nome_produto,
                "quantidade_atual": estoque.quantidade_atual,
            },
            status=status.HTTP_201_CREATED,
        )


class FabricaDisponivelView(FabricaAPIView):
    """GET /api/v1/fabrica/disponivel/ — estoque, a caminho e disponivel por produto."""

    def get(self, request):
        return Response(disponivel_por_produto(self.fabrica(request)))


class FabricaEtiquetasPdfView(FabricaAPIView):
    """GET /api/v1/fabrica/etiquetas/pdf/?pedidos=<id>,<id> — imprimir e reimprimir."""

    def get(self, request):
        fabrica = self.fabrica(request)
        partes = [
            parte.strip()
            for parte in request.query_params.get("pedidos", "").split(",")
            if parte.strip()
        ]
        try:
            pedido_ids = [uuid.UUID(parte) for parte in partes]
        except ValueError:
            return Response({"error": "Pedido inválido."}, status=status.HTTP_400_BAD_REQUEST)

        caixas = caixas_para_etiqueta(fabrica, pedido_ids)
        if not caixas:
            return Response(
                {"error": "Nenhuma etiqueta para imprimir."}, status=status.HTTP_404_NOT_FOUND
            )

        resposta = HttpResponse(gerar_pdf_das_etiquetas(caixas), content_type="application/pdf")
        resposta["Content-Disposition"] = 'inline; filename="etiquetas.pdf"'
        return resposta
