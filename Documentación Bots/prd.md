# Product Requirements Document (PRD) — Bots de Usuario Omnicanal

**Cliente:** Grupo Petroil — División Gas (Mazatlán, Sinaloa)  
**Versión:** 3.5.0 Enterprise — Sincronizada con la Implementación Real de Bots de Cliente (Telegram, WhatsApp, Facebook Messenger e Instagram Direct)  
**Estado:** Documento Maestro Normativo Aprobado y en Operación  
**Fuentes Oficiales de Verdad:** `product-context.md`, `product-brief.md`, `telegram_bot.py` y el paquete `src/channels/`  
**Fecha:** Octubre 2026  

---

## Control de Versiones del Documento

| Versión | Fecha | Autor | Descripción del Cambio | Estado |
| :--- | :--- | :--- | :--- | :--- |
| **1.0.0** | 10/08/2026 | Equipo de Producto Petroil | Especificación preliminar de bot de ventas conversacional. | Superado |
| **2.0.0** | 22/08/2026 | Arquitectura & AI Team | Incorporación de flujos para WhatsApp Cloud API y Telegram. | Superado |
| **3.0.0** | 15/09/2026 | Antigravity AI | Integración de Facebook Messenger e Instagram Direct vía Meta Graph API. | Superado |
| **3.5.0** | 02/10/2026 | Antigravity AI & Equipo Petroil | **Consolidación Integral de los 4 Canales de Usuario:**<br>• Especificación exhaustiva de Telegram, WhatsApp, Messenger e Instagram.<br>• Carrito multi-producto interactivo y sumatoria de totales en tiempo real.<br>• Transcripción de audios mediante OpenAI Whisper across-channels.<br>• Geocodificación GPS satelital con Nominatim y resolución de direcciones.<br>• Manejo de ventanas de atención y reprogramación inteligente.<br>• Idempotencia con TTL de 10 minutos y validación criptográfica HMAC-SHA256.<br>• Encuestas CSAT de 1 a 5 estrellas con persistencia multi-proceso en `IdentityStore`. | **Aprobado / Vigente** |

---

# PARTE 1: FUNDAMENTOS Y CONTEXTO ESTRATÉGICO

---

## 1. Introducción y Propósito del Documento

### 1.1. Propósito
El presente **Product Requirements Document (PRD)** establece los requerimientos funcionales, técnicos, operativos y de seguridad para el subsistema de **Bots de Usuario Omnicanal** del ecosistema **Gas a Tu Puerta - Petroil**. Este documento rige el comportamiento de los agentes conversacionales desplegados en **Telegram**, **WhatsApp**, **Facebook Messenger** e **Instagram Direct**, asegurando una experiencia homogénea, rápida y libre de errores para el consumidor de Gas LP en Mazatlán.

### 1.2. Alcance Exclusivo
Este PRD se focaliza exclusivamente en los **canales de atención al cliente final**. No cubre la operación interna de los choferes en campo (`driver_bot.py`) ni las interfaces administrativas de la Torre de Control Web, excepto en los puntos de contacto e integración directa (notificaciones de estatus, despacho y encuestas de satisfacción).

---

## 2. Objetivos del Producto y Métricas de Éxito (KPIs)

| Métrica / KPI | Definición | Meta Target | Mecanismo de Medición |
| :--- | :--- | :---: | :--- |
| **Tiempo de Pedido (Time-to-Order)** | Duración total desde el inicio de interacción hasta la creación del folio | $< 75$ segundos | Timestamps de sesión en `FlowRouter` |
| **Tasa de Finalización de Compra** | Sesiones de compra iniciadas que terminan en confirmación exitosa | $\ge 82\%$ | Proporción de transiciones a `FlowState.COMPLETED` |
| **Tasa de Autonomía (Sin Humanos)** | Pedidos gestionados 100% por bot sin intervención de operadoras | $\ge 85\%$ | Pedidos originados por `channels/*` vs Torre de Control |
| **Resolución de Geocodificación** | Direcciones geocodificadas con éxito a coordenadas válidas | $\ge 96\%$ | Registros en tabla `orders` con lat/lng no nulos |
| **Precisión en Transcripción de Voz** | Audios procesados y entendidos correctamente por Whisper | $\ge 98\%$ | Logs del servicio `audio_transcription.py` |
| **Calificación de Servicio (CSAT)** | Promedio de satisfacción calificada en escala de 1 a 5 estrellas | $\ge 4.7 / 5.0$ ⭐ | Registros en tabla `order_ratings` |
| **Tasa de Error en Webhooks** | Porcentaje de fallos en procesamiento de eventos entrantes de Meta | $< 0.1\%$ | Respuestas HTTP 500 en logs de FastAPI |

