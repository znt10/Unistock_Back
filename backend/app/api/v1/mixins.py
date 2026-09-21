from rest_framework.exceptions import PermissionDenied

from app.permissions import is_gerente_ou_admin


class ResponsavelOuAdminMixin:
    """Gerente/Admin agem em qualquer registro; os demais so no que e deles.

    Usa is_gerente_ou_admin de permissions.py. Antes havia aqui um `is_admin`
    proprio que contava o Gerente como admin — o mesmo nome do is_admin de
    permissions.py, que exclui o Gerente de proposito.
    """

    def get_queryset(self):
        user = self.request.user

        if is_gerente_ou_admin(user):
            return super().get_queryset()

        return super().get_queryset().filter(responsavel=user)

    def perform_update(self, serializer):
        user = self.request.user

        if not is_gerente_ou_admin(user):
            if serializer.instance.responsavel != user:
                raise PermissionDenied("Você só pode editar o que é seu")

        serializer.save()

    def perform_destroy(self, instance):
        user = self.request.user

        if not is_gerente_ou_admin(user):
            if instance.responsavel != user:
                raise PermissionDenied("Você só pode deletar o que é seu")

        instance.delete()
