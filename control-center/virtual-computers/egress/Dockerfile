# Proxy de salida (solo los dominios permitidos) para el ordenador del campus y el de solicitudes (mitmproxy + socat). Contenedor aparte del ordenador:
# el agente no puede verlo, pararlo ni cambiar sus reglas.
FROM debian:bookworm-slim
ARG TZ=Europe/Madrid
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 TZ=$TZ
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates python3 python3-venv socat tini tzdata \
 && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/mitm && /opt/mitm/bin/pip install --no-cache-dir "mitmproxy==11.0.*" && chmod -R a+rX /opt/mitm
ENV PATH=/opt/mitm/bin:$PATH
RUN useradd -m -u 1002 -s /usr/sbin/nologin egress
COPY filtro.py /opt/egress/filtro.py
COPY egress-entrypoint.sh /usr/local/bin/egress-entrypoint
RUN chmod 644 /opt/egress/filtro.py && chmod 755 /usr/local/bin/egress-entrypoint
USER egress
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/egress-entrypoint"]
