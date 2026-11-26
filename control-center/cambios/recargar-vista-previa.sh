#!/usr/bin/env bash
# Lo ejecuta el Constructor (dentro de su encierro) para que la vista previa enseñe sus cambios:
# migra la base de la vista previa y recompila su web. El backend de la vista previa se recarga solo al cambiar el código.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
[ "${CC_VISTA_PREVIA:-}" = 1 ] || { echo "Solo para la vista previa del Constructor"; exit 1; }
cd "$ROOT/control-center/backend"
if ! git -C "$ROOT" diff --quiet HEAD -- uv.lock 2>/dev/null || [ ! -x .venv/bin/python ]; then uv sync --frozen; fi
.venv/bin/alembic upgrade head
cd "$ROOT/control-center/apps/web"
[ -d node_modules ] || npm ci --no-fund --no-audit --prefer-offline
NEXT_PUBLIC_BASE_PATH=/vista-previa CC_WEB_OUT=out-vista-previa npm run build
touch "$ROOT/control-center/backend/app/__init__.py"  # que el backend de la vista previa se recargue
echo "✓ Vista previa recargada: /vista-previa/"
