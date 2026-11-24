# Personal OS

Un asistente personal que vive en tu PC. Organiza tu agenda, tus tareas, tus estudios, tu entrenamiento, tus finanzas
y tu búsqueda de empleo desde un panel web privado, con un asistente de IA en cada apartado. Tus datos se quedan en tu
máquina; el modelo de IA solo ve lo que necesita en cada turno.

![Asistente de bienvenida](docs/img/bienvenida.png)

## Qué hace

- **Inicio:** tu asistente (por defecto se llama Jarvis, pero le pones el nombre que quieras), que lo ve todo, con check-in de mañana y noche, avisos y un resumen de tu día.
- **Un asistente por apartado.** Cada uno solo ve lo suyo y solo puede hacer lo suyo.
- **Módulos que activas y desactivas:** Agenda, Correo, Educación, Entrenamiento, Salud, Finanzas, Carrera, Objetivos,
  Estilo de vida, Conocimiento (tu vault de Obsidian), Proyectos (GitHub), Ayudante, Vídeos, Ordenadores virtuales,
  Voz y avisos por Telegram. Lo desactivado desaparece del panel y ningún agente puede usarlo.
- **Rutinas:** briefing por la mañana, recordatorio por la noche y revisión semanal.
- **Elige tu motor de IA:** Claude Code, Codex (ChatGPT), OpenRouter (con OpenCode) o Antigravity.
- **Onboarding guiado:** la primera vez que abres un apartado, su asistente te ayuda a configurarlo. Nada se guarda
  sin tu aprobación. El de Educación puede abrir tu campus virtual en un navegador aislado y leer asignaturas,
  entregas y calendario por ti.

| Motor de IA | Módulos | Primera vez en un apartado |
|---|---|---|
| ![Motor de IA](docs/img/motor.png) | ![Módulos](docs/img/modulos.png) | ![Primera vez](docs/img/primera-vez.png) |

## Instalación rápida

Si ya tienes Docker, Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 20+ y git:

```bash
git clone https://github.com/badia-41v4r0/personal-os.git && cd personal-os
bin/pos instalar            # o «bin/pos instalar --simular» para ver qué haría sin tocar nada
```

Abre el panel con `bin/pos abrir` (por defecto `http://127.0.0.1:8770`) y entra con **`admin` / `admin`**: lo primero
que te pide es cambiarlos. Después, la bienvenida. Si no tienes los requisitos, sigue la
[instalación paso a paso](docs/instalacion.md).

## Cómo se usa

Todo está en el panel, ordenado así:

| Dónde | Qué hay |
|---|---|
| **Hoy** | **Inicio** (resumen, check-ins y «Te falta por configurar»), **Bandeja** (lo que espera tu aprobación y los avisos), **Agenda** y **Tareas** |
| **Tus áreas** | Un apartado por módulo activo (Educación, Entrenamiento, Finanzas…), cada uno con su asistente en el chat flotante de abajo |
| **Conocimiento** | Tu vault de Obsidian y «Qué sé de ti» |
| **Ajustes** | Todo lo que se configura o se conecta: cuenta, motor de IA, módulos, conexiones (Google, campus, Telegram, avisos en el móvil), automatizaciones y autonomía. En «Avanzado», agentes, ordenadores virtuales, sistema y auditoría |

La campana de arriba lleva a la Bandeja y cuenta lo que espera tu decisión. `Ctrl+K` busca apartados, ajustes y notas.
Desde la terminal, todo con un comando: `bin/pos` (`bin/pos ayuda`).

Paso a paso con Docker, problemas frecuentes, Windows (WSL2), móvil y mantenimiento: **[docs/instalacion.md](docs/instalacion.md)**.

## Documentación

- [Instalación](docs/instalacion.md): paso a paso con Docker, problemas frecuentes, Windows (WSL2), móvil con Tailscale, actualizar y desinstalar.
- [Guía de uso](docs/guia-de-uso.md): qué hace cada apartado y cómo sacarle partido.
- [Motores de IA](docs/motores-de-ia.md): qué puede hacer cada uno, cómo conectarlo y qué cuesta.
- [Seguridad y privacidad](docs/seguridad.md): qué ve cada agente, qué sale de tu PC y qué no.
- [Crear un módulo](docs/modulos.md): para quien quiera extenderlo.
- Documentación técnica por tema en [control-center/docs/](control-center/docs/).

## Cómo está hecho

```
 Navegador (PC o móvil por Tailscale)
        │ solo 127.0.0.1 o tu tailnet
 ┌──────▼───────────────────────────┐      ┌──────────────────────────────┐
 │ Backend (FastAPI) + web (Next.js) │◄────►│ Host Agent (socket Unix)     │
 │ SQLite o PostgreSQL · módulos     │      │ systemd · Docker · métricas  │
 │ acciones con aprobación · memoria │      │ lista cerrada y auditada     │
 └──────┬───────────────────────────┘      └──────┬───────────────────────┘
        │ lee y escribe                            │ lanza
 ┌──────▼──────────┐                ┌──────────────▼─────────────────────────┐
 │ Vault Obsidian   │                │ Contenedor efímero por turno de IA     │
 │ (tus notas)      │                │ (Claude, Codex u OpenCode), sin $HOME, │
 └─────────────────┘                │ sin Docker, sin privilegios; escribe   │
                                     │ solo por acciones del Personal OS      │
                                     └────────────────────────────────────────┘
```

## Licencia

[PolyForm Noncommercial 1.0.0](LICENSE): puedes usarlo, modificarlo y compartirlo **sin fines comerciales** (uso
personal, estudio, investigación, organizaciones sin ánimo de lucro). El uso comercial está reservado al autor; si lo
quieres para un uso comercial, escríbele. Para contribuir, mira [CONTRIBUTING.md](CONTRIBUTING.md).

## Estado

Proyecto personal publicado tal cual. Funciona en Linux, donde los ordenadores virtuales están incluidos y se instalan
con `bin/pos instalar` (salvo con `--sin-ordenadores`). En Windows puede funcionar dentro de WSL2
([instrucciones](docs/instalacion.md#windows-con-wsl2-sin-probar), sin probar). En Mac o con Docker Desktop no funciona: el Host Agent necesita
Linux. Documentación e interfaz en español.

Usar tu suscripción de un proveedor de IA con este proyecto es responsabilidad tuya: revisa sus condiciones de uso.
