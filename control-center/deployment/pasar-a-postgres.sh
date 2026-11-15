#!/usr/bin/env bash
# Pasa el panel de SQLite a PostgreSQL. Idempotente hasta el cambio final; si algo falla, el panel vuelve a SQLite.
# cc.db nunca se modifica ni se borra: para volver atrás basta con quitar CC_DB_URL de secrets.env y reiniciar.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
D="$ROOT/data/control-center"
SECRETS="$D/secrets.env"
PY="$ROOT/control-center/backend/.venv/bin/python"
PORT=55433

grep -q '^CC_DB_URL=' "$SECRETS" && { echo "El panel ya usa PostgreSQL."; exit 0; }

if [ ! -f "$D/pg.env" ]; then
  PW=$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')
  (umask 077; printf 'POSTGRES_USER=jarvis\nPOSTGRES_DB=personal_os\nPOSTGRES_PASSWORD=%s\n' "$PW" > "$D/pg.env")
fi
PW=$(grep '^POSTGRES_PASSWORD=' "$D/pg.env" | cut -d= -f2-)
URL="postgresql+psycopg://jarvis:${PW}@127.0.0.1:${PORT}/personal_os"

mkdir -p -m 700 "$ROOT/data/postgres"
(cd "$ROOT" && docker compose --profile pos up -d pos-db)
for _ in $(seq 1 60); do
  docker exec pos-db pg_isready -q -U jarvis -d personal_os && break
  sleep 1
done
docker exec pos-db pg_isready -q -U jarvis -d personal_os || { echo "PostgreSQL no arranca"; exit 1; }
docker exec pos-db psql -q -U jarvis -d personal_os -c 'CREATE EXTENSION IF NOT EXISTS vector'

"$PY" "$ROOT/control-center/deployment/backup.py"
systemctl --user stop jarvis-cc-backend
volver() {
  echo "Falló: el panel sigue en SQLite." >&2
  sed -i '/^CC_DB_URL=/d' "$SECRETS"
  systemctl --user start jarvis-cc-backend
}
trap volver ERR

(cd "$ROOT/control-center/backend" && .venv/bin/alembic upgrade head)
CC_DB_URL="$URL" "$PY" "$ROOT/control-center/deployment/migrar_a_postgres.py"
echo "CC_DB_URL=$URL" >> "$SECRETS"
systemctl --user start jarvis-cc-backend
for _ in $(seq 1 30); do
  curl -sf http://127.0.0.1:8770/api/v1/health | grep -q '"database":"ok"' && { trap - ERR; echo "Panel en PostgreSQL."; exit 0; }
  sleep 1
done
false
