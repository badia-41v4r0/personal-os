#!/usr/bin/env bash
# 22:30: si el día no está cerrado, recordatorio con el estado del Panel (0 tokens).
set -euo pipefail
cd "$(dirname "$0")/.."
# En modo runs el aviso lo da el panel (check-in de la noche, con push a las 22:30): aquí no se avisa dos veces.
[ "$(cat data/control-center/runtime 2>/dev/null || true)" = "runs" ] && exit 0
hoy=$(grep -m1 '^fecha:' Jarvis-Vault/Jarvis/Panel.md | awk '{print $2}')
if python3 collectors/estado_dia.py cerrado "$hoy"; then
  echo "Día $hoy ya cerrado"; exit 0
fi
JARVIS_URL=/ bin/telegram-send.sh "$(python3 collectors/estado_dia.py recordatorio)"
