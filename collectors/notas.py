"""Calcula la nota de cada asignatura a partir de Jarvis/Areas/Notas-Uni.md y reescribe su tabla `## Resumen`.

Lee de la nota (la mantienen Jarvis y el usuario):
- `## Resumen`: columnas Fórmula (p. ej. `30 % PEC + 70 % PR`) y Mínimos (`PEC ≥ 4 · PR ≥ 5 · cada PEC ≥ 3`).
- Una sección `## XX · Nombre` por asignatura con una tabla Entregable | Peso | … | Nota. El peso puede ser
  `18 % de PEC` / `1/3 de EC` (dentro de un bloque de la fórmula), `30 %` (directo sobre la final),
  `suma a la práctica` (extra que se suma a esa nota, hasta 10) o vacío/⚠️ (reparte a partes iguales lo que falte).
Escribe solo las columnas Nota actual y Estado. Sin IA, solo librería estándar.

Uso: python3 notas.py [--ver]   (--ver imprime el resumen sin escribir)
"""
import math
import re
import sys

from lib import JARVIS, write_atomic

NOTA = JARVIS / "Areas" / "Notas-Uni.md"
APROBADO = 5.0
LETRAS = {"A": 9.5, "B": 8.0, "C+": 6.0, "C-": 4.0, "D": 1.5}
NUM = r"(\d+(?:[.,]\d+)?)"


def num(s: str) -> float:
    return float(s.replace(",", "."))


