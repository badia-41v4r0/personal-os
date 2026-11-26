# Motores de IA

El motor es la IA que responde en los chats del panel. Se elige en **Ajustes → Motor de IA** (y en la bienvenida). Todos
corren igual de aislados: un contenedor efímero por turno, sin acceso a tu `$HOME` ni a Docker, y las escrituras en tus
datos pasan por acciones del Personal OS (con aprobación cuando toca).

| | Claude Code | Codex (ChatGPT) | OpenCode | Antigravity |
|---|---|---|---|---|
| Cómo se paga | Tu suscripción de Claude | Tu cuenta de ChatGPT | OpenCode Go (suscripción), OpenCode Zen (por uso) u OpenRouter (por uso) | Tu cuenta de Google |
| Herramientas del Personal OS | Sí | Sí | Sí | No (solo texto) |
| Ordenador virtual (tutor, campus) | Sí | Sí | Sí | No |
| Subagentes | Sí | No | No | No |
| Búsqueda web | Sí | No | No | No |
| Red del contenedor | Internet | Solo su API (proxy) | Solo su API (proxy) | — |
| Reanudar la conversación del día | Sí | Sí | Sí | No |

Si el motor elegido no sabe hacer algo que un apartado necesita (por ejemplo, subagentes), el turno sigue sin eso y la
respuesta lo dice. Nunca se cambia de motor a escondidas.

## Conectar cada uno

### Claude Code

1. En el PC: `claude setup-token` e inicia sesión con tu cuenta de Claude (Pro o Max).
2. Pega el token (`sk-ant-…`) en **Ajustes → Motor de IA → Claude Code** (o en la bienvenida).
3. Elige el modelo de cada perfil (Sonnet u Opus) y pulsa **Guardar**.

El token lo guarda el Host Agent en el `.env` del PC con permisos 600. El panel nunca lo vuelve a mostrar.

### Codex (ChatGPT)

1. En el PC: `codex login` con tu cuenta de ChatGPT.
2. En **Ajustes → Motor de IA → Codex (ChatGPT)**, pulsa **Conectar Codex**. Copia tu sesión a la del Personal OS
   (un archivo 600). Si cierras sesión o caduca, vuelve a pulsarlo (**Volver a conectar**).
3. Los modelos pueden quedarse vacíos: se usa el que Codex tenga por defecto.

Codex renueva su token durante los turnos, y se guarda el nuevo.

### OpenCode

[OpenCode](https://opencode.ai) es una CLI de código abierto que habla con muchos modelos (Claude, GPT, Gemini, Kimi,
GLM, DeepSeek…). En el Personal OS puede usar tres servicios, y **el prefijo del modelo dice cuál**:

| Servicio | Cómo se paga | Clave | Modelos |
|---|---|---|---|
| **OpenCode Go** | Suscripción mensual, con sus propios límites de uso | La de opencode.ai | `opencode-go/…` |
| **OpenCode Zen** | Por uso, con saldo en opencode.ai (algunos modelos son gratis) | La de opencode.ai (la misma) | `opencode/…` |
| **OpenRouter** | Por uso, con saldo en openrouter.ai | La de OpenRouter (`sk-or-…`) | `openrouter/proveedor/modelo` |

**Paso a paso (OpenCode Go o Zen):**

1. Entra en [opencode.ai](https://opencode.ai), inicia sesión y suscríbete a **Go** o añade saldo a **Zen**.
2. En la consola de opencode.ai, crea una **clave de API** y cópiala.
3. En **Ajustes → Motor de IA**, elige **OpenCode**, pega la clave en **Clave de OpenCode** y pulsa **Guardar**.
   Aparece como «guardada».
4. En **Modelos**, pon uno por perfil (Rápido, Normal, A fondo y Código). Por ejemplo, con Go:
   `opencode-go/glm-5.3-flash` en Rápido, `opencode-go/kimi-k3` en Normal y A fondo, y `opencode-go/kimi-k2.7-code`
   en Código. Con Zen, lo mismo con `opencode/…` (por ejemplo, `opencode/claude-sonnet-5-5`).
5. Pulsa **Guardar** abajo del todo. Escribe algo en el chat para comprobarlo.

**Con OpenRouter**, igual, pero con una clave creada en [openrouter.ai](https://openrouter.ai) en **Clave de
OpenRouter (opcional)** y modelos con el formato `openrouter/proveedor/modelo` (el nombre exacto, en la web de OpenRouter). Puedes tener las dos claves y mezclar
servicios entre perfiles (por ejemplo, Go para lo diario y OpenRouter para «A fondo»).

**Qué modelos hay:** el catálogo cambia a menudo. Para verlo, ejecuta en el PC `opencode models opencode-go`,
`opencode models opencode` u `opencode models openrouter`, o mira la web de cada servicio. Copia el nombre tal cual,
con su prefijo.

**Límite de gasto:** en la misma tarjeta, **Límite de gasto al mes (USD)**, junto a lo que llevas gastado este mes.
Cuenta lo que cuesta cada turno con Zen u OpenRouter. Al llegar, no se lanzan más turnos de pago hasta el mes siguiente
o hasta que lo subas. La suscripción Go no cuenta (ya tiene sus límites en opencode.ai). Te recomendamos fijar también
un límite en la propia clave de OpenRouter o en tu saldo de Zen.

**Cómo se guardan las claves:** cada una, en un archivo del PC que solo lee tu usuario (`data/control-center/
proveedores/`), nunca en la base ni en el navegador. Cada turno recibe **solo la clave del servicio de su modelo**.
**Quitar** junto a una clave la borra.

### Antigravity

Inicia sesión con su CLI en el PC. Solo responde con texto (sin herramientas ni tus datos), para consultas generales.

## Modelos y relevo

Cada motor tiene un modelo por perfil: rápido, normal, a fondo y código. Los asistentes piden un perfil (el tutor, por
ejemplo, «a fondo»).

**Relevo:** si usas Claude y su cuota de la semana se acaba, otro motor puede responder en modo consulta (solo texto,
sin tus datos). Se activa o desactiva en la misma tarjeta.

## Si algo falla

| Mensaje o síntoma | Qué hacer |
|---|---|
| «Elige un modelo de OpenCode…» | Rellena los modelos de la tarjeta, con prefijo, y pulsa Guardar. |
| «El modelo … no vale para OpenCode» | El nombre debe empezar por `opencode/`, `opencode-go/` u `openrouter/`. |
| «Falta la clave de OpenCode/OpenRouter para el modelo…» | Ese perfil usa un servicio cuya clave no has puesto: ponla o cambia el modelo. |
| «Has llegado al límite de gasto…» | Sube el límite en la tarjeta o espera al mes siguiente (o usa modelos `opencode-go/…`). |
| «Eso no parece una clave de…» | Has pegado la clave en el campo equivocado: las de OpenRouter empiezan por `sk-or-`. |
| Error de la API (saldo, cuota, modelo inexistente) | Comprueba tu saldo o suscripción en la web del servicio y el nombre exacto con `opencode models`. |
| Codex deja de responder | Ejecuta `codex login` en el PC y pulsa **Volver a conectar**. |
| «Falta CLAUDE_CODE_OAUTH_TOKEN» | Vuelve a ejecutar `claude setup-token` y pega el token. |

## Por qué sin red

Codex y OpenCode llevan su credencial dentro del contenedor durante el turno. Para que un contenido malicioso (una web,
un PDF) no pueda convencer al modelo de enviarla a otro sitio, su contenedor no tiene red: sale por un proxy que solo
deja los dominios de su API (`host-agent/proveedores.py → DOMINIOS`) y apunta cada conexión.
