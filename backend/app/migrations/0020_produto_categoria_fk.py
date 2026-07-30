import django.db.models.deletion
from django.db import migrations, models


CODIGO_PARA_NOME = {
    "SALGADOS_GDE": "Salgados grande",
    "SALGADOS_MINI": "Salgados mini",
    "ESFIHAS_GDE": "Esfihas grande",
    "ESFIHAS_MINI": "Esfihas mini",
    "FOGAZZAS_GDE": "Fogazzas grande",
    "FOGAZZAS_MINI": "Fogazzas mini",
    "RECHEIOS": "Recheios",
    "MERCADO": "Mercado",
}


def ligar_produtos_a_categoria(apps, schema_editor):
    Produto = apps.get_model("app", "Produto")
    Categoria = apps.get_model("app", "Categoria")

    for produto in Produto.objects.all():
        nome = CODIGO_PARA_NOME.get(produto.categoria, produto.categoria)
        categoria, _created = Categoria.objects.get_or_create(nome=nome)
        produto.categoria_fk = categoria
        produto.save(update_fields=["categoria_fk"])


def desligar_produtos_de_categoria(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0019_categoria"),
    ]

    operations = [
        migrations.AddField(
            model_name="produto",
            name="categoria_fk",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="produtos",
                to="app.categoria",
            ),
        ),
        migrations.RunPython(ligar_produtos_a_categoria, desligar_produtos_de_categoria),
    ]
