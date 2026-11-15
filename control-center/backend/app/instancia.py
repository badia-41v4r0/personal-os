"""Configuración de la instancia desde el panel: perfil, módulos y configuración de cada módulo.

GET  /api/v1/instancia                 perfil público (nombre, áreas), módulos y estado del onboarding
PUT  /api/v1/instancia/modulos         activa o desactiva módulos (admin)
GET  /api/v1/instancia/config/{nombre} configuración de un módulo (sin secretos)
PUT  /api/v1/instancia/config/{nombre} la sustituye (admin; validada por su esquema)

Los agentes de onboarding no usan estas rutas: piden la acción `config.set`, que enseña la vista previa y espera el OK.
"""
import sys
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import events
from .adapters import hostagent
from .config import ROOT
from .core import modules
from .db import session_scope
from .security import Principal, current_principal, require_admin

sys.path.insert(0, str(ROOT / "collectors"))
import ajustes  # noqa: E402

router = APIRouter(prefix="/api/v1/instancia", dependencies=[Depends(current_principal)])

# Configuración editable desde el panel y por los agentes de onboarding, con su forma esperada.
# Lo que no está aquí (secretos, tokens) no se puede leer ni escribir por esta vía.
ESQUEMAS: dict[str, dict[str, type | tuple]] = {
    "perfil": {"nombre": str, "asistente": str, "nombre_completo": str, "idioma": str, "areas": list, "sobre_mi": str},
    "correo": {"cuentas": dict},
    "github": {"owner": str, "repos": dict},
    "estudios": {"plataforma": dict, "asignaturas": list, "disponibilidad": dict, "descansos": list, "fin": str, "criterio": str},
    "ofertas": {"puestos_objetivo": list, "puestos_cercanos": list, "lugares": list, "descartar": list, "reclutadores": list},
    "finanzas": {"pagadores_nomina": list},
    "agenda": {"calendarios_ocultos": list},
    "ia": {"proveedor": str, "relevo": bool, "modelos": dict, "limite_mensual_usd": (int, float)},
    "onboarding": {"hecho": bool, "apartados": dict},
}
MAX_BYTES = 200_000


def validar(nombre: str, datos: Any) -> dict:
    esquema = ESQUEMAS.get(nombre)
    if esquema is None:
        raise ValueError(f"No hay configuración «{nombre}»")
    if not isinstance(datos, dict):
        raise ValueError("La configuración tiene que ser un objeto")
    extra = set(datos) - set(esquema)
    if extra:
        raise ValueError(f"Campos desconocidos en {nombre}: {', '.join(sorted(extra))}")
    for k, tipo in esquema.items():
        if k in datos and not isinstance(datos[k], tipo):
            raise ValueError(f"{nombre}.{k} no tiene el tipo esperado")
    import json
    if len(json.dumps(datos, ensure_ascii=False)) > MAX_BYTES:
        raise ValueError("Configuración demasiado grande")
    if nombre == "ia":
        from .core import proveedores as motor
        if datos.get("proveedor", "claude") not in motor.PROVEEDORES:
            raise ValueError("Motor de IA desconocido")
        if float(datos.get("limite_mensual_usd", 0)) < 0:
            raise ValueError("El límite de gasto no puede ser negativo")
    if nombre == "perfil":
        if len(str(datos.get("asistente", ""))) > 40:
            raise ValueError("El nombre del asistente puede tener como mucho 40 caracteres")
        for a in datos.get("areas", []):
            if not isinstance(a, dict) or not ajustes.NOMBRE_RE.match(str(a.get("id", ""))):
                raise ValueError("Cada área necesita un id en minúsculas (letras, cifras, - o _)")
    return datos


def guardar_config(nombre: str, datos: dict, actor: str) -> dict:
    datos = validar(nombre, datos)
    ajustes.guardar(nombre, datos)
    if nombre == "estudios":
        actualizar_campus()
    with session_scope() as db:
        events.audit(db, actor, "config.set", nombre, campos=sorted(datos))
    events.publish("config.changed", {"nombre": nombre})
    return ajustes.leer(nombre)


def actualizar_campus() -> None:
    """Si ya hay ordenadores del campus, sus proxys pasan a los dominios nuevos (sin recrearlos ni perder la sesión)."""
    from .models import VirtualComputer
    from .modules import campus
    from sqlalchemy import select
    dom = campus.dominios()
    if not dom:
        return
    with session_scope() as db:
        ids = [v.id for v in db.scalars(select(VirtualComputer).where(VirtualComputer.profile == "canvas", VirtualComputer.status != "deleted"))]
    for vid in ids:
        try:
            hostagent.call_sync(f"/v1/vc/{vid}/dominios", method="PUT", json={"dominios": dom})
        except Exception:  # noqa: BLE001  se reintenta al volver a guardar; el ordenador sigue con los anteriores
            pass


