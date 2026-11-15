#!/usr/bin/env bash
# Pasa una orden a Jarvis en el sistema bajo demanda. La sesión constante de tmux ya no existe.
# Uso: bin/jarvis-prompt.sh "orden"
set -euo pipefail
cd "$(dirname "$0")/.."
[ "${1:-}" = "--clear" ] && shift
exec bin/jarvis-run "$1"
