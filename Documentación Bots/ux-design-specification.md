# Especificación UX/UI de Interfaces Conversacionales de Usuario

**Cliente:** Grupo Petroil — División Gas (Mazatlán, Sinaloa)  
**Versión:** 3.5.0 Enterprise — Consolidada con el Diseño Conversacional Real (Telegram, WhatsApp, Facebook Messenger e Instagram Direct)  
**Estado:** Documento Maestro de Diseño UX/UI Aprobado y Vigente  
**Fuentes Oficiales de Verdad:** `product-context.md`, `prd.md`, `user-flows.md`, `telegram_bot.py` y `src/channels/`  
**Fecha:** Octubre 2026  

---

## 1. Filosofía de Diseño Conversacional y Guía de Estilo

Las interfaces conversacionales de **Gas a Tu Puerta - Petroil** están diseñadas bajo el principio de **Cero Fricción y Máxima Certeza Operativa**:
> *"El usuario debe poder completar su pedido de gas en menos de 60 segundos, utilizando la menor cantidad de pulsaciones posibles, sin confusiones sobre precios y con confirmación visual inequívoca en cada etapa."*

### 1.1. Tono de Voz Institucional
* **Cercano, Amable y Profesional:** Saludos respetuosos (*"¡Hola! Bienvenido a Gas a tu Puerta de Grupo Petroil"*), reconociendo al cliente por su nombre de pila si ya se encuentra registrado en el sistema.
* **Directo y Libre de Ambigüedades:** Mensajes concisos ($\le 3$ párrafos cortos), evitando textos densos que requieran desplazamiento vertical innecesario en pantallas móviles.
* **Afín a la Cultura de Mazatlán:** Lenguaje claro y familiar para la región de Sinaloa (términos como "cilindro", "tanque estacionario", "repartidor", "pipa", "camioneta", "folio de servicio").

### 1.2. Sistema de Tokens Visuales y Emojis Semánticos
Para mejorar la legibilidad y escaneo visual rápido en chats móviles, se asignan emojis con significado estricto y unificado:

| Emoji | Significado Semántico | Ejemplo de Uso en Interfaz |
| :---: | :--- | :--- |
| 🛢️ | Servicio o producto de Cilindro de Gas LP | `[ 🛢️ Cilindros de Gas ]` |
| 🔥 | Servicio de recarga a Tanque Estacionario | `[ 🔥 Tanque Estacionario ]` |
| 🟢 / 🔵 | Indicador visual de cilindros populares | `🟢 Cilindro 30 kg`, `🔵 Cilindro 20 kg` |
| 📍 | Ubicación geográfica, GPS o dirección | `📍 Entregar en: Av. Delfín #402` |
| 🕒 / ⚡ | Horario o inmediatez de despacho | `⚡ Lo antes posible`, `🕒 Programar hora` |
| 💵 / 💳 / 📱 | Métodos de pago aceptados | `💵 Efectivo`, `💳 Tarjeta`, `📱 Transferencia` |
| ✅ | Confirmación afirmativa o estatus exitoso | `[ ✅ Confirmar Pedido ]`, `✅ Entregado` |
| ❌ | Cancelación o rechazo explícito | `[ ❌ Cancelar ]`, `[ ❌ No deseo programar ]` |
| ✏️ | Edición o modificación de borrador | `[ ✏️ Modificar Algo ]` |
| 🛒 | Carrito de compras multi-producto | `🛒 Tu selección actual (2 productos)` |
| 🚛 / 💨 | Camioneta o chofer en ruta de entrega | `🚛 Tu repartidor Juan va en camino...` |
| ⭐ | Calificación del servicio (CSAT) | `[ ⭐⭐⭐⭐⭐ ] Excelente servicio` |

### 1.3. Reglas de Formato Numérico y Divisas
* **Moneda:** Siempre se expresa con signo de pesos, separador de miles con coma y dos decimales, acompañado del código de divisa: `$670.00 MXN`.
* **Teléfonos:** Formato agrupado para fácil lectura humana: `669-123-4567`.
* **Separadores Estructurales:** En tarjetas de resumen se utiliza la línea de caracteres continuos `═══════════════════════════════` para delimitar bloques financieros.

