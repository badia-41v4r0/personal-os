// Ruta base de la web. Vacía en el panel; «/vista-previa» en la vista previa del Constructor, que se compila con
// NEXT_PUBLIC_BASE_PATH y se sirve detrás del panel real. Next la pone sola en <Link> y el router; aquí, para lo demás
// (fetch, WebSocket, enlaces de descarga e imágenes de la API).
export const BASE = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
export const EN_VISTA_PREVIA = BASE !== "";
