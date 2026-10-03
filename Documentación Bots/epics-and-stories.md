# Plan de Implementación Ágil — Epics, Features y Stories
## Bots de Usuario Omnicanal (Gas a tu Puerta) — Grupo Petroil

**Cliente:** Grupo Petroil — División Gas (Mazatlán, Sinaloa)  
**Versión:** 3.5.0 Enterprise — Focalizada Exclusivamente en Canales de Usuario (Telegram, WhatsApp, Facebook Messenger e Instagram Direct)  
**Estado:** Documento Maestro de Historias de Usuario Aprobado y Vigente  
**Fuentes Oficiales de Verdad:** `product-context.md`, `prd.md`, `architecture.md`, `user-flows.md`, `ux-design-specification.md` y Código Fuente  
**Fecha:** Octubre 2026  

---

## Control de Versiones del Documento

| Versión | Fecha | Autor | Descripción del Cambio | Estado |
| :--- | :--- | :--- | :--- | :--- |
| **1.0.0** | 15/08/2026 | Agile Coach & Tech Lead | Backlog inicial de historias de usuario para bot de ventas. | Superado |
| **2.0.0** | 28/08/2026 | Antigravity AI Team | Desglose de épicas para Telegram y WhatsApp Cloud API. | Superado |
| **3.0.0** | 20/09/2026 | Antigravity AI Team | Incorporación de épicas para Facebook Messenger e Instagram Direct. | Superado |
| **3.5.0** | 02/10/2026 | Antigravity AI & Equipo Petroil | **Consolidación Integral de los 4 Bots de Usuario:**<br>• 7 Épicas completas con criterios de aceptación Gherkin.<br>• Mapeo estricto a los archivos de código del repositorio.<br>• Cobertura de carritos multi-producto, Whisper audio, GPS y CSAT.<br>• Validación criptográfica HMAC-SHA256 e idempotencia en Meta APIs. | **Aprobado / Vigente** |

---

# ÍNDICE GENERAL DE ÉPICAS

| ID | Nombre de la Épica | Módulos y Código Involucrado | Estado |
| :--- | :--- | :--- | :---: |
| **EPIC-BOT-01** | Bot de Usuario en Telegram (Teclados, GPS, Contacto y Whisper) | `telegram_bot.py`, `src/services/flow_router.py` | ✅ Implementado |
| **EPIC-BOT-02** | Bot de Usuario en WhatsApp Cloud API (Listas, Botones y Carrito) | `src/channels/whatsapp/adapter.py`, `router.py` | ✅ Implementado |
| **EPIC-BOT-03** | Bot de Usuario en Facebook Messenger (Carruseles, HMAC y PSID) | `src/channels/messenger/adapter.py`, `router.py` | ✅ Implementado |
| **EPIC-BOT-04** | Bot de Usuario en Instagram Direct (Quick Replies, IGSID y Voz) | `src/channels/instagram/adapter.py`, `router.py` | ✅ Implementado |
| **EPIC-BOT-05** | Motor Conversacional Central, Carrito y Regla Zero-LLM | `src/services/flow_router.py`, `src/graphs/sales_graph.py` | ✅ Implementado |
| **EPIC-BOT-06** | Identidad Cross-Channel, Geocodificación y Transcripción Whisper | `src/repositories/identity_store.py`, `src/services/*` | ✅ Implementado |
| **EPIC-BOT-07** | Notificaciones Push de Entrega y Calificación CSAT Multi-Canal | `src/services/notifications.py`, `src/repositories/` | ✅ Implementado |

---

# EPIC-BOT-01: Bot de Usuario en Telegram (`telegram_bot.py`)

**Objetivo:** Proporcionar a los clientes de Telegram una experiencia de compra inmediata mediante teclados inline enriquecidos, compartición de ubicación satelital nativa, captura de teléfono en 1 toque y transcripción de audios.

---

## STORY-BOT-01.1: Menú Inicial con Teclados Inline
* **Descripción:** Como usuario en Telegram, quiero interactuar con botones inline limpios para seleccionar el tipo de servicio de gas sin escribir texto.
* **Criterios de Aceptación (Gherkin):**
  ```gherkin
  Scenario: Inicio de sesión en Telegram
    Given que el usuario abre el chat con el bot de Telegram y envía "/start" o "Hola"
    When el bot procesa el mensaje
    Then responde con el mensaje institucional de Grupo Petroil
    And adjunta un InlineKeyboardMarkup con los botones "[ 🛢️ Cilindros ]" y "[ 🔥 Tanque Estacionario ]"
    And los callback_data corresponden a "srv_cilindro" y "srv_estacionario"
  ```

