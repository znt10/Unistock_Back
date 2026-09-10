"""Teto de estoque por loja: `Estoque.quantidade_maxima`.

Nullable aqui; a 0029 preenche as linhas existentes e a 0030 fecha o campo com
a constraint `maxima > minima`. Tres passos porque o campo e obrigatorio e ja
existe dado no banco.

`Produto.estoque_maximo_sugerido` nasce com default e nao precisa da dança:
e so o valor de partida quando o sistema cria estoque sozinho.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0027_conta_obrigatoria_remove_gerente'),
    ]

    operations = [
        migrations.AddField(
            model_name='produto',
            name='estoque_maximo_sugerido',
            field=models.PositiveIntegerField(default=3),
        ),
        migrations.AddField(
            model_name='estoque',
            name='quantidade_maxima',
            field=models.PositiveIntegerField(null=True),
        ),
    ]
