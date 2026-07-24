import os

from celery import Celery

# Forca o valor certo (nao setdefault): uma variavel DJANGO_SETTINGS_MODULE
# perdida no ambiente (ex. "backend.backend.settings") quebraria o worker/beat,
# enquanto o wsgi.py da API ja forca. Mantem os dois consistentes.
os.environ["DJANGO_SETTINGS_MODULE"] = "backend.settings"

app = Celery("backend")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
