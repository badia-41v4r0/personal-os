#!/usr/bin/env bash
# Procesa la cola de encargos de código (Jarvis-Vault/Jarvis/Encargos/cola/*.md), uno a uno.
# El programador (contenedor) no tiene credenciales de GitHub: trabaja en local en la rama staging.
# Este script, con el gh del PC, sube SOLO la rama staging (sin force), abre/actualiza el PR hacia
# la rama principal y crea los issues que haya propuesto. el usuario revisa y fusiona en GitHub.
# La repo de repos/ nunca entra en el contenedor: trabaja en una copia desechable (.git incluido) y de ella solo
# se traen los commits de staging. Así nada que deje en .git (hooks, config) llega a ejecutarse con el gh del PC.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
OWNER="$(python3 collectors/ajustes.py github owner)"
[ -n "$OWNER" ] || { echo "Falta la cuenta de GitHub (Configuración o data/config/github.json)"; exit 1; }
E=Jarvis-Vault/Jarvis/Encargos
exec 9>/tmp/${POS_INSTANCE:-jarvis}-programador.lock
flock -n 9 || { echo "Ya hay un encargo en marcha"; exit 0; }

avisar() { bin/telegram-send.sh "$1" || true; }
campo() { sed -n "/^---$/,/^---$/s/^$1:[[:space:]]*//p" "$2" | head -1; }

while true; do
  f=$(ls -1 "$E/cola/"*.md 2>/dev/null | sort | head -1) || true
  [ -n "${f:-}" ] || break
  sleep 2  # por si Syncthing aún está escribiendo el archivo
  id=$(basename "$f" .md)
  repo=$(campo repo "$f"); tipo=$(campo tipo "$f"); titulo=$(campo titulo "$f")
  conf=$(python3 collectors/ajustes.py github repos | jq -c --arg r "$repo" '.[$r] // empty')
  if [ -z "$conf" ]; then
    mv "$f" "$E/hechos/"; avisar "⚠️ Encargo $id rechazado: la repo «$repo» no está en la lista."; continue
  fi
  modelo=$(jq -r .modelo <<<"$conf"); minutos=$(jq -r .minutos <<<"$conf"); sub=$(jq -r .subagentes <<<"$conf")
  mv "$f" "$E/en-curso/"; f="$E/en-curso/$id.md"
  avisar "🛠️ Empiezo el encargo «$titulo» en $repo ($modelo, máx. $minutos min)."

  # 1) Preparar staging: se parte de origin/staging (o de la rama principal si no existe) y se trae lo nuevo de la principal
  R="repos/$repo"
  git -C "$R" fetch -q origin
  principal=$(git -C "$R" symbolic-ref --short refs/remotes/origin/HEAD | cut -d/ -f2)
  git -C "$R" reset -q --hard && git -C "$R" clean -qfd
  if git -C "$R" rev-parse -q --verify origin/staging >/dev/null; then
    git -C "$R" checkout -q -B staging origin/staging
  else
    git -C "$R" checkout -q -B staging "origin/$principal"
  fi
  nota_merge=""
  if ! git -C "$R" merge -q --no-edit "origin/$principal" >/dev/null 2>&1; then
    git -C "$R" merge --abort || true
    nota_merge="⚠️ staging tiene conflictos con $principal; no se han integrado los últimos cambios de $principal."
  fi
  base=$(git -C "$R" rev-parse HEAD)

  # 2) Ejecutar el programador
  S="data/programador-salida/$id"; mkdir -p "$S"
  W="data/programador-trabajo/$id"; rm -rf "$W"; mkdir -p "$(dirname "$W")"
  cp -a --reflink=auto "$R" "$W"
  { echo "Encargo ($tipo) en la repo $repo: $titulo"; echo; sed '1,/^---$/{/^---$/!d};/^---$/d' "$f"; } > "$S/encargo.md"
  inicio=$(date +%s)
  # Proxy de salida en su propio contenedor: sin token, y el programador no lo puede tocar
  G="data/programador-gw/$id"; rm -rf "$G"; mkdir -p "$G"
  EG="${POS_INSTANCE:-jarvis}-prog-egress-$$"
  docker run -d --rm --name "$EG" --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges \
    --memory 128m --cpus 0.5 --pids-limit 64 --network bridge \
    -v "$ROOT/$G:/gw" -v "$ROOT/programador/egress.py:/opt/egress.py:ro" \
    --entrypoint python3 "${POS_INSTANCE:-jarvis}:local" /opt/egress.py /gw/proxy.sock >/dev/null
  timeout --kill-after=60 "${minutos}m" docker compose run --rm -T \
    -v "$ROOT/$W:/repo" -v "$ROOT/$S:/salida" -v "$ROOT/$G:/run/egress:ro" \
    -e MODELO="$modelo" -e SUBAGENTES="$sub" -e ENCARGO="$id" programador >/dev/null 2>&1 || echo "(fin por error o tiempo límite)" >> "$S/resumen.md"
  docker rm -f "$EG" >/dev/null 2>&1 || true
  [ -f "$G/egress.jsonl" ] && cp "$G/egress.jsonl" "$S/egress.jsonl"
  rm -rf "$G"
  dur=$(( ($(date +%s) - inicio) / 60 ))

  # 3) Traer solo los commits de staging y subirlos, sin force. Solo se lee la copia con fetch (upload-pack):
  #    nunca se ejecuta git dentro de ella, porque su .git no es de fiar (el WIP lo commitea el contenedor).
  nuevo=""
  if [ -d "$W/.git" ] && [ ! -L "$W/.git" ]; then
    git -C "$R" -c core.hooksPath=/dev/null -c protocol.file.allow=always fetch -q --no-tags \
      "file://$ROOT/$W/.git" "+refs/heads/staging:refs/programador/$id" 2>/dev/null || true
    nuevo=$(git -C "$R" rev-parse -q --verify "refs/programador/$id^{commit}" || true)
  fi
  if [ -n "$nuevo" ] && git -C "$R" merge-base --is-ancestor "$base" "$nuevo"; then
    git -C "$R" -c core.hooksPath=/dev/null merge -q --ff-only "$nuevo"
  else
    echo "⚠️ staging no sale de la base del encargo: no se ha integrado nada." >> "$S/resumen.md"
  fi
  git -C "$R" update-ref -d "refs/programador/$id" 2>/dev/null || true
  rm -rf "$W"
  commits=$(git -C "$R" rev-list --count "$base..HEAD")
  pr=""; push_ok=1
  if [ "$commits" -gt 0 ]; then
    if git -C "$R" -c core.hooksPath=/dev/null push -q origin staging:staging; then
      pr=$(gh pr list -R "$OWNER/$repo" --head staging --base "$principal" --state open --json url -q '.[0].url')
      if [ -z "$pr" ]; then
        pr=$(gh pr create -R "$OWNER/$repo" --head staging --base "$principal" \
          --title "Jarvis · staging → $principal" \
          --body "PR acumulado con los encargos de Jarvis. Cada encargo deja un comentario con su resumen. **Revisa y fusiona tú.**")
      fi
      gh pr comment "$pr" -R "$OWNER/$repo" --body "### 🤖 Encargo: $titulo ($id)

