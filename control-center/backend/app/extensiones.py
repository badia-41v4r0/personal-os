"""Extensiones locales: módulos propios de una instalación que no forman parte del proyecto público.

Si existe el paquete `app/privado/`, se carga al arrancar y su `registrar(app)` añade lo suyo: rutas de la API,
módulos del registro, lecturas y acciones de los agentes, instrucciones extra e integraciones. Las carpetas
`privado/` no se publican nunca (`privado/exportar-publico.sh` las excluye), así que el proyecto público no sabe nada
de ellas: sin ese paquete, esto no hace nada.
"""
from dataclasses import replace

from fastapi import FastAPI

# Instrucciones extra por asistente («jarvis», «tutor»…): se añaden al final de las suyas
INSTRUCCIONES: dict[str, list[str]] = {}


def modulo(m) -> None:
    """Añade un módulo al registro (core/modules.py): se activa y desactiva como los demás."""
    from .core import modules
    modules.MODULES[m.id] = m
    if m.id not in modules.ORDEN:
        modules.ORDEN.append(m.id)


def asistente_general(lecturas: tuple[str, ...] = (), acciones: tuple[str, ...] = ()) -> None:
    """Lecturas y acciones extra para el asistente general (el de Inicio)."""
    from .core import orchestrator as o
    o.DEFAULT = replace(o.DEFAULT, tools=o.DEFAULT.tools + tuple(lecturas), capabilities=o.DEFAULT.capabilities + tuple(acciones))


def integracion(fila: tuple) -> None:
    """Una fila más en Ajustes → Conexiones (mismo formato que modules/home.py → INTEGRACIONES)."""
    from .modules import home
    home.INTEGRACIONES = home.INTEGRACIONES + (fila,)


def cargar(app: FastAPI) -> None:
    try:
        from . import privado
    except ImportError:
        return
    privado.registrar(app)
