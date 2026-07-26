import re

from django.contrib.auth.models import Group, User
from django.db import transaction
from rest_framework import serializers

from app.models import Loja


def criar_acesso_da_loja(loja):
    """Cria o login da loja (username = email da loja) e manda definir senha.

    O acesso nasce inativo e sem senha utilizavel: so passa a valer quando a
    loja define a senha pelo link. Sem email cadastrado, a loja fica sem acesso.
    """
    from django.db import transaction

    from app.notifications.tasks import enviar_email_definir_senha

    if not loja.email:
        return None

    with transaction.atomic():
        acesso = User.objects.create(username=loja.email, email=loja.email)
        acesso.set_unusable_password()
        acesso.is_active = False
        acesso.save()

        grupo, _ = Group.objects.get_or_create(name="Responsavel")
        acesso.groups.add(grupo)

        loja.responsavel = acesso
        loja.save(update_fields=["responsavel", "updated_at"])

    # So depois do commit: se o worker pegar a task antes, nao acha o usuario.
    transaction.on_commit(lambda: enviar_email_definir_senha.delay(acesso.id))
    return acesso


class LojaSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    responsavel_nome = serializers.SerializerMethodField()
    # O acesso da loja e criado pelo sistema a partir do email — nao se escolhe
    # uma pessoa. Exposto so para leitura (mostra o email de acesso na tela).
    responsavel = serializers.PrimaryKeyRelatedField(read_only=True)
    email_acesso = serializers.EmailField(
        source="responsavel.email", read_only=True, default=None
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

    def get_responsavel_nome(self, loja):
        """Nome de exibicao do acesso. A conta da loja nao tem first_name, entao
        cai pro email — melhor que uma coluna em branco na tela."""
        acesso = loja.responsavel
        if not acesso:
            return None
        return acesso.first_name or acesso.email or acesso.username

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
        """Email da loja e o login dela: unico entre lojas E entre usuarios.

        A constraint que estoura de verdade e auth_user.username. Checar so
        Loja.email deixaria passar um email ja registrado por uma pessoa (o
        cadastro publico e aberto), e a criacao da loja quebraria no meio.
        """
        if not value:
            # Sem email a loja fica sem acesso — mas se ela JA tem um login, o
            # username viraria vazio: aquela conta fica irrecuperavel (sem
            # endereco pra receber o link) e a proxima loja que limpar o email
            # colide no username vazio. Trocar por outro email continua valendo.
            if self.instance and self.instance.responsavel_id:
                raise serializers.ValidationError(
                    "Nao da para remover o e-mail de uma loja que ja tem acesso. "
                    "Troque por outro e-mail, ou desative a loja."
                )
            return value

        value = value.strip().lower()

        outras = Loja.objects.filter(email__iexact=value)
        if self.instance:
            outras = outras.exclude(pk=self.instance.pk)
        if outras.exists():
            raise serializers.ValidationError(
                "Ja existe uma loja com este email."
            )

        usuarios = User.objects.filter(username__iexact=value)
        if self.instance and self.instance.responsavel_id:
            usuarios = usuarios.exclude(pk=self.instance.responsavel_id)
        if usuarios.exists():
            raise serializers.ValidationError(
                "Este email ja esta em uso por uma conta do sistema."
            )

        return value

    # A loja e o acesso dela nascem juntos ou nao nascem: sem isso, um erro ao
    # criar o User deixava a Loja gravada sem acesso — e com o email ja tomado,
    # nem recadastrar dava.
    @transaction.atomic
    def create(self, validated_data):
        loja = super().create(validated_data)
        criar_acesso_da_loja(loja)
        return loja

    @transaction.atomic
    def update(self, instance, validated_data):
        email_anterior = instance.email
        loja = super().update(instance, validated_data)

        if loja.email == email_anterior:
            return loja

        if loja.responsavel_id:
            # O login E o email da loja: se um muda, o outro acompanha, senao a
            # loja perde o acesso na primeira edicao de cadastro.
            acesso = loja.responsavel
            acesso.username = loja.email
            acesso.email = loja.email
            acesso.save(update_fields=["username", "email"])
        else:
            # Loja que nao tinha email agora tem: ganha acesso.
            criar_acesso_da_loja(loja)

        return loja
