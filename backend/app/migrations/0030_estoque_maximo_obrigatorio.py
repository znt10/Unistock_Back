"""Fecha o teto: campo obrigatorio e `maxima > minima` garantido no banco.

A constraint fica no banco, e nao so no serializer, porque o bot de WhatsApp,
o PDV e o /admin escrevem estoque sem passar pela API.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0029_preencher_estoque_maximo'),
    ]

    operations = [
        migrations.AlterField(
            model_name='estoque',
            name='quantidade_maxima',
            field=models.PositiveIntegerField(),
        ),
        migrations.AddConstraint(
            model_name='estoque',
            constraint=models.CheckConstraint(
                condition=models.Q(quantidade_maxima__gt=models.F("quantidade_minima")),
                name='estoque_maximo_maior_que_minimo',
            ),
        ),
    ]
