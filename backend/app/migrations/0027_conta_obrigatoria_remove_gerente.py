"""Fecha a troca de dono: `conta` vira obrigatoria e `gerente` sai do banco.

Depois daqui nao existe mais dono-pessoa: quem enxerga o que se decide por
Conta (ver get_conta_do_usuario em permissions.py). O grupo "Gerente"
continua, como cargo.

A constraint de Categoria acompanha: duas empresas podem ter "Bebidas", mas
dentro da mesma empresa os dois gerentes veem a MESMA "Bebidas" — que e o
ponto de toda esta mudanca.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0026_adotar_linhas_em_contas'),
    ]

    operations = [
        # A constraint antiga referencia `gerente`: tem que cair antes do campo.
        migrations.RemoveConstraint(
            model_name='categoria',
            name='categoria_nome_unico_por_gerente',
        ),
        migrations.RemoveField(model_name='loja', name='gerente'),
        migrations.RemoveField(model_name='categoria', name='gerente'),
        migrations.RemoveField(model_name='produto', name='gerente'),
        migrations.AlterField(
            model_name='loja',
            name='conta',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='lojas', to='app.conta'),
        ),
        migrations.AlterField(
            model_name='categoria',
            name='conta',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='categorias', to='app.conta'),
        ),
        migrations.AlterField(
            model_name='produto',
            name='conta',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='produtos', to='app.conta'),
        ),
        migrations.AddConstraint(
            model_name='categoria',
            constraint=models.UniqueConstraint(fields=('nome', 'conta'), name='categoria_nome_unico_por_conta'),
        ),
    ]
