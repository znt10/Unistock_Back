# O digest deixa de ser por usuario (a cada 15 min, horario escolhido por
# pessoa) e passa a ser por loja, num horario fixo: 7h, inicio do expediente.
from django.db import migrations

TASK_ANTIGA = "Disparar digests de estoque baixo"
TASK_NOVA = "Resumo diario de estoque baixo (7h)"
TASK_PATH = "app.notifications.tasks.enviar_digest_lojas"


def criar_agendamento_7h(apps, schema_editor):
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    PeriodicTask.objects.filter(name=TASK_ANTIGA).delete()

    crontab, _ = CrontabSchedule.objects.get_or_create(
        minute="0",
        hour="7",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
    )
    PeriodicTask.objects.update_or_create(
        name=TASK_NOVA,
        defaults={
            "task": TASK_PATH,
            "crontab": crontab,
            "interval": None,
            "enabled": True,
        },
    )


def reverter(apps, schema_editor):
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    PeriodicTask.objects.filter(name=TASK_NOVA).delete()

    intervalo, _ = IntervalSchedule.objects.get_or_create(every=15, period="minutes")
    PeriodicTask.objects.update_or_create(
        name=TASK_ANTIGA,
        defaults={
            "task": "app.notifications.tasks.disparar_digests",
            "interval": intervalo,
            "crontab": None,
            "enabled": True,
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0014_registrar_task_digest"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [
        migrations.RunPython(criar_agendamento_7h, reverter),
    ]
