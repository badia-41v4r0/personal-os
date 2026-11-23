#!/usr/bin/env bash
# Renovación de los permisos de Google (app en modo Prueba: caducan a los 7 días).
# Por cada cuenta cuyo token tenga 6 días o más, abre la pestaña de autorización en el navegador
# del PC (cuenta ya elegida) y avisa por Telegram. el usuario solo pulsa "Continuar". Espera hasta 12 h.
#   personal → secrets/gcal-token.json (calendario + Gmail) · secundaria → secrets/gmail-secundaria-token.json (solo Gmail)
set -euo pipefail
cd "$(dirname "$0")/.."
exec 9>/tmp/${POS_INSTANCE:-jarvis}-renovar-google.lock
flock -n 9 || exit 0
declare -A TOKENS=([personal]=secrets/gcal-token.json [secundaria]=secrets/gmail-secundaria-token.json)
declare -A NOMBRES=([personal]=" (calendario y Gmail)" [secundaria]=" (segunda cuenta de correo)")
# Tras un arranque, el timer atrasado corre antes de que Hyprland exporte WAYLAND_DISPLAY y
# xdg-open falla en silencio: espera a la sesión gráfica (hasta 1 h) y toma su entorno.
for _ in $(seq 360); do
  env_sesion=$(systemctl --user show-environment)
  grep -q '^WAYLAND_DISPLAY=' <<<"$env_sesion" && break
  sleep 10
done
while IFS='=' read -r k v; do
  case $k in WAYLAND_DISPLAY|DISPLAY|XDG_RUNTIME_DIR|DBUS_SESSION_BUS_ADDRESS|HYPRLAND_INSTANCE_SIGNATURE) export "$k=$v";; esac
done <<<"$env_sesion"
sleep 20  # margen para que el escritorio termine de arrancar
renovado=0
for cuenta in personal secundaria; do
  t=${TOKENS[$cuenta]}
  [ -f "$t" ] || continue
  edad=$(( ($(date +%s) - $(stat -c %Y "$t")) / 86400 ))
  [ "$edad" -ge 6 ] || { echo "$cuenta: token de $edad días, no toca"; continue; }
  JARVIS_NIVEL=action JARVIS_URL=/ajustes/conexiones/ bin/telegram-send.sh "🔑 Toca renovar el permiso de Google de ${NOMBRES[$cuenta]}. Te he abierto una pestaña en el navegador del PC (pulsa «Continuar») o, si no estás en casa, renuévalo desde Ajustes → Conexiones en el panel. Te espero hasta 12 h; si no, lo repito mañana." || true
  if python3 collectors/gcal.py auth --cuenta "$cuenta" --abrir --espera 12 >/dev/null; then
    bin/telegram-send.sh "✅ Permiso de ${NOMBRES[$cuenta]} renovado para 7 días más." || true
    renovado=1
  else
    echo "$cuenta: sin respuesta en 12 h"
  fi
done
[ "$renovado" = 1 ] && python3 collectors/build.py --sin-github >/dev/null 2>&1 || true  # quita el aviso del Panel
