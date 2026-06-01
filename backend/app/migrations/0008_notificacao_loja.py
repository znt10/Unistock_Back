from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0007_remove_produto_ativo_remove_produto_codigo"),
    ]

    operations = [
        migrations.AddField(
            model_name="notificacao",
            name="loja",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="notificacoes",
                to="app.loja",
            ),
        ),
    ]