---

## STORY-BOT-01.2: Captura Nativa de Teléfono y Ubicación GPS
* **Descripción:** Como usuario en Telegram, quiero compartir mi ubicación GPS y mi teléfono con botones nativos para no tener que escribirlos manualmente.
* **Criterios de Aceptación (Gherkin):**
  ```gherkin
  Scenario: Envío de contacto y ubicación en Telegram
    Given que el bot se encuentra en el estado WAITING_FOR_PHONE o WAITING_FOR_NEW_CUSTOMER_ADDRESS
    When el bot solicita la información
    Then despliega un ReplyKeyboardMarkup con:
      | Botón | Atributo |
      | "📱 Compartir mi Teléfono en 1 Toque" | request_contact=True |
      | "📍 Enviar mi Ubicación GPS" | request_location=True |
    And al presionar el botón de ubicación, el bot recibe las coordenadas latitud/longitud
    And ejecuta reverse_geocode para obtener calle y colonia en Mazatlán
  ```

---

# EPIC-BOT-02: Bot de Usuario en WhatsApp Cloud API (`src/channels/whatsapp/`)

**Objetivo:** Habilitar la venta automatizada de Gas LP en WhatsApp mediante Meta Cloud API, utilizando listas interactivas para catálogo de productos, botones rápidos de confirmación y carrito de compras.

---

## STORY-BOT-02.1: Handshake de Verificación y Recepción de Webhook
* **Descripción:** Como sistema, debo verificar correctamente el token de WhatsApp en la petición GET inicial y procesar mensajes entrantes en la petición POST.
* **Criterios de Aceptación (Gherkin):**
  ```gherkin
  Scenario: Verificación de Webhook de WhatsApp (GET)
    Given una petición GET a "/channels/whatsapp/webhook"
    When los parámetros incluyen "hub.mode=subscribe" y "hub.verify_token" correcto
    Then el endpoint devuelve HTTP 200 con el valor de "hub.challenge" en texto plano

  Scenario: Recepción de mensaje de texto en WhatsApp (POST)
    Given una petición POST a "/channels/whatsapp/webhook" con un payload válido de Meta
    When el router procesa el evento
    Then responde HTTP 200 OK inmediatamente
    And delega la respuesta conversacional a BackgroundTasks sin bloquear el hilo
  ```

---

## STORY-BOT-02.2: Catálogo en Lista Interactiva y Carrito `wa_carts`
* **Descripción:** Como cliente en WhatsApp, quiero ver el catálogo oficial en una lista desplegable y poder sumar varios cilindros a mi carrito.
* **Criterios de Aceptación (Gherkin):**
  ```gherkin
  Scenario: Selección de cilindro y actualización de carrito en WhatsApp
    Given que el cliente solicita comprar cilindros
    When el bot responde
    Then envía un mensaje interactivo tipo "list" con 1 sección y las capacidades (10, 20, 30, 45 kg)
    And cuando el usuario selecciona "Cilindro de 30 kg", se almacena en el diccionario wa_carts
    And el bot responde con el total acumulado y botones "[ ➕ Agregar otro ]" y "[ ➡️ Continuar ]"
  ```

---

## STORY-BOT-02.3: Recuperación Automática de Token Meta ante Error 401
* **Descripción:** Como infraestructura, el adaptador debe refrescar las credenciales dinámicas e invalidar la caché si Meta API retorna HTTP 401 Unauthorized.
* **Criterios de Aceptación (Gherkin):**
  ```gherkin
  Scenario: Reintento automático ante token expirado en WhatsApp
    Given que el WhatsAppAdapter envía un mensaje a Meta Graph API
    When Meta responde con código HTTP 401 Unauthorized
    Then el adaptador invoca invalidate_dynamic_settings_cache()
    And recarga la configuración remota
    And reintenta el envío del mensaje de manera transparente para el usuario
  ```

---

# EPIC-BOT-03: Bot de Usuario en Facebook Messenger (`src/channels/messenger/`)

