"""Cria a camada de empresa: Conta e o vinculo do usuario com ela.

Primeira das quatro migracoes que trocam o dono do dado de "o usuario Gerente"
para "a empresa". Aqui so os modelos novos nascem; ninguem aponta pra eles
ainda. Ver 0025 (campo nullable), 0026 (adocao dos dados) e 0027 (obrigatorio
e remocao do gerente).
"""

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0023_atribuir_gerente_ao_catalogo_existente'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Conta',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('public_id', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_deleted', models.BooleanField(default=False)),
                ('nome', models.CharField(max_length=150)),
                ('slug', models.SlugField(blank=True, max_length=60, null=True, unique=True)),
                ('ativo', models.BooleanField(default=True)),
            ],
            options={'ordering': ['nome']},
        ),
        migrations.CreateModel(
            name='PerfilUsuario',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('public_id', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_deleted', models.BooleanField(default=False)),
                ('conta', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='membros', to='app.conta')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='perfil', to=settings.AUTH_USER_MODEL)),
            ],
            options={'abstract': False},
        ),
    ]
