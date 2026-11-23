# bin/

**Para ti solo hay un comando: `bin/pos`** (`bin/pos ayuda` enseña todas sus órdenes). Lo demás de esta carpeta lo
usan los servicios y los contenedores del sistema; no hace falta llamarlo a mano.

| Script | Quién lo usa |
|---|---|
| `pos` | Tú: instalar, abrir, estado, logs, contraseña, PostgreSQL, voz, actualizar y desinstalar |
| `entrypoint.sh` | Arranque de los contenedores |
| `sesion-run`, `jarvis-run`, `jarvis-prompt.sh`, `jarvis-rutina` | Turnos de IA (Host Agent y rutinas) |
| `manana.sh`, `noche.sh` | Rutinas de la mañana y de la noche (systemd) |
| `ayudante.sh`, `ayudante-run` | Módulo Ayudante |
| `programador.sh`, `programador-run`, `crear-repo.sh` | Módulo Proyectos |
| `renovar-google.sh` | Renovación del permiso de Google |
| `video.sh`, `transcribir`, `transcribir-video.py` | Vídeos y transcripción |
| `voz` | Voz en el PC |
| `telegram-send.sh` | Avisos por Telegram |
| `aprobar` | Instalar propuestas de skills y subagentes desde la terminal (lo normal es aprobarlas en la Bandeja) |