**Objetivo:** Atender a los clientes de Facebook que contactan la FanPage de Petroil Gas mediante carruseles enriquecidos, Quick Replies y validación criptográfica HMAC.

---

## STORY-BOT-03.1: Validación Criptográfica de Firma HMAC-SHA256
* **Descripción:** Como medida de seguridad, el router de Messenger debe verificar la autenticidad de cada petición con el encabezado `X-Hub-Signature-256`.
* **Criterios de Aceptación (Gherkin):**
  ```gherkin
  Scenario: Rechazo de petición con firma falsa en Messenger
    Given una petición POST a "/channels/messenger/webhook"
    When el hash HMAC-SHA256 calculado con MESSENGER_APP_SECRET no coincide con la firma recibida
    Then el router rechaza la petición con código HTTP 403 Forbidden
    And no procesa ningún mensaje interno

  Scenario: Aceptación de petición legítima de Meta
    Given una petición con firma HMAC-SHA256 válida
    Then el router la acepta con HTTP 200 OK y la procesa normalmente
  ```

---

## STORY-BOT-03.2: Despliegue de Carrusel de Productos y Quick Replies
* **Descripción:** Como usuario en Messenger, quiero visualizar las opciones de gas en un carrusel de tarjetas con imágenes y botones de compra directa.
* **Criterios de Aceptación (Gherkin):**
  ```gherkin
  Scenario: Navegación de catálogo en Messenger
    Given que el usuario selecciona el catálogo de cilindros
    When el bot responde
    Then envía un "Generic Template" con elementos visuales para cada capacidad de cilindro
    And cada tarjeta contiene título, precio en subtítulo, imagen oficial y botón de postback
    And al seleccionar un producto, ofrece Quick Replies inferiores para métodos de pago
  ```

---

# EPIC-BOT-04: Bot de Usuario en Instagram Direct (`src/channels/instagram/`)

**Objetivo:** Conectar a los usuarios de Instagram con el servicio de entrega de gas mediante respuestas directas (DM), Quick Replies deslizables y gestión de notas de voz.

---

## STORY-BOT-04.1: Interacción Táctil Deslizable en Instagram DM
* **Descripción:** Como usuario en Instagram, quiero interactuar mediante botones rápidos deslizables adaptados al diseño nativo de la app.
* **Criterios de Aceptación (Gherkin):**
  ```gherkin
  Scenario: Selección de opciones en Instagram Direct
    Given una conversación activa en Instagram Direct
    When el bot presenta opciones de selección (productos, direcciones u horarios)
    Then envía hasta 13 Quick Replies deslizables horizontalmente
    And asocia cada botón al IGSID del cliente en el caché de sesión ig_carts
  ```

---

## STORY-BOT-04.2: Descarga y Transcripción de Audios M4A en Instagram
* **Descripción:** Como usuario de Instagram, quiero enviar un mensaje de voz y que el bot entienda mi pedido automáticamente.
* **Criterios de Aceptación (Gherkin):**
  ```gherkin
  Scenario: Procesamiento de nota de voz en Instagram
    Given que el usuario envía un audio en formato M4A / AAC por Instagram Direct
    When el router recibe el adjunto de tipo "audio"
    Then descarga el archivo binario desde la URL temporal de CDN de Instagram
    And lo envía al servicio transcribe_audio_file de Whisper
    And procesa el texto resultante en el flujo de ventas sin pedir al usuario volver a escribir
  ```

---

# EPIC-BOT-05: Motor Conversacional Central y Carrito Multi-Producto (`flow_router.py`)

**Objetivo:** Garantizar que los 4 canales compartan la misma lógica de negocio, reglas de cálculo de importes, validación de horarios y confirmación obligatoria.

---

## STORY-BOT-05.1: Regla Zero-LLM en Opciones Estructuradas
* **Descripción:** Como arquitectura de software, las interacciones con botones y callbacks no deben consumir llamadas a LLM para evitar costos y latencia.
* **Criterios de Aceptación (Gherkin):**
  ```gherkin
  Scenario: Procesamiento determinista sin LLM
    Given que el usuario presiona un botón interactivo o envía un comando estándar
    When flow_router.py procesa el input
    Then resuelve la transición de estado mediante lógica determinista
    And realiza exactamente 0 llamadas a la API de OpenRouter / DeepSeek
    And la respuesta se emite en menos de 1.2 segundos
  ```

