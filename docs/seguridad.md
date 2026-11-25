# Seguridad y privacidad

## Qué sale de tu PC

- **Lo que lee el modelo en cada turno**, hacia el proveedor que elijas: tu mensaje, las instrucciones del asistente y
  un contexto corto (hechos sobre ti y lo de ese apartado). No se le manda tu base de datos ni tu vault entera.
- **Avisos push** al servicio de Apple o Google, cifrados de extremo a extremo.
- **Lo que tú conectes:** Google (calendario y correo), GitHub, Telegram, tu campus. Cada uno, solo para lo suyo.
- **Tu banco, si lo conectas:** el panel pide a Enable Banking tus saldos y movimientos (solo lectura; nunca puede
  mover dinero). Se guardan en tu base de datos; ningún agente tiene camino para tocar credenciales bancarias.

Todo lo demás (base de datos, vault, archivos, transcripción de voz con Whisper, búsqueda semántica con Ollama) se
queda en tu máquina.

## Cómo se aísla a los agentes

- **Un contenedor efímero por turno:** raíz de solo lectura, `cap_drop ALL`, `no-new-privileges`, límites de memoria y
  CPU, sin `$HOME`, sin el socket de Docker y sin tus secretos.
- **Sin terminal en el contenedor del modelo.** Si un agente necesita ejecutar código, lo hace en su ordenador
  virtual, que no tiene red ni credenciales.
- **Cada agente solo ve lo suyo:** su apartado de la vault (en solo lectura) y una credencial de turno que abre solo
  sus lecturas y acciones. Lo de los módulos apagados no existe para nadie.
- **Las escrituras pasan por acciones** con tres niveles: 1 se hace sola y se puede deshacer; 2 sale fuera de la
  vault y pide aprobación salvo reglas concretas; 3 siempre espera tu OK. La aprobación va ligada a la huella del
  contenido: si cambia, no se ejecuta. Hay un interruptor general para pausar toda la autonomía.
- **Contenido externo = datos.** Lo que viene de correos, webs o PDF nunca son órdenes. Si un agente ha leído correo
  en un turno, sus acciones de nivel 2 pasan a necesitar aprobación.
- **Motores que no son Claude** corren sin red: solo un proxy hacia su propia API. Ver [motores-de-ia.md](motores-de-ia.md).
- **El ordenador del campus** solo sale a los dominios de tu universidad (los apruebas tú). El agente nunca escribe
  credenciales: inicias sesión tú.

## El panel

- Solo escucha en `127.0.0.1`. Para el móvil, Tailscale Serve (tu red privada), nunca Funnel ni puertos abiertos.
- Contraseña con Argon2id, sesión en cookie HttpOnly y SameSite, CSRF, comprobación de origen (también en WebSocket) y
  bloqueo tras varios fallos.
- El **Host Agent** es la única pieza que toca el sistema (systemd, Docker): por socket Unix con token, con una lista
  cerrada de capacidades y todo auditado. El backend nunca es root ni toca Docker directamente.
- **Auditoría encadenada:** cada registro lleva la huella del anterior; Ajustes → Autonomía comprueba que nadie la ha
  alterado.

## Secretos

`.env`, `data/control-center/secrets.env`, `secrets/` y las credenciales de los motores (`data/control-center/proveedores/`)
tienen permisos 600 y están fuera de git. Ninguno se monta en los contenedores de los agentes, salvo la credencial del
motor durante su turno.

Las credenciales que se ponen desde el panel (token de Claude, clave de OpenRouter, bot de Telegram) las escribe solo el
Host Agent, y solo una lista cerrada de claves con su formato (`host-agent/hostagent.py → ENV_PERMITIDAS`). Igual la
clave `.pem` de Enable Banking: el Host Agent comprueba que es una clave RSA y la guarda en `secrets/<id>.pem`. El
backend las reenvía sin guardarlas, el navegador no las vuelve a ver (solo si están puestas) y la auditoría apunta qué
se cambió, nunca el valor.

## Si encuentras un fallo

No abras una issue pública con los detalles. Escribe al mantenedor por un canal privado.
