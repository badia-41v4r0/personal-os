# Crear un módulo

Un módulo es una parte del Personal OS que se puede activar o desactivar: sus apartados del panel, su API, lo que sus
agentes pueden leer y hacer, sus asistentes, sus temporizadores y su configuración.

## 1. Declararlo

En `control-center/backend/app/core/modules.py`, añade un `Module` a `MODULES`:

```python
Module("plantas", "Plantas", "Riego y cuidados de tus plantas.",
       web=("/plantas/",),              # rutas del panel
       api=("/api/v1/plantas",),        # prefijos de API que son solo suyos (404 si está apagado)
       prefijos=("plant.",),            # lecturas y acciones de agentes: plant.list, plant.water…
       asistentes=("plantas",),         # su asistente de apartado
       timers=("riego",),               # systemd/riego.{service,timer}.in
       config=("plantas",))             # data/config/plantas.json
```

Con eso, al apagarlo: la web lo esconde, su API responde 404, el gateway y `core/actions` rechazan `plant.*` aunque
alguien los pida, el orquestador no elige su asistente y su temporizador se apaga.

## 2. Datos y API

- Modelos en `app/models.py` y una migración de Alembic en `backend/migrations/versions/` (las migraciones se aplican
  siempre; con el módulo apagado sus tablas quedan vacías).
- Router en `app/modules/plantas.py` con `APIRouter(prefix="/api/v1/plantas", dependencies=[Depends(current_principal)])`,
  registrado en `app/main.py`.

## 3. Lo que pueden hacer los agentes

- Lecturas: `@gateway.tool("plant.list")`.
- Acciones: `actions.register(actions.Capability("plant.water", 1, handler, "Regar", inverse=deshacer))`. Elige bien el
  nivel: 1 si es interno y reversible, 2 si sale fuera, 3 si no tiene vuelta atrás. **No registres nada que mueva dinero
  o envíe mensajes a terceros sin aprobación.**

## 4. Su asistente

En `app/core/orchestrator.py`, añade a `SECTIONS` un `Specialist("plantas", "standard", lecturas, acciones, (), section=True)`
y sus instrucciones en `control-center/agents/plantas.md` (usa `{{nombre}}` para el nombre del usuario). En la web,
añade el asistente en `apps/web/src/components/cc/assistants.ts` y el apartado en `nav.ts`.

## 5. Configuración y onboarding

- Valores por defecto en `config/defecto/plantas.json`, su esquema en `ESQUEMAS` de `app/instancia.py` y, si el
  asistente de onboarding puede proponerla, añádela a `CONFIGS_AGENTE` en `app/modules/onboarding.py`.
- Guía del asistente de bienvenida en `control-center/agents/onboarding/plantas.md`: qué preguntar y qué forma tiene la
  configuración. Se le añade sola a `_comun.md`.
- Desde los scripts y collectors: `import ajustes; ajustes.leer("plantas")`.

## 6. Pruebas

`backend/tests/` con los fixtures `client`, `auth` y `config_instancia` (carpeta de configuración temporal con todos los
módulos activos). Prueba también que con el módulo apagado su API da 404 y sus acciones se rechazan.
