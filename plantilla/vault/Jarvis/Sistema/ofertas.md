# Radar de ofertas: reglas

Lo usa `collectors/ofertas.py` cada mañana para puntuar las alertas de LinkedIn que llegan a Gmail. Edítalo cuando quieras: una palabra o frase por línea, en minúsculas. Se busca dentro del título (o del lugar).

## Puestos objetivo (+4)

## Puestos cercanos (+2)

## Descartar (aunque coincida lo de arriba)

## Extra IA (+1, solo a los puestos cercanos)

## Lugar bueno (+1)

## Lugar neutro (0)

Cualquier otro lugar (otra ciudad, presencial) resta 2. Se muestran las ofertas con 2 puntos o más.

## Reclutadores (remitentes o palabras del asunto)
Correos de las últimas 48 h en Gmail que no son alertas automáticas.
