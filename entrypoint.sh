#!/bin/sh
set -e

python manage.py migrate
# CSS/JS do /admin para o whitenoise servir (STATIC_ROOT).
python manage.py collectstatic --noinput
python manage.py loaddata groups || true
python manage.py ensure_admin || true

exec "$@"