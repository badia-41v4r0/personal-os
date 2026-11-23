// Nombre que el usuario ha puesto a su asistente (Ajustes → Tú y tu cuenta). El panel lo fija al cargar la configuración de
// la instancia y no pinta nada hasta tenerlo, así que los textos siempre salen con el nombre bueno.
let nombre = "Jarvis";

export const asistente = () => nombre;

export function setAsistente(n: string | null | undefined) {
  nombre = n?.trim() || "Jarvis";
}
