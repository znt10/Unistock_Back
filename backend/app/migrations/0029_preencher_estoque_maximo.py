"""Preenche o teto das linhas que existiam antes do campo.

Usa a mesma regra que o sistema usa para criar linha nova (maximo_padrao), em
vez de um numero fixo: assim o dado antigo e o novo seguem a mesma logica, e
quem for ajustar loja a loja parte do mesmo lugar.
"""

from django.db import migrations

from app.models import maximo_padrao


def preencher(apps, schema_editor):
    Estoque = apps.get_model("app", "Estoque")
    Produto = apps.get_model("app", "Produto")

    ajustados = 0
    for estoque in Estoque.objects.filter(quantidade_maxima__isnull=True):
        estoque.quantidade_maxima = maximo_padrao(estoque.quantidade_minima)
        estoque.save(update_fields=["quantidade_maxima"])
        ajustados += 1

    # A sugestao do produto acompanha o minimo dele pelo mesmo criterio, senao
    # todo produto nasceria com o default 3 mesmo tendo minimo 10.
    for produto in Produto.objects.all():
        maximo = maximo_padrao(produto.estoque_minimo_sugerido)
        if produto.estoque_maximo_sugerido != maximo:
            produto.estoque_maximo_sugerido = maximo
            produto.save(update_fields=["estoque_maximo_sugerido"])

    if ajustados:
        print(f"\n  Estoques com teto definido: {ajustados}")


def reverter(apps, schema_editor):
    # A 0028 remove a coluna ao reverter; nao ha o que desfazer aqui.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0028_estoque_maximo'),
    ]

    operations = [
        migrations.RunPython(preencher, reverter),
    ]
