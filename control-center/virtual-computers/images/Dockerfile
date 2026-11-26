# Ordenadores virtuales del Jarvis Control Center. Contenedores aislados (no VMs): comparten kernel con el host.
# Dos imágenes: terminal (CLI) y desktop (X virtual + VNC + Chromium + Playwright; sirve a los perfiles browser y desktop).
FROM debian:bookworm-slim AS terminal
ARG TZ=Europe/Madrid
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 TZ=$TZ
RUN apt-get update && apt-get install -y --no-install-recommends \
      bash ca-certificates coreutils curl git jq less nano procps python3 python3-venv python3-pip nodejs npm \
      socat tini tzdata unzip wget zip file \
 && rm -rf /var/lib/apt/lists/*
# Usuario sin privilegios (sin sudo). uid 1001 para no coincidir con el del host.
RUN useradd -m -u 1001 -s /bin/bash vc && mkdir -p /home/vc/trabajo && chown -R vc:vc /home/vc
COPY vc-entrypoint.sh /usr/local/bin/vc-entrypoint
RUN chmod 755 /usr/local/bin/vc-entrypoint
USER vc
WORKDIR /home/vc/trabajo
ENV VC_PROFILE=terminal
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/vc-entrypoint"]

FROM terminal AS desktop
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
      chromium xvfb x11vnc fluxbox xterm pcmanfm scrot xdotool fonts-dejavu-core fonts-liberation x11-xserver-utils \
      libatomic1 \
 && rm -rf /var/lib/apt/lists/*
# Playwright (Python) usando el Chromium del sistema: no descarga navegadores. Su driver (node) necesita libatomic1.
RUN python3 -m venv /opt/pw && /opt/pw/bin/pip install --no-cache-dir playwright==1.* && chmod -R a+rX /opt/pw
ENV PATH=/opt/pw/bin:$PATH PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/chromium
# fluxbox sin fondo de pantalla (si no, abre un aviso xmessage); color liso con xsetroot
RUN mkdir -p /home/vc/.fluxbox \
 && printf 'session.screen0.rootCommand: xsetroot -solid "#1b1f24"\nsession.screen0.toolbar.visible: true\n' > /home/vc/.fluxbox/init \
 && printf 'background: none\n' > /home/vc/.fluxbox/overlay \
 && chown -R vc:vc /home/vc/.fluxbox \
 && printf '#!/bin/sh\nexec xsetroot -solid "#1b1f24"\n' > /usr/local/bin/fbsetbg && chmod 755 /usr/local/bin/fbsetbg
USER vc
ENV VC_PROFILE=desktop

# Campus: navegador con la sesión de la universidad del usuario. Sin red propia: sale solo por su proxy (contenedor aparte,
# solo los dominios de su campus) a través del socket /run/egress/proxy.sock. Políticas de Chromium en la raíz de solo
# lectura: proxy fijo y sin gestor de contraseñas.
FROM desktop AS canvas
USER root
RUN apt-get update && apt-get install -y --no-install-recommends libnss3-tools && rm -rf /var/lib/apt/lists/*
COPY canvas-policy.json /etc/chromium/policies/managed/jarvis-canvas.json
RUN chmod 644 /etc/chromium/policies/managed/jarvis-canvas.json
USER vc
ENV VC_PROFILE=canvas

# Aplicaciones: solicitudes de empleo. Igual que Canvas (sin red, solo su proxy con los dominios de esa solicitud) y
# además sin autorrelleno de tarjetas ni direcciones y sin descargas. (Las herramientas de desarrollo no se pueden
# quitar por política: también cortan el control por CDP que usan las operaciones de formulario.)
FROM canvas AS aplicaciones
USER root
RUN rm -f /etc/chromium/policies/managed/jarvis-canvas.json
COPY aplicaciones-policy.json /etc/chromium/policies/managed/jarvis-aplicaciones.json
RUN chmod 644 /etc/chromium/policies/managed/jarvis-aplicaciones.json
USER vc
ENV VC_PROFILE=aplicaciones
