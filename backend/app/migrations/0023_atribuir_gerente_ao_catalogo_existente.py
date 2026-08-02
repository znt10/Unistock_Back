from django.db import migrations


def atribuir_gerente(apps, schema_editor):
    """Categoria/Produto sem gerente ficam invisiveis pra qualquer Gerente
    depois desta mudanca (so Admin ve). Se so existe UM gerente no sistema,
    nao ha ambiguidade: todo catalogo existente e dele. Com zero ou mais de
    um gerente, nao ha como adivinhar o dono certo — fica sem gerente (nulo)
    para alguem atribuir manualmente depois.
    """
    User = apps.get_model("auth", "User")
    Categoria = apps.get_model("app", "Categoria")
    Produto = apps.get_model("app", "Produto")

    gerentes = User.objects.filter(groups__name="Gerente")
    if gerentes.count() != 1:
        return

    gerente = gerentes.first()
    Categoria.objects.filter(gerente__isnull=True).update(gerente=gerente)
    Produto.objects.filter(gerente__isnull=True).update(gerente=gerente)


def reverter(apps, schema_editor):
    # Nao ha como saber quais linhas eram nulas antes — reversao e um no-op
    # deliberado, nao um "voltar tudo pra nulo" que perderia dado bom.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0022_categoria_gerente_produto_gerente_and_more'),
    ]

    operations = [
        migrations.RunPython(atribuir_gerente, reverter),
    ]