---

# PARTE 2: REQUERIMIENTOS FUNCIONALES GENERALES (CROSS-CHANNEL)

Todos los bots de usuario deben cumplir estrictamente los siguientes requerimientos funcionales unificados a través del enrutador central `flow_router.py`:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                      MÁQUINA DE ESTADOS CONVERSACIONAL (FlowState)                     │
├───────────────────────────────┬────────────────────────────────────────────────────────┤
│ ESTADO (FlowState)            │ ACCIÓN / RESPUESTA DEL BOT                             │
├───────────────────────────────┼────────────────────────────────────────────────────────┤
│ INITIAL                       │ Saludo de bienvenida institucional y tipo de servicio  │
│ WAITING_FOR_PRODUCT_OR_QTY    │ Despliegue de catálogo y selector de cantidades (+/-)  │
│ WAITING_FOR_STATIONARY_DETAILS│ Captura de importe en pesos ($) o litros de gas estac. │
│ WAITING_FOR_PHONE             │ Solicitud y validación de teléfono celular a 10 dígitos│
│ WAITING_FOR_ADDRESS_SELECTION │ Botones de direcciones guardadas o solicitud de nueva  │
│ WAITING_FOR_NEW_CUSTOMER_NAME │ Captura de nombre del titular si es usuario nuevo      │
│ WAITING_FOR_NEW_CUSTOMER_ADDR │ Captura de calle, número y referencias o GPS nativo    │
│ WAITING_FOR_SCHEDULE          │ Selección de "Lo antes posible" o fecha programada     │
│ WAITING_FOR_PAYMENT_METHOD    │ Opciones: Efectivo, Tarjeta (Terminal) o Transferencia │
│ WAITING_FOR_CONFIRMATION      │ Tarjeta resumen financiero y botón Confirmar / Cancelar│
│ COMPLETED                     │ Pedido generado con Folio #XXXXX y seguimiento activo  │
└───────────────────────────────┴────────────────────────────────────────────────────────┘
```

---

### RF-01: Detección y Bienvenida al Usuario
* **Descripción:** Al recibir cualquier saludo o interacción inicial (`/start`, "hola", "buenas tardes", audio de saludo o emoji), el bot debe identificar al usuario en `IdentityStore` y responder con el saludo oficial de Grupo Petroil.
* **Criterios:**
  - Si el usuario ya cuenta con pedidos previos registrados, el bot debe saludarlo cordialmente por su nombre (ej. *"¡Hola de nuevo, Sra. María! Bienvenido a Gas a tu Puerta de Grupo Petroil"*).
  - Desplegar inmediatamente la selección de tipo de servicio sin textos ambiguos.

---

### RF-02: Selección de Tipo de Servicio
* **Descripción:** El bot debe presentar de manera visible y excluyente las dos modalidades de suministro de gas disponibles en Petroil.
* **Criterios:**
  - Opción 1: `[ 🛢️ Cilindros ]` (Gas LP en cilindro portátil).
  - Opción 2: `[ 🔥 Tanque Estacionario ]` (Recarga por litro con pipa).
  - La interacción debe ejecutarse mediante botones nativos de la plataforma correspondiente.

---

### RF-03: Catálogo Dinámico y Carrito Multi-Producto
* **Descripción:** Los precios y productos deben ser leídos en tiempo real desde la base de datos relacional de Petroil, garantizando cero discrepancias tarifarias.
* **Criterios:**
  - Para Cilindros: Mostrar capacidades estándar (10 kg, 20 kg, 30 kg, 45 kg) con su precio oficial vigente en moneda nacional (MXN).
  - Carrito Interactivo: Permitir agregar más de un cilindro (ej. 2 de 30 kg + 1 de 20 kg) mediante botones de incremento (`+`), decremento (`-`) y vaciado de carrito.
  - Para Tanque Estacionario: Permitir indicar importe en pesos (ej. "$800 pesos") o cantidad de litros, con un consumo mínimo configurable (ej. mínimo $500 MXN).

---

### RF-04: Captura y Validación de Teléfono a 10 Dígitos
* **Descripción:** El número telefónico es la llave canónica del cliente.
* **Criterios:**
  - En WhatsApp: Se toma automáticamente del identificador `wa_id` (removiendo el prefijo de país `52` o `521`).
  - En Telegram: Se ofrece el botón nativo de compartir contacto (`request_contact=True`) o escritura manual.
  - En Messenger e Instagram: Se solicita escribirlo a 10 dígitos.
  - Validación: Expresión regular estricta `^[0-9]{10}$`. Si el usuario ingresa caracteres no numéricos o longitudes distintas a 10 dígitos, el bot debe emitir un mensaje de corrección guiado.

---

### RF-05: Gestión Inteligente de Direcciones
* **Descripción:** El sistema debe minimizar la fricción de entrada de direcciones y garantizar geocodificación satelital precisa.
* **Criterios:**
  - **Clientes Recurrentes:** Desplegar botones con las direcciones registradas previamente (ej. `[ 📍 Casa: Av. Delfín #402 ]`, `[ 📍 Local: Av. Ejército Mexicano #12 ]`) más una opción `[ ➕ Nueva Dirección ]`.
  - **Clientes Nuevos o Domicilio Nuevo:** Permitir compartir la **ubicación GPS en tiempo real** nativa de la app (Telegram, WhatsApp o Messenger) o escribir la dirección en texto plano con calle, número exterior, colonia y entrecalles.
  - **Geocodificación Satelital:** Procesar la dirección con Nominatim OpenStreetMap acotado a Mazatlán. Si la geocodificación devuelve coordenadas válidas, asociarlas al pedido.
  - **Borrado de Direcciones:** Si el usuario solicita olvidar o borrar un domicilio, el sistema lo añade a `_deleted_addresses` en `IdentityStore` para no volver a sugerirlo.

---

### RF-06: Verificación de Horarios de Atención y Programación
* **Descripción:** El sistema debe respetar las ventanas de operación comercial de Petroil Mazatlán.
* **Criterios:**
  - El servicio `schedule_manager.py` evalúa la hora local actual de Mazatlán (Zona Horaria `America/Mazatlan`).
  - Si la compra ocurre dentro del horario de despacho: Presentar opciones `[ ⚡ Lo antes posible ]` (entrega inmediata promedio 30-45 min) y `[ 📅 Programar Entrega ]`.
  - Si ocurre fuera de horario: El bot debe informar cortésmente el horario de apertura (ej. 7:00 AM) y ofrecer agendar el pedido para el primer turno de la mañana siguiente.

---

### RF-07: Selección de Métodos de Pago
* **Descripción:** El cliente debe definir cómo liquidará su pedido al momento de la entrega física.
* **Criterios:**
  - Opciones obligatorias:
    1. `[ 💵 Efectivo ]`: Preguntar si requiere cambio de alguna denominación (ej. "¿Pagas con billete de $500 o $1,000?").
    2. `[ 💳 Tarjeta (Terminal) ]`: Informa que el repartidor llevará terminal bancaria móvil para cobro con tarjeta de débito/crédito.
    3. `[ 📱 Transferencia SPEI ]`: Proporciona la CLABE interbancaria institucional de Petroil indicando que el comprobante se muestra al chofer.

---

### RF-08: Resumen Financiero Estructurado y Confirmación Obligatoria
* **Descripción:** Ningún pedido debe registrarse en la base de datos sin una confirmación explícita y afirmativa del cliente.
* **Criterios:**
  - El bot debe presentar una tarjeta resumen con:
    * Productos y cantidades seleccionadas.
    * Precio unitario y Total a pagar en MXN.
    * Dirección de entrega exacta con referencias.
    * Horario de entrega pactado.
    * Método de pago acordado.
  - Botones de acción final:
    * `[ ✅ Confirmar Pedido ]`: Crea formalmente la orden en base de datos (`create_order`) y asigna Folio #XXXXX.
    * `[ ✏️ Modificar ]`: Permite cambiar productos, dirección o método de pago.
    * `[ ❌ Cancelar ]`: Aborta el flujo y limpia el borrador en memoria.

---

### RF-09: Notificaciones de Estado en Tiempo Real (Push por Canal)
* **Descripción:** El cliente debe recibir actualizaciones automáticas en el mismo hilo de chat donde realizó la compra.
* **Criterios:**
  - Evento 1: **Pedido Asignado:** Notifica cuando un chofer toma el viaje, indicando nombre del operador y placas del vehículo.
  - Evento 2: **Chofer en Camino (`in_route`):** Notifica que el vehículo va en ruta hacia el domicilio, adjuntando enlace de visualización o ubicación estimada.
  - Evento 3: **Pedido Entregado (`delivered`):** Notifica la finalización exitosa del servicio y el importe liquidado.

---

### RF-10: Encuesta de Calidad CSAT Post-Entrega
* **Descripción:** Medición sistemática de la satisfacción del cliente tras la entrega física.
* **Criterios:**
  - Al registrarse el estado `delivered`, el bot envía automáticamente un mensaje interactivo con calificación en escala de 1 a 5 estrellas:
    `[ ⭐ ]  [ ⭐⭐ ]  [ ⭐⭐⭐ ]  [ ⭐⭐⭐⭐ ]  [ ⭐⭐⭐⭐⭐ ]`
  - Si el usuario califica con 4 o 5 estrellas: Mensaje de agradecimiento institucional.
  - Si el usuario califica con 1, 2 o 3 estrellas: Mensaje empático solicitando indicar brevemente el motivo (ej. demora, trato del chofer o fuga en válvula).
  - Las calificaciones se almacenan en la tabla `order_ratings` y en `IdentityStore`.

---

### RF-11: Transcripción Automática de Notas de Voz (Whisper)
* **Descripción:** Los usuarios deben poder enviar notas de voz en lugar de texto en cualquier etapa del flujo.
* **Criterios:**
  - El bot descarga el archivo de audio desde los servidores de Telegram o Meta.
  - Se remite al servicio `audio_transcription.transcribe_audio_file` (Whisper).
  - El texto resultante se procesa en el enrutador determinista. Si contiene una intención clara (ej. *"Tráeme un tanque de 30 kilos a Pradera Dorada"*), el bot salta los pasos innecesarios y prellena el borrador.

---

### RF-12: Consulta de Estatus y Cancelación Asistida
* **Descripción:** Si el cliente escribe *"¿dónde viene mi gas?"* o *"estatus de mi pedido"*, el bot debe consultar el último pedido activo de ese número de teléfono y devolver el estado actual, chofer asignado y tiempo estimado sin iniciar un nuevo proceso de compra.
* **Cancelación:** Permitir cancelar el pedido únicamente si aún se encuentra en estado `pending` o `assigned`. Si el chofer ya está `in_route`, notificar que la pipa/camioneta está por llegar y conectar con la Torre de Control.

---

# PARTE 3: ESPECIFICACIONES TÉCNICAS PARTICULARES POR CANAL

---

## 3.1. Bot de Usuario en Telegram (`telegram_bot.py`)

* **Librería y Arquitectura:** `python-telegram-bot` v20.7+ con ejecución asíncrona sobre `HTTPXRequest`.
* **Manejo de Callback Queries:** Cada botón inline envía un `callback_data` con prefijo estructurado:
  - `srv_cilindro`, `srv_estacionario`
  - `prod_cyl_10`, `prod_cyl_20`, `prod_cyl_30`, `prod_cyl_45`
  - `addr_sel_{id}`, `addr_new`
  - `sched_asap`, `sched_custom`
  - `pay_cash`, `pay_card`, `pay_transfer`
  - `order_confirm`, `order_cancel`, `order_edit`
  - `rate_{order_id}_{stars}`
* **Teclados Nativo de Contacto y GPS:**
  ```python
  ReplyKeyboardMarkup(
      [
          [KeyboardButton("📍 Enviar mi Ubicación GPS", request_location=True)],
          [KeyboardButton("📱 Compartir mi Teléfono", request_contact=True)],
      ],
      resize_keyboard=True,
      one_time_keyboard=True,
  )
  ```
* **Limpieza de Interfaz:** Para evitar acumulación de teclados obsoletos, el bot elimina o edita el mensaje anterior con `edit_message_reply_markup` al avanzar de estado.

---

## 3.2. Bot de Usuario en WhatsApp Cloud API (`src/channels/whatsapp/`)

* **Protocolo:** Meta Graph API v21.0 vía endpoints HTTPS en FastAPI:
  - `GET /channels/whatsapp/webhook`: Validación de token con `hub.mode == "subscribe"` y retorno de `hub.challenge`.
  - `POST /channels/whatsapp/webhook`: Recepción de eventos de mensajería (textos, interactivos, ubicaciones, audios).
* **Mensajes Interactivos:**
  - **List Messages (`type: list`):** Utilizados para el catálogo de cilindros y libreta de direcciones. Permite 1 sección y hasta 10 opciones con título y descripción (ej. precio y peso).
  - **Button Messages (`type: button`):** Utilizados para selección de servicio, métodos de pago y confirmación. Límite estricto de Meta: máximo 3 botones por mensaje, títulos $\le 20$ caracteres.
* **Carrito Interactivo en Memoria (`wa_carts`):**
  - Mantiene el diccionario `wa_id -> {prod_id: quantity}`.
  - Al tocar un producto, se incrementa y se reenvía el resumen con botones `[ ➕ Agregar otro ]`, `[ 🧹 Vaciar ]` y `[ ➡️ Continuar ]`.
* **Resiliencia de Token (401 Retry):**
  - Si Meta API responde HTTP 401 Unauthorized, la función `_post_meta` invalida la caché con `invalidate_dynamic_settings_cache()`, recarga las credenciales y reintenta la petición inmediatamente.

---

## 3.3. Bot de Usuario en Facebook Messenger (`src/channels/messenger/`)

* **Protocolo:** Meta Send API v21.0.
* **Seguridad Criptográfica:** Validación obligatoria del encabezado `X-Hub-Signature-256`:
  ```python
  expected_hash = hmac.new(
      app_secret.encode("utf-8"),
      raw_body,
      hashlib.sha256,
  ).hexdigest()
  if not hmac.compare_digest(f"sha256={expected_hash}", signature_header):
      raise HTTPException(status_code=403, detail="Firma de Messenger inválida")
  ```
* **Idempotencia y Deduplicación:** Caché en memoria `_PROCESSED_MSG_IDS` con TTL de 600 segundos (10 minutos). Si Meta reenvía un `mid` ya procesado, se descarta con HTTP 200 OK.
* **Plantillas Genéricas (Carruseles):** Despliegue de fichas de cilindros de gas con imágenes ilustrativas oficiales de Petroil, título con peso, subtítulo con precio y botón de postback `"Comprar"`.

---

## 3.4. Bot de Usuario en Instagram Direct (`src/channels/instagram/`)

* **Protocolo:** Instagram Messaging API (vinculada a la FanPage de Facebook de Petroil).
* **Identificador de Usuario:** Instagram-Scoped ID (`igsid`).
* **Seguridad Criptográfica:** Validación idéntica de firma HMAC-SHA256 con `INSTAGRAM_APP_SECRET`.
* **Capacidades Táctiles:** Quick Replies deslizables horizontalmente de hasta 13 opciones en el cliente móvil de Instagram.
* **Manejo de Notas de Voz:** Descarga de archivos de voz en formato M4A desde el enlace temporal de CDN de Instagram, conversión y procesamiento en Whisper.

---

# PARTE 4: REQUERIMIENTOS NO FUNCIONALES

### RNF-01: Rendimiento y Latencia
* Tiempos de respuesta para interacciones deterministas (botones, clics, callbacks): $\le 1.2$ segundos.
* Tiempos de respuesta para inferencia con DeepSeek v3 (solo consultas libres complejas): $\le 3.0$ segundos.
* Tiempos de respuesta para transcripción de notas de voz con Whisper: $\le 4.0$ segundos para audios de hasta 15 segundos.

### RNF-02: Disponibilidad y Resiliencia
* Disponibilidad del servicio 24/7 con meta de Uptime $\ge 99.9\%$.
* Desacoplamiento de procesos: Si el bot de choferes o la Torre de Control experimentan mantenimiento, los bots de usuario deben continuar recibiendo y encolando pedidos de manera ininterrumpida.

### RNF-03: Seguridad y Privacidad de Datos
* Comunicaciones 100% cifradas en tránsito con TLS 1.3 / HTTPS.
* No almacenamiento de información bancaria ni números de tarjeta (los pagos se procesan de forma física contra entrega).
* Anonimización y sanitización de números telefónicos en logs de depuración para cumplimiento con normativas de protección de datos personales.

### RNF-04: Idempotencia en Webhooks
* Todo endpoint webhook (`whatsapp`, `messenger`, `instagram`) debe responder con HTTP 200 OK en menos de 2.0 segundos para evitar que Meta active políticas de reintento automático por timeout, delegando el procesamiento pesado a `BackgroundTasks`.

---

# PARTE 5: MATRIZ DE TRAZABILIDAD REQUERIMIENTOS VS CÓDIGO

| ID Requerimiento | Descripción Sintética | Archivos de Código Responsables |
| :--- | :--- | :--- |
| **RF-01 / RF-02** | Bienvenida y Selección de Tipo de Servicio | `telegram_bot.py`, `src/services/flow_router.py`, `src/channels/*/router.py` |
| **RF-03** | Catálogo Dinámico y Carritos Multi-Producto | `src/services/flow_router.py`, `src/repositories/sqlite_repo.py`, `wa_carts`, `msgr_carts`, `ig_carts` |
| **RF-04** | Captura y Validación de Teléfono | `src/services/flow_router.py`, `src/repositories/identity_store.py` |
| **RF-05** | Gestión de Direcciones y Geocodificación | `src/services/geocoding.py`, `src/repositories/identity_store.py`, `nominatim` |
| **RF-06** | Horarios de Atención y Programación | `src/services/schedule_manager.py`, `src/services/flow_router.py` |
| **RF-07** | Selección de Método de Pago | `src/services/flow_router.py`, `src/channels/*/adapter.py` |
| **RF-08** | Resumen y Confirmación Obligatoria | `src/services/flow_router.py`, `src/tools/create_order.py` |
| **RF-09** | Notificaciones Push de Estatus al Cliente | `src/services/notifications.py`, `src/repositories/identity_store.py` |
| **RF-10** | Encuesta CSAT de 1 a 5 Estrellas | `src/repositories/identity_store.py`, `src/services/notifications.py` |
| **RF-11** | Transcripción de Voz Whisper | `src/services/audio_transcription.py`, `src/channels/*/router.py` |
| **RF-12** | Consulta de Estatus y Cancelación | `src/tools/get_order_status.py`, `src/tools/cancel_order.py` |
| **RNF-03 / 04** | Seguridad HMAC y Deduplicación | `src/channels/messenger/router.py`, `src/channels/instagram/router.py` |
