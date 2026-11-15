# API (v1)

Todo bajo `/api/v1`, con sesión (cookie) salvo `/health` y el login. Las peticiones con efecto llevan `X-CSRF-Token` y `Origin` permitido. Esquema completo: `/api/v1/openapi.json`.

| Área | Endpoints |
|---|---|
| Salud y acceso | `GET /health` · `POST /auth/login` · `POST /auth/logout` · `GET /auth/me` · `GET /audit` |
| Eventos | `GET /events?after=N` · `GET /events/cursor` · `GET /events/recent` · `WS /ws?after=N` (efímeros con id 0) |
| Sesión principal | `GET /sessions/main/transcripts` · `GET /sessions/main/messages` · `POST /sessions/main/messages` · `POST /sessions/main/interrupt` · `GET /sessions/main/state` |
| Sesiones | `GET/POST /sessions` · `GET/PATCH /sessions/{id}` · `GET/POST /sessions/{id}/messages` · `POST /sessions/{id}/interrupt` |
| Agentes | `GET/POST /agents` · `POST /agents/validate` · `GET/PATCH/DELETE /agents/{id}` · `POST /agents/{id}/activate|deactivate|duplicate|restore|sessions` · `GET /agents/{id}/versions|export|sessions` · `GET /agents/runs` |
| Ordenadores | `GET/POST /virtual-computers` · `GET/DELETE /virtual-computers/{id}` · `POST /virtual-computers/{id}/start|stop|restart` · `GET …/logs|files|download|screenshot` · `WS …/tty` · `WS …/vnc` |
| Sistema | `GET /system/metrics|services|containers` · `GET /system/metrics/history?range=` · `GET /system/logs/unit/{u}` · `GET /system/logs/container/{c}` · `GET /alerts` · `POST /alerts/{id}/resolve` |
| Memory | `GET /memory/tree|file|raw|search|recent|resolve|backlinks|rules` · `PUT /memory/file` |
| Productividad | `GET /agenda` · `GET /tasks` · `POST /tasks/done` (`texto`, `hecho`: Tareas.md + casilla del Panel) |
| Gym | Gym 2.0: ~45 rutas (overview, workouts, exercises, progress, records, muscles, recovery, plans, routines, recommendations, coach, reports, import). Lista completa en `docs/gym.md` |
| Orquestador de un proyecto | `GET /orq/status` (lo mismo que `orq-top`, con el cupo más reciente) · `POST /orq/action` (`pause`, `resume`, `drain`, `cap-override-on|off`, `retry|skip|done` + `task`, `answer` + `task` + `text`) |
