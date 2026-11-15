#!/usr/bin/env python3
"""Convierte el texto de un entreno pegado a mano en una sesión de Gym.md, sin modelo.

Admite el formato de Gym.md (`Press banca: 80×8, 80×8`) y el de compartir de Hevy:
    Press banca
    Set 1: 80 kg x 8
    Set 2 [Warm-up]: 40 kg x 10
Los calentamientos marcados no se apuntan, como en el método de Gym.md. Solo librería estándar.
"""
import re

SET_RE = re.compile(r"^(?:set|serie)\s*\d+\s*(\[[^\]]*\])?\s*:\s*(?:(\d+(?:[.,]\d+)?)\s*kg\s*[x×]\s*)?(\d+)\s*(?:reps?)?", re.I)
LINEA_RE = re.compile(r"^-?\s*([^:\d][^:]*?)\s*:\s*(.+\d.*)$")
RUIDO = re.compile(r"^(@|#|https?://|hevy|duration|volume|sets|records?)\b", re.I)


def _peso(v: str | None) -> str:
    if v is None:
        return "PC"
    n = v.replace(",", ".")
    return n[:-2] if n.endswith(".0") else n


def parsear(texto: str) -> tuple[list[tuple[str, list[str]]], list[str]]:
    ejercicios: list[tuple[str, list[str]]] = []
    avisos: list[str] = []
    actual: tuple[str, list[str]] | None = None
    for cruda in texto.splitlines():
        linea = cruda.strip()
        if not linea:
            actual = None
            continue
        m = SET_RE.match(linea)
        if m:
            if actual is None:
                avisos.append(f"Serie sin ejercicio: {linea}")
            elif not (m[1] and re.search(r"warm|calent", m[1], re.I)):
                actual[1].append(f"{_peso(m[2])}×{m[3]}")
            continue
        m = LINEA_RE.match(linea)
        if m and re.search(r"\d\s*[×x]\s*\d", m[2]):
            ejercicios.append((m[1].strip(), [s.strip().replace("x", "×") for s in m[2].split(",") if s.strip()]))
            actual = None
            continue
        if RUIDO.match(linea) or re.search(r"\b\d{4}\b", linea) or re.search(r"\b(am|pm)\b", linea, re.I):
            continue
        actual = (linea.lstrip("- ").strip(), [])
        ejercicios.append(actual)
    vacios = [e for e, s in ejercicios if not s]
    # El título del entreno es una línea sin series: se descarta sin avisar si es la primera
    if ejercicios and not ejercicios[0][1]:
        ejercicios = ejercicios[1:]
        vacios = vacios[1:]
    avisos += [f"«{e}» no tiene series: no se apunta" for e in vacios]
    return [(e, s) for e, s in ejercicios if s], avisos


def bloque(fecha: str, sesion: str, ejercicios: list[tuple[str, list[str]]]) -> str:
    return "\n".join([f"### {fecha} · {sesion}", *(f"- {e}: {', '.join(s)}" for e, s in ejercicios)])
