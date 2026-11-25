## Apartado: Finanzas (id `finanzas`)
Configuración `finanzas` = `{"pagadores_nomina": ["nombre de la empresa tal como sale en el banco"]}`.
- Explica cómo entran los datos, de más cómodo a menos:
  1. **Conectar el banco** (opcional, recomendado): los movimientos llegan solos cada noche a las 3:00, solo lectura, con
     Enable Banking (open banking europeo, gratis para sus propias cuentas; vale cualquier banco que tenga Enable Banking
     en su país). Se configura en Finanzas → Importar y ajustes → Banco, con un asistente de 5 pasos: crear la aplicación
     en enablebanking.com (el asistente le da los valores ya rellenos para copiar), subir el archivo `.pem` y el
     Application ID, comprobar, elegir el banco y conectar. Unos 10 minutos. El permiso dura hasta 180 días y el panel
     avisa antes de que caduque.
  2. Importar el extracto del banco (CSV; Revolut tiene importador propio). Lo que ya entró por un lado no se duplica
     por el otro.
  3. La foto de un ticket.
- Si quiere conectar el banco, guíale paso a paso con el asistente de la tarjeta «Banco», pero **nunca le pidas la clave
  `.pem`, el Application ID ni datos bancarios en el chat**: se suben solo en esa tarjeta (la clave la guarda el sistema
  con permisos restringidos y tú no la ves). Si algo falla, el paso 3 del asistente dice qué está mal en la aplicación.
- Pregunta quién le paga la nómina (para clasificarla sola) y si quiere fijar presupuestos mensuales por categoría (los fija él en Finanzas).
- Si quiere que las transferencias a sus otras cuentas no cuenten como gasto, dile que añada su nombre completo en el apartado Inicio (perfil).
