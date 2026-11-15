"""Ventana de la conversación de voz con Jarvis (terminal). Teclas: p = pausar/reanudar, b = borrar la vista, q = salir.

Lee voz/estado/conversacion.jsonl y voz/estado/fase, que escribe jarvis_voz.py. Solo librería estándar.
"""
import json
import os
import select
import shutil
import sys
import termios
import textwrap
import time
import tty
from datetime import datetime
from pathlib import Path

ESTADO = Path(__file__).resolve().parent / "estado"
CONVERSACION, FASE, PAUSA = ESTADO / "conversacion.jsonl", ESTADO / "fase", ESTADO / "pausa"
DESDE = ESTADO / "ventana-desde"   # la vista empieza en esta marca de tiempo (tecla b)
PENSANDO_MAX = 180                 # s sin respuesta: deja de mostrar «pensando»

CIAN, AMBAR, GRIS, BLANCO, ROJO, VERDE, RESET = ("\033[38;5;45m", "\033[38;5;214m", "\033[38;5;244m",
                                                  "\033[97m", "\033[38;5;203m", "\033[38;5;78m", "\033[0m")
FASES = {"escuchando": (VERDE, "● ESCUCHANDO · di «oye Jarvis»"), "grabando": (ROJO, "● TE ESCUCHO…"),
         "transcribiendo": (AMBAR, "◌ TRANSCRIBIENDO…"), "hablando": (CIAN, "◉ HABLANDO"),
         "pausa": (GRIS, "⏸ EN PAUSA · p para reanudar")}


def leer_mensajes() -> list[dict]:
    desde = DESDE.read_text().strip() if DESDE.exists() else ""
    try:
        lineas = CONVERSACION.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    out = []
    for l in lineas:
        try:
            m = json.loads(l)
        except json.JSONDecodeError:
            continue
        if m["t"] > desde:
            out.append(m)
    return out


def pintar(mensajes: list[dict]) -> str:
    ancho, alto = shutil.get_terminal_size((80, 24))
    ancho = max(30, ancho)
    fase = FASE.read_text().strip() if FASE.exists() else "?"
    color, etiqueta = FASES.get(fase, (GRIS, "○ SERVICIO PARADO"))
    if mensajes and mensajes[-1]["quien"] == "tu" and fase not in ("hablando", "pausa"):
        if (datetime.now() - datetime.fromisoformat(mensajes[-1]["t"])).total_seconds() < PENSANDO_MAX:
            color, etiqueta = AMBAR, "◌ JARVIS ESTÁ PENSANDO…"
    cab = [f"{CIAN}{'J.A.R.V.I.S. · VOZ'.center(ancho)}{RESET}", f"{color}{etiqueta.center(ancho)}{RESET}",
           f"{GRIS}{'─' * ancho}{RESET}"]
    cuerpo = []
    for m in mensajes:
        hora = m["t"][11:16]
        if m["quien"] == "tu":
            pre, col = f"{hora} Tú  ", BLANCO
        elif m["quien"] == "jarvis":
            pre, col = f"{hora} J.  ", CIAN
        else:
            pre, col = f"{hora} ·   ", GRIS
        lineas = textwrap.wrap(m["texto"], ancho - len(pre)) or [""]
        cuerpo.append(f"{GRIS}{pre}{RESET}{col}{lineas[0]}{RESET}")
        cuerpo += [f"{' ' * len(pre)}{col}{l}{RESET}" for l in lineas[1:]]
        cuerpo.append("")
    pie = f"{GRIS}{'p pausa · b limpiar · q salir'.center(ancho)}{RESET}"
    hueco = alto - len(cab) - 1
    cuerpo = cuerpo[-hueco:] if hueco > 0 else []
    cuerpo += [""] * (hueco - len(cuerpo))
    return "\033[H\033[2J" + "\n".join(cab + cuerpo + [pie])


def main():
    fd = sys.stdin.fileno()
    viejo = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    sys.stdout.write("\033[?25l\033]2;Jarvis · voz\007")
    anterior = None
    try:
        while True:
            mensajes = leer_mensajes()
            pantalla = pintar(mensajes)
            if pantalla != anterior:
                sys.stdout.write(pantalla)
                sys.stdout.flush()
                anterior = pantalla
            if select.select([sys.stdin], [], [], 0.4)[0]:
                k = os.read(fd, 1).decode(errors="ignore").lower()
                if k == "q":
                    break
                if k == "p":
                    PAUSA.unlink() if PAUSA.exists() else PAUSA.touch()
                if k == "b":
                    DESDE.write_text(datetime.now().isoformat(timespec="seconds"))
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, viejo)
        sys.stdout.write("\033[?25h\033[H\033[2J")


if __name__ == "__main__":
    main()
