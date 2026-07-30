# O acesso da loja passa a ser a propria loja: o login do responsavel vira o
# email da loja. E o mesmo usuario, entao o historico (Pedido.responsavel,
# MovimentacaoEstoque.usuario) continua intacto.
from django.db import migrations

from app.migracoes_loja_login import converter_responsaveis


def converter(apps, schema_editor):
    User = apps.get_model("auth", "User")
    Loja = apps.get_model("app", "Loja")

    convertidos, pulados = converter_responsaveis(User, Loja)
    print(f"\n  Lojas convertidas para login proprio: {convertidos}")
    for nome, motivo in pulados:
        print(f"  PULADA: {nome} — {motivo}")


def reverter(apps, schema_editor):
    # Sem volta: o email pessoal anterior nao fica guardado em lugar nenhum.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0016_remove_preferencianotificacao_digest_ativo_and_more"),
    ]

    operations = [
        migrations.RunPython(converter, reverter),
    ]