$(cat "$S/resumen.md")" >/dev/null
    else
      push_ok=0
    fi
  fi

  # 4) Issues propuestos
  issues=""
  if [ -s "$S/issues.json" ]; then
    while IFS= read -r it; do
      url=$(gh issue create -R "$OWNER/$repo" --title "$(jq -r .titulo <<<"$it")" --body "$(jq -r .cuerpo <<<"$it")

_Creado por Jarvis (encargo $id)._" 2>/dev/null) && issues+=$'\n'"• $url"
    done < <(jq -c '.[]' "$S/issues.json")
  fi

  # 5) Registro y aviso
  { echo; echo "## Resultado ($(date '+%d/%m %H:%M'), $dur min)"; echo; [ -n "$nota_merge" ] && echo "$nota_merge"; \
    echo "- Commits: $commits"; [ -n "$pr" ] && echo "- PR: $pr"; [ -n "$issues" ] && echo "- Issues:$issues"; \
    [ "$push_ok" = 0 ] && echo "- ⚠️ No se pudo subir staging (¿cambios remotos?)."; echo; cat "$S/resumen.md"; } >> "$f"
  mv "$f" "$E/hechos/"
  msg="✅ Encargo terminado: «$titulo» ($repo, $dur min)
$(head -c 900 "$S/resumen.md")"
  [ -n "$pr" ] && msg+=$'\n\n'"🔀 PR para revisar: $pr"
  [ -n "$issues" ] && msg+=$'\n'"📝 Issues:$issues"
  [ -n "$nota_merge" ] && msg+=$'\n'"$nota_merge"
  [ "$push_ok" = 0 ] && msg+=$'\n'"⚠️ No pude subir staging: hay cambios remotos que no tengo. Revísalo."
  avisar "$msg"
done
