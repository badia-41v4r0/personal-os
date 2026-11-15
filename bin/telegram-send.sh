#!/usr/bin/env bash
# Avisa al usuario sin pasar por el modelo (0 tokens): por el bot de Telegram y en la bandeja del panel (con push).
# Uso: [JARVIS_NIVEL=critical|action|info|silent] [JARVIS_URL=/ruta/] bin/telegram-send.sh "texto"
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Copia para el panel. Si esto falla, Telegram debe salir igual.
aviso_panel() {
  local carpeta="$DIR/data/control-center/avisos" tmp
  mkdir -p -m 700 "$carpeta"
  tmp=$(mktemp "$carpeta/.tmp.XXXXXX")
  jq -n --arg text "$1" --arg level "${JARVIS_NIVEL:-info}" --arg url "${JARVIS_URL:-/avisos/}" \
    '{text: $text, level: $level, url: $url}' > "$tmp"
  mv "$tmp" "$carpeta/$(date +%s%N)-$$.json"
}
aviso_panel "$1" || true

TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$DIR/.env" 2>/dev/null | cut -d= -f2- || true)
CHAT_ID=$(grep -E '^TELEGRAM_CHAT_ID=' "$DIR/.env" 2>/dev/null | cut -d= -f2- || true)
# Instalaciones antiguas: el chat emparejado con el plugin de Telegram
[ -n "$CHAT_ID" ] || CHAT_ID=$(jq -r '.allowFrom[0] // empty' "$DIR/data/home/.claude/channels/telegram/access.json" 2>/dev/null || true)
# Telegram es opcional: sin bot configurado, el aviso queda solo en el panel
[ -n "$TOKEN" ] && [ -n "$CHAT_ID" ] || exit 0
# La URL lleva el token: va por stdin para que no se vea en la lista de procesos
printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$TOKEN" | curl -sf -o /dev/null -K - \
  --data-urlencode "chat_id=${CHAT_ID}" --data-urlencode "text=$1"
