#!/bin/sh
# Proxy de salida del ordenador de Canvas. Escucha solo en 127.0.0.1 de SU contenedor; el ordenador llega por el
# socket Unix del volumen compartido /gw (que monta en solo lectura). Copia ahí el certificado de la CA de mitmproxy
# para que Chromium confíe en él.
set -u
mkdir -p /data/mitm
mitmdump --quiet --listen-host 127.0.0.1 --listen-port 8080 --set confdir=/data/mitm \
  --set connection_strategy=lazy --set stream_large_bodies=5m -s /opt/egress/filtro.py &
for _ in $(seq 100); do [ -s /data/mitm/mitmproxy-ca-cert.pem ] && break; sleep 0.1; done
cp /data/mitm/mitmproxy-ca-cert.pem /gw/ca.pem.tmp && mv /gw/ca.pem.tmp /gw/ca.pem
rm -f /gw/proxy.sock
exec socat UNIX-LISTEN:/gw/proxy.sock,fork,mode=666 TCP:127.0.0.1:8080
