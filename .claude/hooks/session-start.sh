#!/bin/bash
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# System libs for mysqlclient (build) and WeasyPrint (PDF rendering) — same
# packages the CI workflow installs (.github/workflows/ci.yml).
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
  libpango-1.0-0 libpangoft2-1.0-0 default-libmysqlclient-dev build-essential pkg-config

if [ ! -d .venv ]; then
  python3.12 -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip -q
pip install -q -r requirements.txt

# No DB_ENGINE -> settings.py falls back to SQLite (no MySQL needed locally).
# These three have no default in settings.py and are required for it to load.
cat >> "$CLAUDE_ENV_FILE" <<'EOF'
export SECRET_KEY="dev-session-secret-key-not-for-production"
export ALLOWED_HOSTS="localhost,127.0.0.1"
export CORS_ALLOWED_ORIGINS="http://localhost:3000"
export CSRF_TRUSTED_ORIGINS="http://localhost:3000"
export DEBUG="True"
EOF

echo "source $(pwd)/.venv/bin/activate" >> "$CLAUDE_ENV_FILE"
