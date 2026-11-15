#!/usr/bin/env bash
# Procesa la cola de tareas del ayudante (Jarvis-Vault/Jarvis/Ayudante/cola/*.md), una a una.
# El ayudante es una instancia de Claude Code aislada: su carpeta (/trabajo), la vault en solo lectura
# y la web. Sin credenciales, sin Python ni node. El resultado se copia a Ayudante/hechos/<id>/ y
# el resumen llega por Telegram.
#   Campos del archivo: titulo, modelo (sonnet|opus; por defecto sonnet), minutos (por defecto 30, máx. 90)
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
A=Jarvis-Vault/Jarvis/Ayudante
mkdir -p "$A/cola" "$A/en-curso" "$A/hechos" data/ayudante-home  # creada por mí, no por Docker (sería de root)
exec 9>/tmp/${POS_INSTANCE:-jarvis}-ayudante.lock
flock -n 9 || { echo "Ya hay una tarea en marcha"; exit 0; }

avisar() { bin/telegram-send.sh "$1" || true; }
campo() { sed -n "/^---$/,/^---$/s/^$1:[[:space:]]*//p" "$2" | head -1; }

while true; do
  f=$(ls -1 "$A/cola/"*.md 2>/dev/null | sort | head -1) || true
  [ -n "${f:-}" ] || break
  sleep 2  # por si Syncthing aún está escribiendo el archivo
  id=$(basename "$f" .md)
  titulo=$(campo titulo "$f"); [ -n "$titulo" ] || titulo=$id
  modelo=$(campo modelo "$f"); [[ "$modelo" =~ ^(sonnet|opus)$ ]] || modelo=sonnet
  minutos=$(campo minutos "$f"); [[ "$minutos" =~ ^[0-9]+$ ]] || minutos=30
  [ "$minutos" -le 90 ] || minutos=90
  mv "$f" "$A/en-curso/"; f="$A/en-curso/$id.md"
  avisar "🤖 Empiezo la tarea «$titulo» ($modelo, máx. $minutos min)."

  T="data/ayudante/$id"; rm -rf "$T"; mkdir -p "$T"
  sed '1,/^---$/{/^---$/!d};/^---$/d' "$f" > "$T/.tarea.md"
  inicio=$(date +%s)
  timeout --kill-after=60 "${minutos}m" docker compose run --rm -T \
    -v "$ROOT/$T:/trabajo" -e MODELO="$modelo" ayudante >/dev/null 2>&1 \
    || echo $'\n\n(fin por error o tiempo límite)' >> "$T/resultado.md"
  dur=$(( ($(date +%s) - inicio) / 60 ))

  # Copia a la vault lo que haya dejado (sin el registro interno ni enlaces), con 20 MB como máximo
  D="$A/hechos/$id"; mkdir -p "$D"
  find "$T" -maxdepth 3 -type f ! -name '.*' -size -20M -print0 | while IFS= read -r -d '' x; do
    rel=${x#"$T"/}; mkdir -p "$D/$(dirname "$rel")"; cp "$x" "$D/$rel"
  done
  [ "$(du -sm "$D" | cut -f1)" -le 20 ] || { rm -rf "$D"; mkdir -p "$D"; cp "$T/resultado.md" "$D/"; }
  { echo; echo "## Resultado ($(date '+%d/%m %H:%M'), $dur min)"; echo; echo "Archivos: [[Ayudante/hechos/$id/resultado|resultado]]"; } >> "$f"
  mv "$f" "$D/tarea.md"
  archivos=$(cd "$D" && ls -1 | grep -v -e '^tarea.md$' -e '^resultado.md$' | head -10 | sed 's/^/• /')
  msg="✅ Tarea terminada: «$titulo» ($dur min)
$(head -c 1500 "$D/resultado.md")"
  [ -n "$archivos" ] && msg+=$'\n\n'"📎 En la vault (Jarvis/Ayudante/hechos/$id):"$'\n'"$archivos"
  avisar "$msg"
done
