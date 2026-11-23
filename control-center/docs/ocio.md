# Ocio

Sección del panel (`/ocio/`) para el tiempo libre. Por ahora tiene un apartado, **Pelis y series**; las pestañas
dejan sitio para otros (libros, juegos…).

## Pelis y series

- **Estados:** `pendiente` (quiero verla), `viendo`, `vista`, `abandonada`. Pasar a *viendo* pone la fecha de inicio
  (y, en una serie, T1·E0); pasar a *vista* pone la de fin. Tu nota va de 1 a 10.
- **Series:** temporada y capítulo por los que vas. «+ Capítulo» avanza uno y, si se acaba la temporada (TMDB da los
  capítulos de cada una), pasa al 1 de la siguiente.
- **Ficha automática (TMDB):** al buscar y elegir un resultado se copian título, título original, año, sinopsis,
  géneros, duración (o temporadas, capítulos y estado de emisión), nota de TMDB y dónde verla en España (suscripción).
  «Actualizar info» la vuelve a pedir (temporadas nuevas, plataformas) sin tocar tu estado, nota ni progreso.
- **Carátulas:** se descargan al PC (`data/control-center/ocio/w342|w92/`) y el panel las sirve desde
  `/api/v1/me/ocio/imagen/...` (con sesión). El navegador nunca carga imágenes de fuera (la CSP lo impide) y lo
  guardado no depende de TMDB. Solo se aceptan nombres de archivo de TMDB (`[A-Za-z0-9_-].jpg|png`), tamaños `w92` y
  `w342` y hasta 3 MB.
- **Sin clave de TMDB** se añade a mano (título y tipo), sin carátula ni información.

Tabla `media_items` (migración `0019`), módulo `backend/app/modules/ocio.py`.

## Clave de TMDB

Token de lectura de la API v4 («API Read Access Token») de una cuenta gratuita de themoviedb.org, en
`data/control-center/secrets.env` como `CC_TMDB_TOKEN=…`. Lo usa solo el backend; nunca llega al navegador ni a los
agentes. Sin él, todo funciona salvo la búsqueda y la ficha automática.

Llamadas a TMDB: solo al buscar (con 350 ms de espera entre teclas), al añadir y al pulsar «Actualizar info».

## Jarvis y el chat del apartado

- Chat propio (`ocio`, `control-center/agents/ocio.md`), que solo ve su contenido: lecturas `ocio.list` y
  `ocio.search`, y acciones `ocio.add` y `ocio.update`. Jarvis, en Inicio, tiene las mismas.
- `ocio.add` (nivel 1, con deshacer): con `titulo` busca en TMDB y elige el resultado (exacto primero; `anio` y
  `tipo` desempatan). Con `tmdb_id` y `tipo` usa ese. Sin TMDB, lo guarda a mano si sabe el tipo.
- `ocio.update` (nivel 1, con deshacer): `estado`, `valoracion`, `temporada`, `capitulo`, `nota`, por `id` o por un
  título que coincida con uno solo.
- `ocio.search` cuenta como contenido externo (las sinopsis son de terceros): marca la ejecución, como el correo.

## Pruebas

- `backend/tests/test_ocio.py` (TMDB simulado): búsqueda, ficha, duplicados, fechas por estado, alta a mano, actualizar
  sin perder lo tuyo, validación de imágenes y acciones de Jarvis con deshacer.
- `apps/web/e2e/ocio.spec.ts`: búsqueda y carátula con la API simulada en el navegador; con `CC_E2E_OCIO_MUTA=1` (solo
  contra un backend de prueba sin token), alta a mano, valoración y quitar.