---

## 2. Especificación de Componentes UI por Plataforma

---

### 2.1. Telegram User Bot (`telegram_bot.py`)

* **Componente 1: Botones Inline (`InlineKeyboardMarkup`):**
  - **Distribución de Rejilla:** Cuadrícula de 2 columnas para el catálogo de cilindros (30 kg y 20 kg arriba; 45 kg y 10 kg abajo) para mantener el menú compacto.
  - **Límite de `callback_data`:** Máximo 64 bytes por botón, utilizando prefijos compactos (`srv_`, `prod_`, `addr_`, `pay_`, `rate_`).
  - **Reemplazo en Caliente:** Para evitar que el usuario presione botones antiguos en el historial del chat, el bot edita el mensaje anterior removiendo el teclado (`edit_message_reply_markup(reply_markup=None)`) al avanzar de estado.
* **Componente 2: Teclado de Entrada (`ReplyKeyboardMarkup`):**
  - Botón táctil para compartir número de contacto nativo:
    `KeyboardButton("📱 Compartir mi Teléfono en 1 Toque", request_contact=True)`
  - Botón táctil para compartir ubicación satelital:
    `KeyboardButton("📍 Enviar mi Ubicación GPS", request_location=True)`
  - Configuración: `resize_keyboard=True`, `one_time_keyboard=True` para que el teclado se oculte automáticamente tras su uso.

---

### 2.2. WhatsApp Cloud API (`src/channels/whatsapp/`)

* **Componente 1: Mensajes de Lista Interactiva (`type: list`):**
  - Utilizados obligatoriamente para catálogos con más de 3 opciones y libretas de direcciones.
  - **Restricciones de Meta API:**
    * Texto del botón principal (`button`): Máximo 20 caracteres (ej. `"Ver Opciones"`, `"Elegir Dirección"`).
    * Secciones: 1 sección obligatoria (`title` $\le 24$ caracteres, ej. `"Capacidades Oficiales"`).
    * Filas (`rows`): Hasta 10 elementos.
    * Título de fila (`title`): Máximo 24 caracteres (ej. `"Cilindro de 30 kg"`).
    * Descripción de fila (`description`): Máximo 72 caracteres (ej. `"$670.00 MXN — Ideal para hogares"`).
* **Componente 2: Botones Interactivos de Respuesta Rápida (`type: button`):**
  - Utilizados para selección de servicio, métodos de pago y confirmación.
  - **Restricciones de Meta API:**
    * Máximo 3 botones por mensaje.
    * Título de cada botón (`title`): Máximo 20 caracteres exactos.
* **Componente 3: Tarjetas de Ubicación Nativa (`type: location`):**
  - Envía las coordenadas del centro de distribución o la ubicación del repartidor con nombre del punto y dirección legible.

---

### 2.3. Facebook Messenger (`src/channels/messenger/`)

* **Componente 1: Plantillas Genéricas / Carruseles (`Generic Template`):**
  - Carrusel horizontal con tarjetas visuales de cilindros.
  - Cada elemento contiene:
    * `title`: Nombre del producto (ej. `"Cilindro Portátil 30 kg"`).
    * `subtitle`: Precio y descripción (ej. `"$670.00 MXN | Llenado garantizado"`).
    * `image_url`: Fotografía oficial del cilindro Petroil en alta definición.
    * `buttons`: Botón de acción tipo postback con título `"Seleccionar"` y payload `"prod_cyl_30"`.
* **Componente 2: Quick Replies:**
  - Botones deslizables en la parte inferior del chat para selección de método de pago o confirmación (`[ ✅ Confirmar ]`, `[ ✏️ Modificar ]`, `[ ❌ Cancelar ]`).
  - Botón especial `content_type: "location"` para solicitar las coordenadas GPS del cliente en un solo toque.

---

### 2.4. Instagram Direct (`src/channels/instagram/`)

