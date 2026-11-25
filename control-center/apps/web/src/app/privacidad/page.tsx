// Página pública que pide Enable Banking (privacy URL) al registrar la aplicación. Sin datos de nadie.
export default function PrivacidadPage() {
  return (
    <main className="mx-auto max-w-2xl space-y-4 p-6 text-sm leading-relaxed">
      <h1 className="text-lg font-semibold">Privacidad</h1>
      <p>Personal OS es un panel personal que cada persona instala en su propio ordenador. No es un servicio para terceros.</p>
      <p>
        Si conectas tu banco, el panel lee tus saldos y movimientos (solo lectura, con tu permiso y a través de Enable Banking) y los guarda en
        tu propia instalación para tu contabilidad personal. No se comparten, no se venden y no salen de tu equipo salvo hacia el proveedor de IA que tú
        hayas configurado, si le pides un análisis.
      </p>
      <p>Puedes retirar el permiso cuando quieras desde tu banco o desde Finanzas, y borrar los datos de tu instalación.</p>
    </main>
  );
}
