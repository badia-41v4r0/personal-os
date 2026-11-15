# Panel del Personal OS (control-center)

Panel web, backend y Host Agent. La instalación y el uso están en el [README del proyecto](../README.md) y en
[docs/](../docs/); aquí solo lo que hace falta para desarrollar.

- `backend/`: FastAPI + SQLAlchemy + Alembic (SQLite por defecto; PostgreSQL con `CC_DB_URL`). Pruebas:
  `cd backend && env -u CC_DB_URL .venv/bin/pytest` (nunca con `secrets.env` cargado: las pruebas borran la base).
- `host-agent/`: única pieza que toca el host (systemd, Docker, métricas), por socket Unix con token y auditoría.
- `apps/web/`: Next.js exportado en estático y servido por el backend. `npm run build`; E2E con Playwright contra
  una instancia de prueba (`CC_E2E_URL`).
- `virtual-computers/`: imágenes de los ordenadores virtuales y su proxy de salida.
- `agents/`: instrucciones de Jarvis, de cada apartado y de los asistentes de onboarding (`agents/onboarding/`).
- `docs/`: documentación técnica por tema (arquitectura, seguridad, gym, educación, candidaturas…).