def onboarding_estado() -> dict:
    o = ajustes.leer("onboarding")
    return {"hecho": bool(o.get("hecho")), "apartados": o.get("apartados") or {}}


@router.get("")
def instancia():
    perfil = ajustes.leer("perfil")
    return {"nombre": perfil.get("nombre") or "", "asistente": ajustes.asistente(), "idioma": perfil.get("idioma") or "es", "areas": ajustes.areas(),
            "modulos": modules.vista(), "onboarding": onboarding_estado()}


class ModulosIn(BaseModel):
    activos: list[str] = Field(max_length=64)


@router.put("/modulos")
async def poner_modulos(body: ModulosIn, p: Principal = Depends(require_admin)):
    antes = modules.timers_activos()
    try:
        act = modules.guardar(body.activos)
    except ValueError as e:
        raise HTTPException(422, str(e))
    with session_scope() as db:
        events.audit(db, p.name, "modules.set", ",".join(sorted(act)))
    events.publish("config.changed", {"nombre": "modulos"})
    despues = modules.timers_activos(act)
    avisos = []
    for t, on in [*((t, False) for t in antes - despues), *((t, True) for t in despues - antes)]:
        try:  # los timers siguen al módulo; si el Host Agent no responde, se dice y no se deshace el cambio
            await hostagent.call(f"/v1/timers/{t}/enabled", method="POST", json={"activo": on}, timeout=20)
        except Exception as e:  # noqa: BLE001
            avisos.append(f"No pude {'encender' if on else 'apagar'} el temporizador «{t}»: {str(getattr(e, 'detail', e))[:120]}")
    return {"modulos": modules.vista(act), "avisos": avisos}


@router.get("/config/{nombre}")
def leer_config(nombre: str):
    if nombre not in ESQUEMAS:
        raise HTTPException(404, "Configuración desconocida")
    return {"nombre": nombre, "datos": ajustes.leer(nombre)}


@router.put("/config/{nombre}")
def poner_config(nombre: str, body: dict, p: Principal = Depends(require_admin)):
    try:
        return {"nombre": nombre, "datos": guardar_config(nombre, body, p.name)}
    except ValueError as e:
        raise HTTPException(422, str(e))


# ---------- motor de IA: estado, credenciales (las guarda el Host Agent, nunca este proceso) ----------

@router.get("/motor")
async def motor_estado():
    from .core import proveedores as motor
    from .db import session_scope as scope
    try:
        estado = {p["id"]: p for p in await hostagent.call("/v1/proveedores")}
    except Exception as e:  # noqa: BLE001
        estado, aviso = {}, f"El Host Agent no responde: {str(getattr(e, 'detail', e))[:120]}"
    else:
        aviso = ""
    with scope() as db:
        gasto = motor.gasto_mes(db)
    return {"config": motor.config(), "elegido": motor.elegido(), "gasto_mes_openrouter": gasto, "limite": motor.limite(), "aviso": aviso,
            "proveedores": [{"id": p, "nombre": motor.NOMBRES[p], **motor.CAPACIDADES[p], "conectado": bool(estado.get(p, {}).get("conectado"))}
                            for p in motor.PROVEEDORES]}


class ClaveIn(BaseModel):
    clave: str = Field(min_length=10, max_length=300)


@router.put("/motor/openrouter/clave")
async def motor_clave(body: ClaveIn, p: Principal = Depends(require_admin)):
    r = await hostagent.call("/v1/proveedores/openrouter/clave", method="PUT", json={"clave": body.clave})
    with session_scope() as db:
        events.audit(db, p.name, "motor.clave", "openrouter")  # nunca la clave
    return r


@router.post("/motor/codex/importar")
async def motor_codex(p: Principal = Depends(require_admin)):
    r = await hostagent.call("/v1/proveedores/codex/importar", method="POST")
    with session_scope() as db:
        events.audit(db, p.name, "motor.codex.importar", "codex")
    return r


@router.delete("/motor/{prov}")
async def motor_desconectar(prov: str, p: Principal = Depends(require_admin)):
    if prov not in ("codex", "opencode"):
        raise HTTPException(404, "Ese motor no guarda credenciales aquí")
    r = await hostagent.call(f"/v1/proveedores/{prov}", method="DELETE")
    with session_scope() as db:
        events.audit(db, p.name, "motor.desconectar", prov)
    return r