---

## STORY-BOT-05.2: Resumen Financiero y Confirmación Previa Obligatoria
* **Descripción:** Como cliente, quiero revisar el desglose total antes de que se cree el pedido formal en la gasera.
* **Criterios de Aceptación (Gherkin):**
  ```gherkin
  Scenario: Confirmación obligatoria de pedido
    Given que el cliente completó productos, dirección, horario y pago
    When el bot alcanza el estado WAITING_FOR_CONFIRMATION
    Then muestra la tarjeta resumen con productos, importe total en MXN, dirección y pago
    And no crea el pedido en base de datos hasta que el cliente presione "[ ✅ Confirmar Pedido ]"
    And al confirmar, ejecuta create_order y entrega el Folio numérico al cliente
  ```

---

# EPIC-BOT-06: Identidad Cross-Channel, Geocodificación y Whisper

**Objetivo:** Compartir identidades y domicilios entre los distintos canales de chat, geocodificar direcciones en Mazatlán y transcribir notas de voz.

---

## STORY-BOT-06.1: Enlace Universal de Teléfono en `IdentityStore`
* **Descripción:** Como cliente omnicanal, si ya compré por WhatsApp y luego entro por Telegram, el sistema debe reconocer mi teléfono y mis direcciones registradas.
* **Criterios de Aceptación (Gherkin):**
  ```gherkin
  Scenario: Vinculación cross-channel de cliente
    Given que el cliente tiene el teléfono "6691234567" registrado con direcciones en WhatsApp
    When inicia conversación en Telegram y comparte ese mismo número telefónico
    Then IdentityStore enlaza su chat_id de Telegram con el teléfono
    And el bot de Telegram le muestra de inmediato sus direcciones guardadas en botones
  ```

---

## STORY-BOT-06.2: Geocodificación Satelital con Nominatim Mazatlán
* **Descripción:** Como motor logístico, toda dirección ingresada debe validarse geográficamente para obtener latitud y longitud antes de asignarla a un chofer.
* **Criterios de Aceptación (Gherkin):**
  ```gherkin
  Scenario: Geocodificación de dirección en Mazatlán
    Given una dirección proporcionada por texto o GPS
    When se ejecuta geocode_address()
    Then consulta Nominatim acotado al bounding box de Mazatlán, Sinaloa
    And devuelve coordenadas lat/lng válidas
    And asocia las coordenadas al pedido para el cálculo de cercanía del chofer
  ```

---

# EPIC-BOT-07: Notificaciones Push de Entrega y Calificación CSAT Multi-Canal

**Objetivo:** Informar proactivamente al cliente sobre el trayecto de su pedido y recopilar su evaluación de satisfacción tras recibir el gas.

---

## STORY-BOT-07.1: Notificación Push Reactiva al Canal de Origen
* **Descripción:** Como cliente, quiero recibir avisos automáticos en el mismo chat donde ordené cuando mi pedido sea asignado, vaya en ruta y sea entregado.
* **Criterios de Aceptación (Gherkin):**
  ```gherkin
  Scenario: Notificación de chofer en ruta
    Given un pedido creado por WhatsApp en estado "in_route"
    When el chofer inicia el viaje en driver_bot.py
    Then notifications.py identifica el canal "whatsapp" y el "channel_user_id" en IdentityStore
    And envía un mensaje proactivo al cliente con el nombre del chofer y placas de la unidad
  ```

---

## STORY-BOT-07.2: Encuesta de Calidad CSAT de 1 a 5 Estrellas
* **Descripción:** Como departamento de calidad de Grupo Petroil, quiero medir la satisfacción del cliente tras cada entrega para evaluar el servicio de la flota.
* **Criterios de Aceptación (Gherkin):**
  ```gherkin
  Scenario: Envío y captura de calificación CSAT
    Given que un pedido cambia a estado "delivered"
    When el bot envía el comprobante de entrega
    Then adjunta botones de calificación del 1 al 5 (⭐ a ⭐⭐⭐⭐⭐)
    And al seleccionar una opción, guarda el puntaje en la tabla ORDER_RATINGS
    And emite un mensaje de agradecimiento personalizado según el puntaje
  ```
