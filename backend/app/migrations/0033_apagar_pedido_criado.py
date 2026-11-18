from django.db import migrations


def apagar(apps, schema_editor):
    """O aviso "Pedido criado com sucesso" deixou de existir; some com os antigos."""
    apps.get_model("app", "Notificacao").objects.filter(tipo="pedido_criado").delete()


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0032_leituracaixa'),
    ]

    operations = [
        migrations.RunPython(apagar, migrations.RunPython.noop),
    ]
