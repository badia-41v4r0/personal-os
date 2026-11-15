#!/usr/bin/env bash
# Restaura la base del Control Center desde una copia de backup.py. No toca a Jarvis.
# Uso: control-center/deployment/restaurar.sh data/control-center/backups/AAAAMMDD-HHMMSS
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="${1:?Indica la carpeta de la copia}"
set -a; . "$ROOT/data/control-center/secrets.env"; set +a
if ls "$SRC"/*.enc >/dev/null 2>&1; then
  "$ROOT/control-center/backend/.venv/bin/python" "$ROOT/control-center/deployment/backup.py" --descifrar "$SRC"
fi
[ -f "$SRC/cc.db" ] || [ -f "$SRC/personal_os.dump" ] || { echo "No hay cc.db ni personal_os.dump en $SRC"; exit 1; }
cat "$SRC/LEEME.txt" 2>/dev/null || true
read -r -p "Se sustituirá la base actual del panel (se guarda antes una copia de seguridad). ¿Seguir? [s/N] " r
[[ "$r" =~ ^[sS]$ ]] || { echo "Cancelado."; exit 0; }
set -a; . "$ROOT/data/control-center/secrets.env"; set +a
"$ROOT/control-center/backend/.venv/bin/python" "$ROOT/control-center/deployment/backup.py" --dest "$ROOT/data/control-center/backups/antes-de-restaurar" --keep 5
systemctl --user stop jarvis-cc-backend
if [ -f "$SRC/personal_os.dump" ]; then
  docker exec -i pos-db pg_restore -U jarvis -d personal_os --clean --if-exists < "$SRC/personal_os.dump"
else
  rm -f "$ROOT/data/control-center/cc.db-wal" "$ROOT/data/control-center/cc.db-shm"
  install -m 600 "$SRC/cc.db" "$ROOT/data/control-center/cc.db"
fi
systemctl --user start jarvis-cc-backend   # aplica las migraciones pendientes al arrancar (ExecStartPre)
sleep 4
curl -sf http://127.0.0.1:8770/api/v1/health && echo && echo "Restaurado."
