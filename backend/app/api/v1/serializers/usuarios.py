from django.contrib.auth.models import Group, User
from rest_framework import serializers


class UsuarioSerializer(serializers.ModelSerializer):
    tipo_usuario = serializers.ChoiceField(
        choices=["responsavel", "gerente"],
        write_only=True,
    )

    class Meta:
        model = User
        fields = ["id", "first_name", "email", "password", "tipo_usuario"]
        extra_kwargs = {"password": {"write_only": True}}

    def validate_password(self, value):
        if len(value) < 6:
            raise serializers.ValidationError(
                "A senha deve conter pelo menos 6 caracteres."
            )
        return value

    def validate_email(self, value):
        value = value.lower()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Este email ja esta em uso.")
        return value

    def create(self, validated_data):
        senha = validated_data.pop("password")
        email = validated_data.get("email")
        tipo_usuario = validated_data.pop("tipo_usuario")

        user = User(**validated_data)
        user.set_password(senha)
        user.username = email
        user.email = email
        user.save()

        if tipo_usuario == "gerente":
            grupo, _ = Group.objects.get_or_create(name="Gerente")
        else:
            grupo, _ = Group.objects.get_or_create(name="Responsavel")

        user.groups.add(grupo)

        return user
