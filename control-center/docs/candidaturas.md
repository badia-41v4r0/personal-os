# Candidaturas con agente (fase 4)

El agente prepara el formulario de una candidatura; **el usuario lo revisa y lo aprueba en Carrera**; solo entonces se pulsa «Enviar». Nada sale sin esa aprobación, y lo que sale es exactamente lo aprobado.

## Datos (migración 0017)
- `career_documents`: CV y cartas en `archivos/Carrera/`, con huella SHA-256 (sin duplicados), idioma y texto extraído (`pdftotext`). Archivar no borra el archivo.
- `applicant_profile`: lo único que el agente puede escribir en un formulario (contacto, ciudad, enlaces, permiso de trabajo, disponibilidad, pretensión, idiomas y respuestas estándar) y la lista **«nunca rellenar»**. Lo básico de esa lista (DNI, cuentas, salud, creencias…) no se puede quitar.
- `application_runs`: una solicitud. Estados: `en_cola → preparando → verificando → listo_para_revisar → aprobada → enviada`, o `fallida` / `abortada` / `rechazada` / `caducada` (pasa a manual).

## Flujo
1. **Carrera → Preparar solicitud** con la URL (https) y el CV. Como mucho una a la vez.
2. El backend crea un ordenador **`aplicaciones`** (`jarvis-vc:aplicaciones`): sin red propia, sale por un proxy con **solo** el dominio de la URL (el de la empresa o el del ATS) y unos CDN. La lista va en `allow.json`, en el volumen del proxy, que el ordenador no monta.
3. Lanza al agente **`solicitud`** (`control-center/agents/solicitud.md`) en una conversación propia. Solo puede leer la página (`vc_open_url`, `vc_page_text`, captura, scroll) y **rellenar por referencia** (`vc_form_fields`, `vc_form_fill`, `vc_form_attach`). No tiene terminal, ratón, teclado ni envío: la pasarela del Host Agent lo rechaza (`vms.APLICACIONES_OPS`). Solo adjunta el CV de esa solicitud, por su huella.
4. Termina con `candidatura.preparada` (o `candidatura.abortar` si hay captcha, inicio de sesión, SSO o un campo inesperado).
5. El backend **lee el formulario del navegador** (no se fía de lo que diga el agente) y lo descarta si hay bloqueos, si el botón no existe, si el formulario está en otro dominio o si un campo de «nunca rellenar» tiene valor. Si todo está bien, guarda la captura y crea la acción **`candidatura.aplicar`** (nivel 3 fijo, `actions.FIXED_LEVEL`: no se puede bajar desde el panel). El *payload* lleva todos los valores, el botón, el dominio, la huella del CV y la de la captura, así que la huella de la aprobación cubre exactamente lo que se envía. Llega un aviso push.
6. **Revisión en Carrera:** campos y valores, botón, CV, URL y captura. «Aprobar y enviar» o «Rechazar».
7. Al aprobar, el Host Agent (`POST /v1/vc/{id}/form/submit`, solo para el backend) **vuelve a leer el formulario y solo pulsa el botón si todos los valores siguen igual**. Si no, no envía nada y la solicitud queda fallida. Si se envía: candidatura a `aplicado`, follow-up a +7 días, evento en memoria y tabla de `Trabajo.md` rehecha. El ordenador se elimina al terminar (o caduca a las 26 h).

## Probado
- 16 pruebas de backend (`tests/test_candidaturas.py`), también en PostgreSQL, y 4 del Host Agent.
- **Navegador real** (contenedor aislado de `jarvis-vc:aplicaciones`, sin red, con un formulario local): lee los campos, no deja rellenar un botón, adjunta el CV, deja sin marcar los términos, **no envía** si un valor ha cambiado o el botón no existe, no sale nada antes de aprobar y, con el envío aprobado, llegan todos los datos y el CV.
- Proxy: sin lista, solo el campus (Canvas sigue igual); con lista, solo esos dominios y sin aceptar imitaciones (`evilgreenhouse.io`, `greenhouse.io.evil.com`).

## Límites y riesgos aceptados
- Dominios compartidos de ATS: permitir `greenhouse.io` permite también otras ofertas alojadas allí.
- El proxy hace TLS-MITM: ve el CV y los datos del formulario (se queda en el PC).
- Sin cuentas en portales: si piden iniciar sesión (LinkedIn Easy Apply incluido), pasa a manual. Las alertas de LinkedIn no dicen si una oferta tiene Easy Apply, así que el radar no lo guarda.
- No hay modo de solo lectura (el usuario lo quitó en Canvas el 02/11): el control es que el agente no tiene con qué pulsar «Enviar» y que el envío exige la huella aprobada.
- Las herramientas de desarrollo de Chromium no se pueden quitar por política: cortan el control por CDP. El agente no tiene teclado para abrirlas.
- Un turno de solicitud usa la web, pero sus únicas capacidades (`candidatura.preparada` y `candidatura.abortar`) no envían nada a terceros, así que no hace falta marcarlo como contaminado.
