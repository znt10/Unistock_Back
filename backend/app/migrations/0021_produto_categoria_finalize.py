import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0020_produto_categoria_fk"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="produto",
            name="categoria",
        ),
        migrations.RenameField(
            model_name="produto",
            old_name="categoria_fk",
            new_name="categoria",
        ),
        migrations.AlterField(
            model_name="produto",
            name="categoria",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="produtos",
                to="app.categoria",
            ),
        ),
    ]
