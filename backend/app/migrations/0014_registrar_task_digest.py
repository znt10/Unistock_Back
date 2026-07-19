# Registra a task periodica do digest no django-celery-beat (DatabaseScheduler).
from django.db import migrations

TASK_NAME = "Disparar digests de estoque baixo"
TASK_PATH = "app.notifications.tasks.disparar_digests"


def criar_periodic_task(apps, schema_editor):
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    intervalo, _ = IntervalSchedule.objects.get_or_create(every=15, period="minutes")
    PeriodicTask.objects.update_or_create(
        name=TASK_NAME,
        defaults={"task": TASK_PATH, "interval": intervalo, "enabled": True},
    )


def remover_periodic_task(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name=TASK_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0013_preferencianotificacao_ultimo_digest_em"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [
        migrations.RunPython(criar_periodic_task, remover_periodic_task),
    ]
