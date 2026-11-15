#!/usr/bin/env bash
# Procesa la cola de repos nuevas (Jarvis-Vault/Jarvis/Repos/cola/*.md), una a una.
# Jarvis no tiene credenciales de GitHub: deja la petición y este script, con el gh del PC, crea la
# repo SIEMPRE privada en la cuenta del usuario, la clona en repos/, la añade a la configuración (data/config/github.json)
# (así el programador puede trabajar en ella y sale en el Panel) y avisa por Telegram.
#   Campos del archivo: nombre, descripcion, area (un área del perfil; por defecto personal)
set -euo pipefail
cd "$(dirname "$0")/.."
OWNER="$(python3 collectors/ajustes.py github owner)"
[ -n "$OWNER" ] || { echo "Falta la cuenta de GitHub (Configuración o data/config/github.json)"; exit 1; }
MAX_DIA=3  # repos nuevas por día como máximo
Q=${REPOS_DIR:-Jarvis-Vault/Jarvis/Repos}  # REPOS_DIR solo para pruebas (y entonces los avisos salen por pantalla)
mkdir -p "$Q/cola" "$Q/hechos"
exec 9>/tmp/${POS_INSTANCE:-jarvis}-repos.lock
flock -n 9 || { echo "Ya se está creando una repo"; exit 0; }

avisar() { if [ -n "${REPOS_DIR:-}" ]; then echo "AVISO: $1"; else bin/telegram-send.sh "$1" || true; fi; }
campo() { sed -n "/^---$/,/^---$/s/^$1:[[:space:]]*//p" "$2" | head -1; }
cerrar() {  # cerrar <archivo> <resultado>
  { echo; echo "## Resultado ($(date '+%d/%m %H:%M'))"; echo; echo "$2"; } >> "$1"
  mv "$1" "$Q/hechos/"
}

while true; do
  f=$(ls -1 "$Q/cola/"*.md 2>/dev/null | sort | head -1) || true
  [ -n "${f:-}" ] || break
  sleep 2  # por si Syncthing aún está escribiendo el archivo
  nombre=$(campo nombre "$f")
  desc=$(campo descripcion "$f" | tr -d '\r' | head -c 350)
  area=$(campo area "$f"); python3 -c "import sys;sys.path.insert(0,'collectors');import ajustes;sys.exit(0 if sys.argv[1] in ajustes.areas() else 1)" "$area" || area=personal

  if ! [[ "$nombre" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$ ]]; then
    cerrar "$f" "❌ Nombre no válido."; avisar "⚠️ No he creado la repo «$nombre»: el nombre solo puede llevar letras, números, «.», «-» y «_»."; continue
  fi
  hoy=$(grep -c "^$(date +%F) " data/repos-creadas.log 2>/dev/null || true)
  if [ "${hoy:-0}" -ge "$MAX_DIA" ]; then
    cerrar "$f" "❌ Límite de $MAX_DIA repos al día."; avisar "⚠️ No he creado «$nombre»: ya van $MAX_DIA repos hoy. Si de verdad hacen falta más, créala desde el PC."; continue
  fi
  if gh repo view "$OWNER/$nombre" >/dev/null 2>&1 || [ -e "repos/$nombre" ]; then
    cerrar "$f" "❌ Ya existe."; avisar "⚠️ La repo «$nombre» ya existe en GitHub o en repos/."; continue
  fi

  # Siempre privada: no hay ningún camino en este script que cree una repo pública
  if ! err=$(gh repo create "$OWNER/$nombre" --private --add-readme --description "$desc" 2>&1 >/dev/null); then
    cerrar "$f" "❌ Error de GitHub: ${err:0:300}"; avisar "⚠️ GitHub no me ha dejado crear «$nombre»: ${err:0:300}"; continue
  fi
  vis=$(gh repo view "$OWNER/$nombre" --json visibility -q .visibility)
  if [ "$vis" != "PRIVATE" ]; then
    gh repo edit "$OWNER/$nombre" --visibility private --accept-visibility-change-consequences >/dev/null || true
    avisar "🚨 La repo «$nombre» salió como $vis y la he pasado a privada. Compruébalo en GitHub."
  fi

  nota=""
  gh repo clone "$OWNER/$nombre" "repos/$nombre" -- -q 2>/dev/null || nota="⚠️ No pude clonarla en repos/; el programador no podrá usarla hasta clonarla."
  # Se añade a la configuración de la instancia (data/config/github.json), no al repo
  python3 - "$nombre" "$area" <<'PY'
import sys; sys.path.insert(0, "collectors"); import ajustes
g = ajustes.propia("github"); g.setdefault("repos", {})[sys.argv[1]] = {"modelo": "sonnet", "minutos": 45, "subagentes": False, "area": sys.argv[2]}
ajustes.guardar("github", g)
PY
  echo "$(date +%F) $nombre" >> data/repos-creadas.log

  url="https://github.com/$OWNER/$nombre"
  cerrar "$f" "✅ Creada (privada): $url
- Área: $area · programador: Sonnet, 45 min${nota:+
- $nota}"
  avisar "📦 Repo creada (privada): $url
Ya puedes encargarle cosas al programador (Sonnet, 45 min; dímelo si quieres cambiarlo).${nota:+
$nota}"
done
