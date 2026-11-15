#!/usr/bin/env bash
# Arranque del contenedor: prepara Claude Code, instala el canal de Telegram
# y mantiene viva una sesión de Claude dentro de tmux (se relanza si se cae).
set -euo pipefail

CFG="$HOME/.claude.json"
CHANNEL="plugin:telegram@claude-plugins-official"

: "${CLAUDE_CODE_OAUTH_TOKEN:?Falta CLAUDE_CODE_OAUTH_TOKEN en .env}"
: "${TELEGRAM_BOT_TOKEN:?Falta TELEGRAM_BOT_TOKEN en .env}"

# Saltar el asistente de primer uso y marcar /workspace como carpeta de confianza
[ -f "$CFG" ] || echo '{}' > "$CFG"
tmp=$(mktemp)
jq '.hasCompletedOnboarding = true
    | .projects["/workspace"].hasTrustDialogAccepted = true' "$CFG" > "$tmp" && cat "$tmp" > "$CFG" && rm -f "$tmp"

# Plugin oficial de Telegram (solo la primera vez; queda guardado en data/home)
if ! claude plugin list 2>/dev/null | grep -q 'telegram@claude-plugins-official'; then
  claude plugin marketplace add https://github.com/anthropics/claude-plugins-official.git || true
  claude plugin install telegram@claude-plugins-official --scope user
fi

start_session() {
  tmux new-session -d -s jarvis -x 200 -y 50 \
    "claude --channels $CHANNEL; sleep 5"
}

echo "[jarvis] arrancando sesión"
while true; do
  tmux has-session -t jarvis 2>/dev/null || { echo "[jarvis] (re)lanzando Claude"; start_session; }
  sleep 30
done
