# Registro de decisiones técnicas (ADR)

| ADR | Decisión | Estado |
|---|---|---|
| 0001 | Monolito modular: FastAPI + SQLite (WAL) + Next.js, procesos de usuario con systemd; sin Redis, colas externas, Prometheus ni Kubernetes | Aceptada |
| 0002 | Claude Code híbrido: sesión principal por tmux (lectura del JSONL + cola serializada); sesiones independientes con `claude -p --resume` en contenedores efímeros; Agent SDK aplazado | Aceptada (prueba del 31/10) |
| 0003 | Host Agent aparte: socket Unix 600 + token, capacidades cerradas, sin root, auditoría JSONL. El backend nunca ve el socket de Docker | Aceptada |
| 0004 | Obsidian es la fuente de verdad. SQLite solo guarda datos del panel; Gym.md se parsea, no se copia | Aceptada |
| 0005 | Autenticación propia aunque haya Tailscale: Argon2id, cookie opaca HttpOnly/Secure/SameSite=Strict, token CSRF + Origin, WebSocket con Origin y cookie | Aceptada |
| 0006 | Acceso por Tailscale Serve en el puerto HTTPS 10000 (443 y 8443 ya están ocupados) | Aceptada y activa (31/10) |
| 0008 | Frontend como export estático servido por FastAPI (no `next start`): ahorra un proceso y ~150 MB, mismo origen. Coste: sin funciones de servidor de Next (no se usan) y CSP con `'unsafe-inline'` en scripts (el export no admite nonces) | Aceptada |
| 0009 | Cerrojo común de teclado (`$XDG_RUNTIME_DIR/jarvis-prompt.lock`) para todo lo que escribe en tmux; el prefijo del panel lo pone el Host Agent | Aceptada y activa |
| 0007 | Ordenadores virtuales con contenedores Docker endurecidos (no VMs); acceso por `docker exec`, sin puertos; agentes por MCP con socket por turno | Aceptada |
| 0010 | Sesiones independientes sin Bash: con red y token en el entorno, una terminal permitiría sacarlo; `execute` = su ordenador virtual | Aceptada |
| 0011 | SQLite sin pool (`NullPool`) y autenticación con conexión breve: evita agotar conexiones con peticiones que esperan | Aceptada |
| 0012 | Secretos del panel en `data/control-center/secrets.env`, no en `secrets/` (montada por el contenedor de Jarvis) | Aceptada |

Detalle y alternativas de 0002 en `../M0-auditoria.md`.
