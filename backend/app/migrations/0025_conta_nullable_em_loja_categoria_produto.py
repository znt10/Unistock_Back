"""Adiciona `conta` nullable nas tres tabelas que trocam de dono.

Nullable de proposito: as linhas que ja existem so ganham conta na 0026, e o
campo so vira obrigatorio na 0027. Fazer as tres coisas de uma vez impediria
a migracao de rodar em qualquer banco que ja tenha dados.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0024_conta_perfilusuario'),
    ]

    operations = [
        migrations.AddField(
            model_name='loja',
            name='conta',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='lojas', to='app.conta'),
        ),
        migrations.AddField(
            model_name='categoria',
            name='conta',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='categorias', to='app.conta'),
        ),
        migrations.AddField(
            model_name='produto',
            name='conta',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='produtos', to='app.conta'),
        ),
    ]
