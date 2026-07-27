import uuid

from django.db import migrations, models


CATEGORIAS_INICIAIS = [
    ("SALGADOS_GDE", "Salgados grande"),
    ("SALGADOS_MINI", "Salgados mini"),
    ("ESFIHAS_GDE", "Esfihas grande"),
    ("ESFIHAS_MINI", "Esfihas mini"),
    ("FOGAZZAS_GDE", "Fogazzas grande"),
    ("FOGAZZAS_MINI", "Fogazzas mini"),
    ("RECHEIOS", "Recheios"),
    ("MERCADO", "Mercado"),
]


def criar_categorias_iniciais(apps, schema_editor):
    Categoria = apps.get_model("app", "Categoria")
    for ordem, (_codigo, nome) in enumerate(CATEGORIAS_INICIAIS):
        Categoria.objects.get_or_create(nome=nome, defaults={"ordem": ordem})


def remover_categorias_iniciais(apps, schema_editor):
    Categoria = apps.get_model("app", "Categoria")
    nomes = [nome for _codigo, nome in CATEGORIAS_INICIAIS]
    Categoria.objects.filter(nome__in=nomes).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0018_loja_gerente"),
    ]

    operations = [
        migrations.CreateModel(
            name="Categoria",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("public_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_deleted", models.BooleanField(default=False)),
                ("nome", models.CharField(max_length=50, unique=True)),
                ("ordem", models.PositiveIntegerField(default=0)),
            ],
            options={
                "ordering": ["ordem", "nome"],
                "abstract": False,
            },
        ),
        migrations.RunPython(criar_categorias_iniciais, remover_categorias_iniciais),
    ]
