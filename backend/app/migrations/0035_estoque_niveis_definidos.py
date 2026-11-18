from django.db import migrations, models


def marcar_as_ja_mexidas(apps, schema_editor):
    """Linhas antigas: quem tem minimo/maximo diferente do sugerido do produto
    foi mexida por alguem; as que ainda estao no sugerido ficam com "?"."""
    Estoque = apps.get_model("app", "Estoque")
    for linha in Estoque.objects.select_related("produto").iterator():
        p = linha.produto
        teto_padrao = max(p.estoque_maximo_sugerido, p.estoque_minimo_sugerido + 1)
        no_sugerido = linha.quantidade_minima == p.estoque_minimo_sugerido and (
            linha.quantidade_maxima in (p.estoque_maximo_sugerido, teto_padrao)
        )
        if not no_sugerido:
            linha.niveis_definidos = True
            linha.save(update_fields=["niveis_definidos"])


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0034_toqueestoque'),
    ]

    operations = [
        migrations.AddField(
            model_name='estoque',
            name='niveis_definidos',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(marcar_as_ja_mexidas, migrations.RunPython.noop),
    ]
