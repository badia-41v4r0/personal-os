"""Nombre de la instancia: separa varias instalaciones en el mismo PC (contenedores, imágenes, etiquetas, unidades,
socket y cerrojos). Se elige con POS_INSTANCE; sin ella vale «jarvis», que es como se llamaba todo antes."""
import os
import re

INST = os.environ.get("POS_INSTANCE", "jarvis")
if not re.fullmatch(r"[a-z][a-z0-9-]{1,15}", INST):
    raise SystemExit(f"POS_INSTANCE no válido: {INST!r} (minúsculas, cifras y guiones; de 2 a 16 caracteres)")
