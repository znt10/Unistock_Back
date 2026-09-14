import unicodedata
import uuid

import django.db.models.deletion
from django.db import migrations, models

PREFIXOS_DA_FABRICA = ("salgados", "esfihas", "fogazzas")


def _sem_acento(texto):
    return (
        unicodedata.normalize("NFD", texto or "")
        .encode("ascii", "ignore")
        .decode()
        .strip()
        .lower()
    )


def normalizar_tipo_loja(apps, schema_editor):
    """Texto livre -> "Loja"/"Fabrica". Roda ANTES do campo virar NOT NULL."""
    Loja = apps.get_model("app", "Loja")
    for loja in Loja.objects.all().only("id", "tipo"):
        novo = "Fabrica" if _sem_acento(loja.tipo) == "fabrica" else "Loja"
        if loja.tipo != novo:
            Loja.objects.filter(pk=loja.pk).update(tipo=novo)


def marcar_produtos_da_fabrica(apps, schema_editor):
    """Salgados, esfihas e fogazzas comecam como vem_da_fabrica.

    Nao liga o fluxo das caixas: isso so acontece com a fabrica cadastrada.
    """
    Produto = apps.get_model("app", "Produto")
    for produto in Produto.objects.select_related("categoria"):
        if _sem_acento(produto.categoria.nome).startswith(PREFIXOS_DA_FABRICA):
            Produto.objects.filter(pk=produto.pk).update(vem_da_fabrica=True)


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0030_estoque_maximo_obrigatorio"),
    ]

    operations = [
        migrations.RunPython(normalizar_tipo_loja, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="loja",
            name="tipo",
            field=models.CharField(
                choices=[("Loja", "Loja"), ("Fabrica", "Fábrica")],
                default="Loja",
                max_length=50,
            ),
        ),
        migrations.AddField(
            model_name="produto",
            name="vem_da_fabrica",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(marcar_produtos_da_fabrica, migrations.RunPython.noop),
        migrations.AddField(
            model_name="pedido",
            name="da_fabrica",
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name="pedido",
            name="status",
            field=models.CharField(
                choices=[
                    ("PENDENTE", "Pendente"),
                    ("EM_ENTREGA", "Em entrega"),
                    ("ENTREGUE", "Entregue"),
                    ("CANCELADO", "Cancelado"),
                ],
                default="PENDENTE",
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name="Caixa",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("public_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_deleted", models.BooleanField(default=False)),
                ("numero", models.PositiveSmallIntegerField()),
                ("codigo", models.CharField(max_length=16, unique=True)),
                (
                    "situacao",
                    models.CharField(
                        choices=[
                            ("A_CAMINHO", "A caminho"),
                            ("CHEGOU", "Chegou"),
                            ("ABERTA", "Aberta"),
                            ("ACABOU", "Acabou"),
                        ],
                        default="A_CAMINHO",
                        max_length=10,
                    ),
                ),
                ("chegou_em", models.DateTimeField(blank=True, null=True)),
                ("aberta_em", models.DateTimeField(blank=True, null=True)),
                ("acabou_em", models.DateTimeField(blank=True, null=True)),
                (
                    "pedido",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="caixas",
                        to="app.pedido",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("pedido", "numero"), name="caixa_numero_unico_no_pedido"
                    )
                ],
            },
        ),
    ]