* **Componente 1: Quick Replies Deslizables (Hasta 13 Opciones):**
  - En Instagram Direct, los Quick Replies se presentan como una barra horizontal deslizable.
  - Ideal para seleccionar entre múltiples direcciones guardadas o franjas horarias de entrega.
* **Componente 2: Fichas de Producto en Mensajes Directos:**
  - Envío de tarjetas con desglose visual de peso, precio y botón de compra directa.
* **Componente 3: Respuestas en Hilo (DM Replies):**
  - El bot cita o responde directamente al mensaje del usuario, manteniendo el contexto claro si el cliente envía varios mensajes seguidos.

---

## 3. Copywriting Oficial y Plantillas de Mensajes

---

### 3.1. Bienvenida y Tipo de Servicio
```text
¡Hola! 👋 Te damos la bienvenida a Gas a tu Puerta de Grupo Petroil en Mazatlán.

Estamos listos para llevar tu gas hasta la puerta de tu hogar o negocio. 🚛💨
¿Qué tipo de servicio necesitas hoy?
```
*(Botones: `[ 🛢️ Cilindros de Gas ]` | `[ 🔥 Tanque Estacionario ]`)*

---

### 3.2. Catálogo de Cilindros y Carrito
```text
Selecciona la capacidad de cilindro que requieres. Precios oficiales vigentes en Mazatlán:
```
*(Opciones: `[ 🟢 30 kg — $670.00 ]`, `[ 🔵 20 kg — $447.00 ]`, `[ ⚪ 45 kg — $1,005.00 ]`, `[ 🟡 10 kg — $224.00 ]`)*

**Actualización del Carrito:**
```text
🛒 Tu carrito actual:
• 2x Cilindro de 30 kg — $1,340.00 MXN

💰 Total: $1,340.00 MXN (2 cilindros)
```
*(Botones: `[ ➕ Agregar otro ]` | `[ 🧹 Vaciar ]` | `[ ➡️ Continuar con el Pedido ]`)*

---

### 3.3. Selección de Domicilio
* **Para Cliente con Libreta:**
  ```text
  Hemos localizado tu historial. ¿A cuál de tus domicilios registrados enviamos el pedido?
  ```
  *(Botones: `[ 📍 Casa: Av. Delfín #402 ]` | `[ 📍 Negocio: Belisario D. #12 ]` | `[ ➕ Enviar otra dirección ]`)*
* **Para Cliente Nuevo:**
  ```text
  📍 ¿En qué domicilio de Mazatlán entregaremos tu gas?
  
  Puedes tocar el botón de abajo para enviar tu ubicación GPS exacta o escribir tu calle, número exterior y colonia.
  ```
  *(Botón nativo: `[ 📍 Compartir mi Ubicación GPS ]`)*

---

### 3.4. Horarios y Fuera de Servicio
* **Dentro de Horario:**
  ```text
  ¿En qué horario prefieres recibir tu gas?
  ```
  *(Botones: `[ ⚡ Lo antes posible (30-45 min) ]` | `[ 📅 Programar Entrega ]`)*
* **Fuera de Horario:**
  ```text
  🌙 En este momento nuestras unidades se encuentran fuera de horario de reparto.
  Atendemos de Lunes a Sábado de 7:00 AM a 7:00 PM y Domingos de 8:00 AM a 3:00 PM.
  
  ¿Deseas programar tu pedido para mañana a primera hora (8:00 AM)?
  ```
  *(Botones: `[ 📅 Sí, programar para mañana ]` | `[ ❌ No, gracias ]`)*

---

### 3.5. Formas de Pago
```text
¿Cómo deseas liquidar tu pedido al momento de la entrega?
```
*(Botones: `[ 💵 Efectivo ]` | `[ 💳 Tarjeta (Terminal) ]` | `[ 📱 Transferencia SPEI ]`)*

---

