# Instalación, configuración y operación

## Requisitos
Omarchy/Arch con Docker y el contenedor `jarvis` en marcha, Tailscale, `uv` (Python 3.12), Node ≥ 22 y `gh` autenticado (para Projects). Todo corre como el usuario normal, nunca como root.

## Instalar o actualizar
```bash
# 1. Secretos del panel (una vez). NO en secrets/: esa carpeta la monta el contenedor de Jarvis.
install -m 600 control-center/deployment/control-center.env.example data/control-center/secrets.env
#    y rellenar CC_HOSTAGENT_TOKEN con: python3 -c 'import secrets;print(secrets.token_hex(32))'
# 2. Instalar o actualizar (dependencias, web, imágenes de ordenadores virtuales, servicios y temporizador de copias)
control-center/deployment/instalar.sh
# 3. Usuario (una vez; pregunta la contraseña)
cd control-center/backend && uv run python -m app.cli set-password <usuario>
# 4. Acceso por la tailnet (una vez)
tailscale serve --bg --https=10000 http://127.0.0.1:8770
```

## Configuración (`data/control-center/secrets.env`)
| Variable | Para qué |
|---|---|
| `CC_HOSTAGENT_TOKEN` | Secreto compartido backend ↔ Host Agent (≥ 32 caracteres) |
| `CC_ALLOWED_ORIGINS` | Orígenes permitidos (CSRF y WebSocket): la URL de Tailscale y `http://127.0.0.1:8770` |
| `CC_COOKIE_SECURE` | `1` en producción (HTTPS de Tailscale) |
| `CC_MONITOR` | `0` desactiva el muestreo y las políticas (solo pruebas) |

## Servicios (systemd de usuario)
| Unidad | Qué hace |
|---|---|
| `<instancia>-cc-hostagent.service` | Capacidades del host (socket `$XDG_RUNTIME_DIR/<instancia>-cc/hostagent.sock`) |
| `<instancia>-cc-backend.service` | API + web en `127.0.0.1:8770`; aplica migraciones al arrancar. Depende del Host Agent (reiniciar este reinicia el backend) |
| `<instancia>-cc-backup.timer` | Copia de la base a las 3:30 (`Persistent=true`) |

Reiniciar el panel no toca a Jarvis: `systemctl --user restart <instancia>-cc-backend`.
Logs: `journalctl --user -u <instancia>-cc-backend -f`. Auditoría del host: `data/control-center/hostagent-audit.jsonl`. Health check: `curl http://127.0.0.1:8770/api/v1/health`.

## Copias y recuperación
- Qué se copia: `data/control-center/cc.db` (sesiones, mensajes del panel, agentes y versiones, ejecuciones, aprobaciones, auditoría, métricas, ordenadores) y la auditoría del Host Agent. Copia en caliente con la API de SQLite, comprobada con `integrity_check`, en `data/control-center/backups/<fecha>/` (permisos 600, se guardan 14).
- Qué **no**: la vault (Syncthing con versionado de 30 días), el repo (git + GitHub), el estado de Jarvis (`data/home`) y los volúmenes de los ordenadores persistentes. Copia externa de todo ello: backlog («Backup nocturno… al disco externo»).
- Copia manual: `control-center/backend/.venv/bin/python control-center/deployment/backup.py`.
- Restaurar: `control-center/deployment/restaurar.sh data/control-center/backups/<fecha>` (guarda antes una copia de la base actual, para el backend, restaura y arranca con las migraciones pendientes). Probado el 31/10.
- Si el panel no arranca: `journalctl --user -u <instancia>-cc-backend -n 50`; si es la base, restaurar la última copia. Si es el Host Agent, `systemctl --user restart <instancia>-cc-hostagent`.

## Quitarlo del todo (rollback)
`tailscale serve --https=<puerto> off`, `systemctl --user disable --now <instancia>-cc-backend <instancia>-cc-hostagent <instancia>-cc-backup.timer`. Jarvis sigue igual: lo único que se tocó de él es aditivo (regla del panel en `agent/CLAUDE.md`, línea de `gym_stats.py`, cerrojo común en `jarvis-prompt.sh` y la voz, opciones `--json`/`--si` de `bin/aprobar`) y funciona sin el panel.

## Migrar al MSI GT72
Copiar la carpeta entera (incluida `data/`), instalar requisitos y ejecutar `instalar.sh` y el `tailscale serve`. Los ordenadores virtuales y la GPU son opcionales.

## Avisos en el iPhone

1. Abre Tailscale en el iPhone y actívalo. Para no depender de ello, activa «VPN bajo demanda» en sus ajustes.
2. Abre el panel en **Safari** (`https://<equipo>.<tailnet>.ts.net:<puerto>`).
3. Compartir → «Añadir a pantalla de inicio».
4. Abre Jarvis **desde ese icono** e inicia sesión. La sesión de la app es distinta a la de Safari.
5. Avisos → «Activar avisos en este dispositivo» → permitir → «Enviar prueba».

El aviso llega aunque el iPhone no esté en la tailnet; para abrir el panel, sí hace falta. Si dejan de llegar: Avisos muestra el último envío de cada dispositivo. Quita el dispositivo y actívalo de nuevo. Si el PC o el backend están caídos no hay push: para eso sigue el aviso por Telegram.

Copia a guardar aparte: `data/control-center/vapid.pem`.

