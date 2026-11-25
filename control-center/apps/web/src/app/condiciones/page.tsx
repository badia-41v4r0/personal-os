// Página pública que pide Enable Banking (terms URL) al registrar la aplicación. Sin datos de nadie.
export default function CondicionesPage() {
  return (
    <main className="mx-auto max-w-2xl space-y-4 p-6 text-sm leading-relaxed">
      <h1 className="text-lg font-semibold">Condiciones de uso</h1>
      <p>Personal OS es software libre para uso personal y no comercial: cada persona lo instala y lo usa en su propio equipo, bajo su responsabilidad.</p>
      <p>
        La conexión con el banco es de solo lectura: el panel nunca puede mover dinero ni iniciar pagos. Las cifras que muestra son una ayuda para
        llevar tus cuentas y pueden contener errores; la referencia es siempre tu banco.
      </p>
    </main>
  );
}
