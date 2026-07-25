import re

from django.contrib.auth.models import Group, User
from rest_framework import serializers

from app.models import Loja


def criar_acesso_da_loja(loja):
    """Cria o login da loja (username = email da loja) e manda definir senha.

    O acesso nasce inativo e sem senha utilizavel: so passa a valer quando a
    loja define a senha pelo link. Sem email cadastrado, a loja fica sem acesso.
    """
    from app.notifications.tasks import enviar_email_definir_senha

    if not loja.email:
        return None

    acesso = User.objects.create(username=loja.email, email=loja.email)
    acesso.set_unusable_password()
    acesso.is_active = False
    acesso.save()

    grupo, _ = Group.objects.get_or_create(name="Responsavel")
    acesso.groups.add(grupo)

    loja.responsavel = acesso
    loja.save(update_fields=["responsavel", "updated_at"])

    enviar_email_definir_senha.delay(acesso.id)
    return acesso


class LojaSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    responsavel_nome = serializers.CharField(
        source="responsavel.first_name",
        read_only=True,
    )
    # O acesso da loja e criado pelo sistema a partir do email — nao se escolhe
    # uma pessoa. Exposto so para leitura (mostra o email de acesso na tela).
    responsavel = serializers.PrimaryKeyRelatedField(read_only=True)
    email_acesso = serializers.EmailField(
        source="responsavel.email", read_only=True
    )

    class Meta:
        model = Loja
        fields = [
            "id",
            "nome_loja",
            "tipo",
            "cidade",
            "endereco",
            "responsavel",
            "responsavel_nome",
            "email_acesso",
            "ativo",
            "telefone_whatsapp",
            "email",
        ]

    def validate_telefone_whatsapp(self, value):
        if not value:
            return None
        # Normaliza para apenas digitos (aceita +55 (83) 99999-8888).
        digitos = re.sub(r"\D", "", value)
        if len(digitos) < 10:
            raise serializers.ValidationError(
                "Informe o numero com DDD (minimo 10 digitos)."
            )
        return digitos

    def validate_email(self, value):
        """Email da loja e o login dela: precisa ser unico entre lojas."""
        if not value:
            return value

        outras = Loja.objects.filter(email=value)
        if self.instance:
            outras = outras.exclude(pk=self.instance.pk)
        if outras.exists():
            raise serializers.ValidationError(
                "Ja existe uma loja com este email."
            )
        return value

    def create(self, validated_data):
        loja = super().create(validated_data)
        criar_acesso_da_loja(loja)
        return loja
