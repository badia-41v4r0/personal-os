#!/usr/bin/env bash
# Arranque del ordenador virtual. Sin servicios de red: el panel entra con `docker exec` (terminal) y
# `docker exec socat` al VNC local (escritorio). x11vnc solo escucha en localhost y sin contraseña porque
# solo es accesible desde dentro del contenedor.
set -u
mkdir -p "$HOME/trabajo" "$HOME/descargas" /tmp/.X11-unix 2>/dev/null
case "${VC_PROFILE:-terminal}" in
  browser|desktop|canvas|aplicaciones)
    export DISPLAY=:1
    Xvfb :1 -screen 0 1280x800x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
    for _ in $(seq 50); do [ -e /tmp/.X11-unix/X1 ] && break; sleep 0.1; done
    x11vnc -display :1 -localhost -rfbport 5900 -nopw -forever -shared -quiet >/tmp/x11vnc.log 2>&1 &
    if [ "$VC_PROFILE" = desktop ]; then
      fluxbox >/tmp/fluxbox.log 2>&1 &
      (sleep 1; xterm -geometry 110x30+40+40 -fa Monospace -fs 10 &) 
    else
      start=about:blank
      if [ "$VC_PROFILE" = canvas ] || [ "$VC_PROFILE" = aplicaciones ]; then
        # Única salida: su proxy (otro contenedor, con su lista de dominios) por el socket del volumen compartido
        socat TCP-LISTEN:3128,bind=127.0.0.1,fork,reuseaddr UNIX-CONNECT:/run/egress/proxy.sock >/tmp/socat.log 2>&1 &
        for _ in $(seq 100); do [ -s /run/egress/ca.pem ] && break; sleep 0.1; done
        mkdir -p "$HOME/.pki/nssdb"
        [ -f "$HOME/.pki/nssdb/cert9.db" ] || certutil -d "sql:$HOME/.pki/nssdb" -N --empty-password
        certutil -d "sql:$HOME/.pki/nssdb" -D -n jarvis-egress >/dev/null 2>&1
        certutil -d "sql:$HOME/.pki/nssdb" -A -t "C,," -n jarvis-egress -i /run/egress/ca.pem
        [ "$VC_PROFILE" = canvas ] && start="${VC_START_URL:-about:blank}"
      fi
      # El contenedor es el aislamiento: Chromium sin su sandbox (necesitaría privilegios que se han quitado).
      # CDP solo en 127.0.0.1 del contenedor (sin puertos publicados): lo usan las herramientas del agente.
      # Se relanza si se cierra, para que el agente no se quede sin navegador.
      (while true; do
        chromium --no-sandbox --no-first-run --disable-dev-shm-usage --user-data-dir="$HOME/.chromium" \
          --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 \
          --download-default-directory="$HOME/descargas" --window-position=0,0 --window-size=1280,800 "$start" \
          >>/tmp/chromium.log 2>&1
        sleep 2
      done) &
    fi
    ;;
esac
exec sleep infinity
