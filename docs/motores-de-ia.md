# Motores de IA

Se elige en **Configuración → Motor de IA** (y en la bienvenida). Todos corren igual de aislados: un contenedor
efímero por turno, sin acceso a tu `$HOME` ni a Docker, y las escrituras en tus datos pasan por acciones del
Personal OS (con aprobación cuando toca).

| | Claude Code | Codex (ChatGPT) | OpenRouter (OpenCode) | Antigravity |
|---|---|---|---|---|
| Cómo se paga | Tu suscripción de Claude | Tu cuenta de ChatGPT | Por uso, con tu clave | Tu cuenta de Google |
| Herramientas del Personal OS | Sí | Sí | Sí | No (solo texto) |
| Ordenador virtual (tutor, campus) | Sí | Sí | Sí | No |
| Subagentes | Sí | No | No | No |
| Búsqueda web | Sí | No | No | No |
| Red del contenedor | Internet | Solo su API (proxy) | Solo su API (proxy) | — |
| Reanudar la conversación del día | Sí | Sí | Sí | No |

Si el motor elegido no sabe hacer algo que un apartado necesita (por ejemplo, subagentes), el turno sigue sin eso y la
respuesta lo dice. Nunca se cambia de motor a escondidas.

## Conectar cada uno

- **Claude Code:** en el PC, `claude setup-token`, y pon el token en `.env` (`CLAUDE_CODE_OAUTH_TOKEN=`). Después
  `bin/pos actualizar`.
- **Codex:** en el PC, `codex login`. En Configuración → Motor de IA, pulsa **Conectar Codex**: copia tu sesión a la
  del Personal OS (archivo 600). Codex renueva su token durante los turnos y se guarda el nuevo.
- **OpenRouter:** crea una clave en openrouter.ai y pégala en Configuración → Motor de IA. Se guarda en un archivo
  que solo lee tu usuario y solo la recibe el turno en curso. Pon modelos en formato `openrouter/proveedor/modelo` y un
  **límite de gasto mensual**: al llegar, no se lanzan más turnos con él. Te recomendamos fijar también un límite en la
  propia clave de OpenRouter.
- **Antigravity:** inicia sesión con su CLI en el PC. Solo responde con texto (sin herramientas ni tus datos), para
  consultas generales.

## Modelos y relevo

Cada motor tiene un modelo por perfil: rápido, normal, a fondo y código. Los asistentes piden un perfil (el tutor, por
ejemplo, «a fondo»).

**Relevo:** si usas Claude y su cuota de la semana se acaba, otro motor puede responder en modo consulta (solo texto,
sin tus datos). Se activa o desactiva en la misma tarjeta.

## Por qué sin red

Codex y OpenCode llevan su credencial dentro del contenedor durante el turno. Para que un contenido malicioso (una web,
un PDF) no pueda convencer al modelo de enviarla a otro sitio, su contenedor no tiene red: sale por un proxy que solo
deja los dominios de su API (`host-agent/proveedores.py → DOMINIOS`) y apunta cada conexión.