def fmt(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def arriba(x: float) -> float:
    """Redondea hacia arriba a 0,1 (lo que hace falta, mejor no quedarse corto)."""
    return math.ceil(round(x * 10, 6)) / 10


def limpio(s: str) -> str:
    return s.replace("⚠️", "").replace("⚠", "").replace("**", "").strip()


def celdas(linea: str) -> list[str]:
    return [c.strip() for c in linea.strip().strip("|").split("|")]


def tablas(texto: str) -> list[tuple[list[str], list[list[str]]]]:
    """Tablas markdown de un bloque de texto: (cabecera, filas)."""
    out, actual = [], None
    for linea in texto.splitlines():
        if linea.lstrip().startswith("|"):
            c = celdas(linea)
            if actual is None:
                actual = (c, [])
                out.append(actual)
            elif not all(re.fullmatch(r":?-+:?", x) for x in c if x):
                actual[1].append(c)
        else:
            actual = None
    return out


def leer_nota(cell: str) -> float | None:
    s = limpio(cell).upper()
    if not s:
        return None
    if s.startswith("NP"):
        return 0.0
    m = re.search(NUM, s)
    if m:
        return min(num(m[1]), 10.0)
    return LETRAS.get(s.split()[0])


def bloques(formula: str) -> dict[str, float]:
    """'30 % PEC + 70 % PR' -> {'pec': 0.3, 'pr': 0.7}"""
    out = {}
    for t in limpio(formula).split("+"):
        m = re.match(rf"\s*{NUM}\s*%\s*(.+?)\s*$", t)
        if m:
            out[m[2].lower()] = num(m[1]) / 100
    return out


def entregables(filas, cab, formula) -> tuple[list[dict], list[str]]:
    col = {n.lower(): i for i, n in enumerate(cab)}
    ie, ip, inn = col.get("entregable", 0), col.get("peso"), col.get("nota")
    if ip is None or inn is None:
        return [], ["tabla sin columnas Peso o Nota"]
    bl, avisos, items, extras = bloques(formula), [], [], []
    for f in filas:
        f += [""] * (len(cab) - len(f))
        nombre, peso, nota = limpio(f[ie]), f[ip], leer_nota(f[inn])
        it = {"nombre": nombre, "nota": nota, "peso": None, "grupo": nombre.lower(), "supuesto": "⚠" in peso}
        p = limpio(peso)
        if m := re.search(r"suma a (?:la |el )?(.+)", p, re.I):
            extras.append((m[1].strip().lower(), nota))
            continue
        pct = re.search(rf"{NUM}\s*%", p)
        frac = re.search(r"(\d+)\s*/\s*(\d+)", p)
        v = num(pct[1]) / 100 if pct else int(frac[1]) / int(frac[2]) if frac else None
        de = re.search(r"\bde\s+([^\s(]+)", p)
        if de and v is not None:
            if de[1].lower() in bl:
                it["peso"], it["grupo"] = v * bl[de[1].lower()], de[1].lower()
            else:
                avisos.append(f"bloque «{de[1]}» no está en la fórmula")
                it["supuesto"] = True
        elif v is not None:
            it["peso"] = v
        items.append(it)

    # Pesos desconocidos: se reparte a partes iguales lo que falte hasta el 100 %
    sin = [i for i in items if i["peso"] is None]
    if sin:
        resto = max(0.0, 1 - sum(i["peso"] for i in items if i["peso"] is not None))
        for i in sin:
            i["peso"], i["supuesto"] = resto / len(sin), True
    total = sum(i["peso"] for i in items)
    if items and abs(total - 1) > 0.01:
        avisos.append(f"los pesos suman {fmt(total * 100)} %")

    # Extras (p. ej. ejercicios voluntarios): se suman a la nota del entregable o bloque indicado, hasta 10
    for destino, extra in extras:
        if not extra:
            continue
        for i in items:
            if (i["grupo"] == destino or i["nombre"].lower().startswith(destino)) and i["nota"] is not None:
                i["nota"] = min(10.0, i["nota"] + extra)
    return items, avisos


def calcular(items: list[dict], minimos: str) -> tuple[str, str]:
    if not items:
        return "", "sin tabla de entregables"
    hechos = [i for i in items if i["nota"] is not None]
    total = sum(i["peso"] for i in items)
    acc = sum(i["peso"] * i["nota"] for i in hechos)
    peso_hecho = sum(i["peso"] for i in hechos)
    resto = total - peso_hecho
    supuesto = " (pesos ⚠️)" if any(i["supuesto"] for i in items) else ""
    if not hechos:
        return "", "Sin notas aún" + supuesto

    actual = acc / peso_hecho
    nota_actual = f"{fmt(actual)} ({fmt(peso_hecho / total * 100).removesuffix(',0')} % evaluado)"
    fallos, extra = [], []

    # Mínimos: 'PEC ≥ 4' sobre la media del bloque; 'cada PEC ≥ 3' sobre cada entregable
    for regla in re.split(r"[·,;]", limpio(minimos)):
        m = re.match(rf"\s*(cada\s+)?(.+?)\s*(?:≥|>=)\s*{NUM}\s*$", regla, re.I)
        if not m:
            continue
        cada, nombre, minimo = bool(m[1]), m[2].strip().lower(), num(m[3])
        grupo = [i for i in items if i["grupo"] == nombre or i["nombre"].lower().startswith(nombre)]
        if not grupo:
            continue
        if cada:
            for i in grupo:
                if i["nota"] is not None and i["nota"] < minimo:
                    fallos.append(f"{i['nombre']} {fmt(i['nota'])} < {fmt(minimo)}")
            continue
        w = sum(i["peso"] for i in grupo)
        a = sum(i["peso"] * i["nota"] for i in grupo if i["nota"] is not None)
        r = sum(i["peso"] for i in grupo if i["nota"] is None)
        etiqueta = m[2].strip()
        if r == 0:
            if a / w < minimo:
                fallos.append(f"{etiqueta} {fmt(a / w)} < {fmt(minimo)}")
        elif r < w:  # bloque empezado: lo que hace falta en lo que queda del bloque
            falta = (minimo * w - a) / r
            if falta > 10:
                fallos.append(f"{etiqueta} ya no llega al {fmt(minimo)}")
            elif falta > 0:
                extra.append((etiqueta, arriba(falta)))

    partes = [f"❌ {f}" for f in fallos]
    if resto <= 1e-9:
        final = acc / total
        if not fallos:
            partes.insert(0, f"{'✅ Aprobada' if final >= APROBADO else '❌ Suspendida'} ({fmt(final)})")
        else:
            partes.insert(0, f"Final {fmt(final)}, pero no cumple los mínimos")
    else:
        falta = (APROBADO * total - acc) / resto
        if falta > 10:
            partes.append("❌ ya no llega al 5")
        elif falta <= 0:
            partes.append("El 5 ya está asegurado (si cumples los mínimos)")
        else:
            partes.append(f"Para el 5: ≥ {fmt(arriba(falta))} de media en lo que falta")
        partes += [f"en {e} ≥ {fmt(v)}" for e, v in extra if v > falta]
        partes.append(f"con un 10 en todo: {fmt((acc + 10 * resto) / total)}")
    return nota_actual, " · ".join(partes) + supuesto


def main() -> None:
    ver = "--ver" in sys.argv
    texto = NOTA.read_text(encoding="utf-8")
    secciones = {}
    for m in re.finditer(r"^## ([^\n]+?) · [^\n]*\n(.*?)(?=^## |\Z)", texto, re.M | re.S):
        t = tablas(m[2])
        if t:
            secciones[m[1].strip()] = t[0]

    m = re.search(r"^## Resumen\s*\n(.*?)(?=^## |^---|\Z)", texto, re.M | re.S)
    if not m:
        sys.exit("Notas-Uni.md no tiene sección ## Resumen")
    bloque = m[1]
    t = tablas(bloque)
    if not t:
        sys.exit("## Resumen sin tabla")
    cab, filas = t[0]
    col = {n.lower(): i for i, n in enumerate(cab)}
    ia, ifo = col.get("asignatura", 0), col.get("fórmula")
    imi, ina, ies = col.get("mínimos"), col.get("nota actual"), col.get("estado")
    if None in (ifo, ina, ies):
        sys.exit("## Resumen necesita las columnas Fórmula, Nota actual y Estado")

    lineas = ["| " + " | ".join(cab) + " |", "|" + "---|" * len(cab)]
    for f in filas:
        f += [""] * (len(cab) - len(f))
        asig = limpio(f[ia])
        if asig in secciones:
            cab_s, filas_s = secciones[asig]
            items, avisos = entregables(filas_s, cab_s, f[ifo])
            f[ina], f[ies] = calcular(items, f[imi] if imi is not None else "")
            if avisos:
                f[ies] += " · ⚠️ " + "; ".join(avisos)
        else:
            f[ina], f[ies] = "", f"⚠️ no encuentro la sección «## {asig} · …»"
        lineas.append("| " + " | ".join(f) + " |")
        if ver:
            print(f"{asig}: {f[ina] or '—'} · {f[ies]}")

    nueva = "\n".join(lineas) + "\n"
    inicio = bloque.index("|")
    fin = bloque.rindex("|") + 1
    texto_nuevo = texto[: m.start(1) + inicio] + nueva.rstrip("\n") + texto[m.start(1) + fin:]
    if not ver and texto_nuevo != texto:
        write_atomic(NOTA, texto_nuevo)


if __name__ == "__main__":
    main()
