#!/usr/bin/env bash
# 7:00: regenera el Panel; si ayer no se cerró, Jarvis lo cierra en automático; después, el briefing.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 collectors/build.py
ayer=$(date -d yesterday +%F)
orden="Lee /vault/Jarvis/Sistema/briefing.md y ejecútalo para hoy."
if [ -f "Jarvis-Vault/Jarvis/Sistema/panel-archivo/$ayer.md" ] && ! python3 collectors/estado_dia.py cerrado "$ayer"; then
  orden="Primero haz el cierre automático del día $ayer según /vault/Jarvis/Sistema/cierre.md, usando el Panel archivado /vault/Jarvis/Sistema/panel-archivo/$ayer.md y sin mensaje al usuario. Después, $orden"
fi
bin/jarvis-rutina briefing "$orden"
