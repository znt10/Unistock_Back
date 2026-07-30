from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from app.models import Notificacao, PreferenciaNotificacao
from ..serializers import (
    NotificacaoSerializer,
    PreferenciaNotificacaoSerializer,
)


# 🔹 NOTIFICACAO
class NotificacaoViewSet(viewsets.ModelViewSet):
    serializer_class = NotificacaoSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'public_id'

    def get_queryset(self):
        return Notificacao.objects.filter(
            usuario=self.request.user
        ).order_by('-created_at')

    def create(self, request, *args, **kwargs):
        return Response(
            {"detail": "Notificações são criadas automaticamente pelo sistema."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED
        )

    @action(detail=True, methods=['patch'], url_path='marcar-lida')
    def marcar_lida(self, request, public_id=None):
        notificacao = self.get_object()
        notificacao.lida = True
        notificacao.save(update_fields=['lida', 'updated_at'])
        return Response({"ok": True})

    @action(detail=False, methods=['patch'], url_path='todas-lidas')
    def todas_lidas(self, request):
        self.get_queryset().update(lida=True)
        return Response({"ok": True})

    @action(detail=False, methods=['delete'], url_path='limpar')
    def limpar(self, request):
        self.get_queryset().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# 🔹 PREFERENCIAS DE NOTIFICACAO
class PreferenciaNotificacaoViewSet(viewsets.GenericViewSet):
    """GET/PATCH /api/v1/preferencias-notificacao/me/ — sempre do proprio usuario."""

    serializer_class = PreferenciaNotificacaoSerializer
    permission_classes = [IsAuthenticated]
    queryset = PreferenciaNotificacao.objects.none()  # rota so via action `me`

    @action(detail=False, methods=['get', 'patch'], url_path='me')
    def me(self, request):
        prefs, _ = PreferenciaNotificacao.objects.get_or_create(usuario=request.user)

        if request.method.lower() == 'patch':
            serializer = self.get_serializer(prefs, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)

        return Response(self.get_serializer(prefs).data)
