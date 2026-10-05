# Contexto: Puentes de Bots y Requerimiento de Servidor

## 1. ¿Cómo funcionan los "puentes" actualmente?
Los bots (Messenger y Telegram) y la PWA del chofer no se comunican de forma aislada, dependen de un backend central que procesa los pedidos y eventos:

- **Meta Messenger:** Meta envía las interacciones de los usuarios a través de una URL de Webhook (`/webhooks/messenger`).
- **PWA de Chofer y Tracking:** Cuando el chofer actualiza el pedido o su ubicación en la PWA, se envían eventos para notificar al cliente en tiempo real y mostrar la pantalla de seguimiento (`/tracking`).
- **Telegram:** Los bots de cliente y chofer consultan y envían eventos a este mismo backend.

Para realizar pruebas, se levantó un puente temporal mediante un túnel que conecta las peticiones de Internet directamente a una computadora local.

---

## 2. ¿Por qué dejó de funcionar?
Al estar montado el puente en una laptop de desarrollo:
- Mientras la computadora está encendida y con el túnel activo, los mensajes entran con normalidad.
- En cuanto la computadora se apaga, entra en suspensión o se desconecta de la red, el túnel se cierra. Meta y las demás plataformas intentan enviar los eventos, pero al no encontrar el servidor en línea, marcan error y el bot deja de responder.

---

## 3. ¿Qué necesitamos del compañero en el servidor?
Para que el sistema sea estable y funcione las 24 horas sin depender de ninguna computadora personal, se requiere:

1. **Alojar el backend en el servidor:**
   - Desplegar el proyecto de los bots en el mismo servidor donde ya están productivos los demás servicios de la empresa.

2. **Habilitar el acceso público (URL / Webhook):**
   - Proporcionar o configurar una URL pública con HTTPS (ya sea mediante un subdominio o una ruta dentro del dominio existente) que apunte al servicio de los bots.
   - Con esta URL fija, se configurará Meta for Developers de forma definitiva para que las notificaciones de Messenger, la PWA y el tracking queden enlazados de manera permanente.