### 3.6. Resumen Financiero y Confirmación Obligatoria
```text
📋 RESUMEN DE TU PEDIDO — PETROIL GAS
═══════════════════════════════════════
🛢️ Producto: 1x Cilindro de 30 kg
💰 Total a Pagar: $670.00 MXN
📍 Domicilio: Av. Delfín #402, Fracc. Alarcón
🕒 Entrega: Lo antes posible (30-45 min)
💳 Método de Pago: Efectivo
👤 Titular: María González (669-123-4567)
═══════════════════════════════════════
Por favor, revisa que los datos sean correctos para enviar tu unidad.
```
*(Botones: `[ ✅ Confirmar Pedido ]` | `[ ✏️ Modificar Algo ]` | `[ ❌ Cancelar ]`)*

---

### 3.7. Confirmación de Pedido Exitoso
```text
🎉 ¡Excelente! Tu pedido ha sido confirmado con éxito.
🏷️ Folio de Servicio: #10482

Tu orden ya está en nuestra central de despacho de Petroil Mazatlán.
Te avisaremos por este mismo chat en cuanto tu chofer asignado vaya en camino. 🚛💨
```

---

### 3.8. Notificaciones de Despacho y Entrega
* **Asignado:**
  ```text
  🚛 ¡Tu unidad ha sido asignada!
  Chofer: Juan Pérez
  Unidad: Camioneta #14 (Placas: VZ-4821-A)
  ```
* **En Ruta:**
  ```text
  📍 ¡Tu repartidor ya va en camino hacia tu domicilio!
  Tiempo estimado de llegada: 10 a 15 minutos. Por favor ten despejado el acceso a tu cilindro.
  ```
* **Entregado:**
  ```text
  ✅ ¡Servicio concluido!
  Tu gas ha sido entregado exitosamente. Importe cobrado: $670.00 MXN.
  ```

---

### 3.9. Encuesta de Calidad CSAT
```text
🌟 En Grupo Petroil tu opinión es lo más importante.
¿Cómo calificarías la rapidez y atención de tu repartidor hoy?

[ ⭐ ]  [ ⭐⭐ ]  [ ⭐⭐⭐ ]  [ ⭐⭐⭐⭐ ]  [ ⭐⭐⭐⭐⭐ ]
```
* **Respuesta a 4-5 estrellas:** *"¡Muchas gracias por tu calificación! Nos alegra haberte brindado un servicio de calidad. ¡Hasta la próxima recarga!"*
* **Respuesta a 1-3 estrellas:** *"Lamentamos que tu experiencia no haya sido perfecta. Tu opinión nos ayuda a mejorar. ¿Podrías indicarnos brevemente qué ocurrió (demora, trato o producto)?"*

---

## 4. Matriz de Errores, Recuperación y Fallbacks

| Error o Excepción | Causa Probable | Mensaje de Recuperación UX | Acción del Sistema |
| :--- | :--- | :--- | :--- |
| **Teléfono Inválido** | Usuario escribe letras o menos de 10 dígitos | *"El número debe ser de 10 dígitos (ej. 6691234567). Por favor, ingrésalo nuevamente:"* | Permanece en `WAITING_FOR_PHONE` |
| **Dirección no Localizada** | Calle inexistente o colonia fuera de Mazatlán | *"No pudimos ubicar con precisión esa dirección en Mazatlán. ¿Podrías indicarnos colonia y entre qué calles se encuentra, o enviarnos tu ubicación GPS?"* | Reabre botón de GPS nativo y texto de referencias |
| **Audio Inaudible o con Ruido** | Viento fuerte o audio vacío en Whisper | *"No alcanzamos a escuchar con claridad tu nota de voz. 🎤 ¿Podrías grabarla de nuevo o escribir tu pedido en texto?"* | Mantiene el estado actual |
| **Interrupción de Sesión** | Usuario abandona el chat a la mitad del flujo | Al volver a escribir: *"Tenías un pedido en proceso para 1x Cilindro de 30 kg. ¿Deseas continuarlo o empezar de nuevo?"* | Botones `[ Continuar ]` y `[ Reiniciar ]` |
| **Fallo Temporal de API Externa** | Meta API o Telegram experimenta lentitud | *"Estamos experimentando una breve interrupción en la red. Tu pedido no se ha perdido; reintentando en un momento..."* | Reintento automático asíncrono con backoff |
