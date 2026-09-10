"""Cria uma Conta por gerente existente e move as linhas dele para ela.

A logica fica em app/migracoes_conta.py para ser testavel — mesmo padrao do
migracoes_loja_login.py (0017). Aqui a migracao so entrega os models
historicos e imprime o resultado.
"""

from django.db import migrations

from app.migracoes_conta import adotar_linhas_em_contas


def adotar(apps, schema_editor):
    criadas, adotadas = adotar_linhas_em_contas(
        apps.get_model("auth", "User"),
        apps.get_model("app", "Conta"),
        apps.get_model("app", "PerfilUsuario"),
        apps.get_model("app", "Loja"),
        apps.get_model("app", "Categoria"),
        apps.get_model("app", "Produto"),
    )
    print(f"\n  Contas criadas: {criadas}; linhas adotadas: {adotadas}")


def reverter(apps, schema_editor):
    # A 0027 recria `gerente` vazio ao reverter, entao nao ha de onde tirar o
    # dono de volta. Apagar as contas seria destruir o unico registro do
    # vinculo — no-op deliberado, igual a reversao da 0023.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0025_conta_nullable_em_loja_categoria_produto'),
    ]

    operations = [
        migrations.RunPython(adotar, reverter),
    ]
