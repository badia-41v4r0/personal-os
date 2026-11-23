#!/usr/bin/env python3
"""Datos de demostración para probar el panel sin conectar nada. Úsalo solo en una instancia de prueba.

  cd control-center/backend && set -a && . ../../data/control-center/secrets.env && set +a && .venv/bin/python ../deployment/demo.py

Va por las mismas acciones que usan el panel y los agentes (como usuario «demo»), así que todo queda auditado y se
puede deshacer desde la Bandeja. Si ya hay tareas en la base, no hace nada.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import func, select  # noqa: E402

from app.core import actions  # noqa: E402
from app.db import session_scope  # noqa: E402
from app.models import Task  # noqa: E402
from app.modules import agent_caps  # noqa: E402,F401  (registra las acciones)

HOY = date.today()
d = lambda n: (HOY + timedelta(days=n)).isoformat()  # noqa: E731

DEMO = [
    ("task.create", {"texto": "Preparar la reunión del lunes", "fecha": d(1), "area": "trabajo"}),
    ("task.create", {"texto": "Repasar el tema 3", "fecha": d(0), "area": "uni"}),
    ("task.create", {"texto": "Renovar el DNI", "fecha": d(10), "area": "personal"}),
    ("task.create", {"texto": "Llamar al fontanero", "area": "personal"}),
    ("goal.create", {"titulo": "Correr una carrera de 10 km", "horizonte": "trimestre", "porque": "Mejorar el fondo", "fecha": d(90)}),
    ("habit.create", {"nombre": "Leer 20 minutos", "tipo": "diario"}),
    ("health.log", {"metrica": "peso", "valor": 72.4, "dia": d(-7)}),
    ("health.log", {"metrica": "peso", "valor": 71.9, "dia": d(0)}),
    ("health.log", {"metrica": "sueno", "valor": 7.5, "dia": d(-1)}),
    ("lifestyle.add", {"tipo": "viaje", "titulo": "Fin de semana en la montaña", "dia": d(21)}),
    ("lifestyle.add", {"tipo": "suscripcion", "titulo": "Música (9,99 €/mes)", "dia": d(5), "nota": "Se renueva cada mes"}),
    ("career.application.create", {"empresa": "Empresa Ejemplo", "puesto": "Ingeniería de soluciones", "proximo_paso": "Esperar respuesta"}),
]


def main() -> None:
    with session_scope() as db:
        if db.scalar(select(func.count()).select_from(Task)):
            sys.exit("Ya hay tareas en esta base: los datos de demostración son para una instancia vacía.")
    for cap, payload in DEMO:
        r = actions.request(cap, payload, actor="demo", actor_type="user", reason="Datos de demostración")
        print(f"{r['status']:>8}  {cap}  {r.get('error') or ''}")


if __name__ == "__main__":
    main()
