// Puente del programador: su contenedor no tiene red y las herramientas solo saben hablar con un proxy por TCP.
// Escucha en 127.0.0.1 y lo pasa al socket del proxy de salida. No decide nada: las reglas están en el proxy.
const net = require("net");
net.createServer((c) => {
  const up = net.connect("/run/egress/proxy.sock");
  c.pipe(up).pipe(c);
  const cierra = () => { c.destroy(); up.destroy(); };
  c.on("error", cierra); up.on("error", cierra);
}).listen(3128, "127.0.0.1");
