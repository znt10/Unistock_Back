import re

from django.contrib.auth.models import Group, User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as ErroDeValidacaoDjango
from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from app.models import Loja, PerfilUsuario
from app.permissions import is_gerente_ou_admin


def criar_acesso_da_loja(loja, senha=None):
    """Cria o login da loja (username = email da loja).

    Sem `senha`: o acesso nasce inativo e sem senha utilizavel, e so passa a
    valer quando a loja define a senha pelo link — o caminho padrao.

    Com `senha`: o gerente/admin ja digitou a senha na tela de editar (pra
    agilizar cadastro de varias lojas sem esperar o email). O acesso nasce
    ativo e USAVEL na hora, e o email de "defina sua senha" NAO e mandado —
    mandar um link pra trocar algo que ja foi definido so confundiria a loja.

    Sem email cadastrado, a loja fica sem acesso nos dois casos.
    """
    if not loja.email:
        return None

    with transaction.atomic():
        acesso = User.objects.create(
            username=loja.email, email=loja.email, first_name=loja.nome_loja,
        )
        if senha:
            acesso.set_password(senha)
            acesso.is_active = True
        else:
            acesso.set_unusable_password()
            acesso.is_active = False
        acesso.save()

        grupo, _ = Group.objects.get_or_create(name="Responsavel")
        acesso.groups.add(grupo)

        # O acesso entra na empresa da loja. Sem isto ele logaria num sistema
        # vazio: o escopo pergunta a conta do usuario, e quem nao tem perfil
        # nao enxerga nada.
        PerfilUsuario.objects.get_or_create(
            user=acesso, defaults={"conta_id": loja.conta_id}
        )

        loja.responsavel = acesso
        loja.save(update_fields=["responsavel", "updated_at"])

    if not senha:
        from app.notifications.tasks import enviar_email_definir_senha

        # So depois do commit: se o worker pegar a task antes, nao acha o
        # usuario.
        transaction.on_commit(lambda: enviar_email_definir_senha.delay(acesso.id))

    return acesso


def definir_senha_do_acesso(acesso, senha):
    """Define a senha de um acesso QUE JA EXISTE e ativa a conta na hora.

    Mesmo caminho de `criar_acesso_da_loja(senha=...)`, para quando a loja ja
    tinha login e o gerente/admin esta trocando a senha direto, sem o link.
    """
    acesso.set_password(senha)
    acesso.is_active = True
    acesso.save(update_fields=["password", "is_active"])


class LojaSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    responsavel_nome = serializers.SerializerMethodField()
    # O acesso da loja e criado pelo sistema a partir do email — nao se escolhe
    # uma pessoa. Exposto so para leitura (mostra o email de acesso na tela).
    responsavel = serializers.PrimaryKeyRelatedField(read_only=True)
    email_acesso = serializers.EmailField(
        source="responsavel.email", read_only=True, default=None
    )
    # Mesma regra de Produto: a empresa vem de quem cria, nao do corpo.
    conta = serializers.SlugRelatedField(slug_field="nome", read_only=True)
    # Atalho de gerencia: digitar a senha aqui pula o link por email. Write-only
    # e nunca aparece em nenhuma resposta, nem a de quem acabou de manda-la.
    senha_acesso = serializers.CharField(
        write_only=True, required=False, allow_blank=True, style={"input_type": "password"}
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
            "conta",
            "ativo",
            "telefone_whatsapp",
            "email",
            "senha_acesso",
        ]

    def get_responsavel_nome(self, loja):
        """Nome de exibicao do acesso: o first_name e o nome da loja (setado na
        criacao do acesso). Cai pro email/username pra contas criadas antes
        disso, que nasceram sem first_name."""
        acesso = loja.responsavel
        if not acesso:
            return None
        return acesso.first_name or acesso.email or acesso.username

    def validate_senha_acesso(self, value):
        if not value:
            return value

        # E' um atalho de gerencia, nao um jeito da loja trocar a propria
        # senha — ela ja tem o fluxo normal de troca, logada. Sem isto,
        # qualquer um com permissao de PATCH na loja (inclusive o
        # responsavel dela) poderia resetar o proprio acesso por aqui.
        request = self.context.get("request")
        if not request or not is_gerente_ou_admin(request.user):
            raise PermissionDenied(
                "Apenas gerente ou admin pode definir a senha da loja."
            )

        try:
            validate_password(value)
        except ErroDeValidacaoDjango as erro:
            raise serializers.ValidationError(list(erro.messages))

        return value

    def _so_gerencia_muda(self, campo, value, mensagem):
        # Tipo e ativo decidem quem e a fabrica da empresa — e com isso quem
        # recebe os pedidos da fabrica e se o fluxo vale para todas as lojas.
        # O responsavel pode editar a propria loja, mas nao virar fabrica (nem
        # desligar a fabrica) por aqui. Reenviar o valor atual sem mudar passa:
        # o formulario de edicao manda o objeto inteiro.
        request = self.context.get("request")
        if request and is_gerente_ou_admin(request.user):
            return value
        if self.instance is not None and getattr(self.instance, campo) == value:
            return value
        raise PermissionDenied(mensagem)

    def validate_tipo(self, value):
        return self._so_gerencia_muda(
            "tipo", value, "Apenas gerente ou admin pode mudar o tipo da loja."
        )

    def validate_ativo(self, value):
        return self._so_gerencia_muda(
            "ativo", value, "Apenas gerente ou admin pode ativar ou desativar a loja."
        )

    def validate(self, data):
        senha = data.get("senha_acesso")
        if senha:
            email = data.get("email", getattr(self.instance, "email", None))
            if not email:
                raise serializers.ValidationError(
                    {"senha_acesso": "Cadastre um e-mail antes de definir a senha."}
                )

        return super().validate(data)

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
        senha = validated_data.pop("senha_acesso", None) or None
        loja = super().create(validated_data)
        criar_acesso_da_loja(loja, senha=senha)
        return loja

    @transaction.atomic
    def update(self, instance, validated_data):
        senha = validated_data.pop("senha_acesso", None) or None
        email_anterior = instance.email
        loja = super().update(instance, validated_data)

        if not loja.responsavel_id:
            # Loja com email e sem login. Duas historias caem aqui: a que nao
            # tinha email e passou a ter, e a que TINHA acesso e o perdeu —
            # Loja.responsavel e SET_NULL, entao apagar o usuario no /admin
            # deixa a loja assim, sem erro nenhum.
            #
            # Salvar o cadastro recria o acesso. Antes, so o email MUDAR
            # recriava: a loja que perdeu o login ficava num beco, e trocar o
            # email so para recuperar o acesso e contorno, nao caminho.
            criar_acesso_da_loja(loja, senha=senha)
            return loja

        if loja.email != email_anterior:
            # O login E o email da loja: se um muda, o outro acompanha, senao a
            # loja perde o acesso na primeira edicao de cadastro.
            acesso = loja.responsavel
            acesso.username = loja.email
            acesso.email = loja.email
            acesso.save(update_fields=["username", "email"])

        if senha:
            definir_senha_do_acesso(loja.responsavel, senha)

        return loja
