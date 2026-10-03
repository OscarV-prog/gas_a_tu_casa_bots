# Product Context: Bots de Usuario Omnicanal (Gas a tu Puerta)

**Cliente:** Grupo Petroil — División Gas (Mazatlán, Sinaloa)  
**Versión:** 3.5.0 Enterprise — Consolidada con la Arquitectura Real de Canales de Cliente (Telegram, WhatsApp, Facebook Messenger e Instagram Direct)  
**Estado:** Documento de Contexto Oficial Aprobado y Operativo  
**Fecha:** Octubre 2026  

---

## 1. Visión General del Contexto de Negocio

El proyecto **Gas a Tu Puerta - Petroil** opera en el mercado de distribución minorista y comercial de Gas Licuado de Petróleo (Gas LP) en el municipio de Mazatlán, Sinaloa. La operación atiende dos modalidades esenciales de consumo:

1. **Venta de Cilindros Portátiles:** Suministro a domicilio de cilindros metálicos presurizados de 10 kg, 20 kg, 30 kg y 45 kg, distribuidos mediante camionetas de redilas con choferes repartidores.
2. **Suministro a Tanque Estacionario:** Recarga de gas líquido por volumen en litros mediante camiones cisterna presurizados (pipas), solicitada comúnmente por importe en pesos (ej. "$500 MXN", "$1,200 MXN") o por porcentaje de llenado (ej. "llenar al 80%").

### Particularidades Geográficas y Operativas de Mazatlán
* **Diversidad de Zonas Urbanas:** La plaza combina zonas tradicionales y turísticas (Centro Histórico, Paseo Olas Altas, Zona Dorada, Cerritos) con fraccionamientos residenciales consolidados (El Conchi, Fracc. del Bosque, Villa Verde, Misiones) y complejos suburbanos en rápida expansión (Pradera Dorada etapas I-VII, Santa Teresa, Real del Valle) donde las calles y códigos postales suelen no estar debidamente indexados en cartografías comerciales tradicionales.
* **Demanda Climática y Estacional:** Picos marcados de demanda matutina (6:30 AM a 10:00 AM) para uso doméstico, y demanda comercial vespertina para establecimientos gastronómicos y hoteleros a lo largo del Malecón.
* **Comportamiento Digital del Usuario Local:** La casi totalidad de la población cuenta con WhatsApp como su herramienta primaria de comunicación diaria, mientras que sectores jóvenes utilizan intensivamente Instagram Direct, usuarios de mediana edad mantienen interacción constante con negocios a través de Facebook Messenger, y audiencias técnicas o con alta exigencia de rapidez prefieren Telegram.

---

## 2. Ecosistema de Canales de Usuario

La arquitectura del sistema desacopla los adaptadores de entrada de la lógica de negocio, permitiendo que cuatro canales de mensajería distintos interactúen con el mismo núcleo conversacional:

```
                                  CLIENTES EN MAZATLÁN
                ┌───────────────┬──────────────────┬─────────────────┐
                │               │                  │                 │
                ▼               ▼                  ▼                 ▼
         ┌────────────┐  ┌──────────────┐  ┌───────────────┐  ┌─────────────┐
         │  Telegram  │  │   WhatsApp   │  │   Facebook    │  │  Instagram  │
         │  User Bot  │  │  Cloud API   │  │   Messenger   │  │   Direct    │
         └─────┬──────┘  └──────┬───────┘  └───────┬───────┘  └──────┬──────┘
               │                │                  │                 │
               │ HTTPXRequest   │ Webhook POST     │ Webhook POST    │ Webhook POST
               │ Long Polling   │ Graph API v21.0  │ Send API (HMAC) │ IG Graph API
               ▼                ▼                  ▼                 ▼
         ┌────────────┐  ┌──────────────┐  ┌───────────────┐  ┌─────────────┐
         │telegram_bot│  │  whatsapp/   │  │  messenger/   │  │ instagram/  │
         │    .py     │  │  router.py   │  │   router.py   │  │  router.py  │
         └─────┬──────┘  └──────┬───────┘  └───────┬───────┘  └──────┬──────┘
               │                │                  │                 │
               └────────────────┼──────────────────┴─────────────────┘
                                │
                                ▼
         ┌──────────────────────────────────────────────────────────┐
         │           MOTOR CONVERSACIONAL CENTRAL (flow_router.py)  │
         │   • Máquina de Estados (FlowState)                       │
         │   • Carrito Temporal de Compra (wa_carts, msgr_carts...) │
         │   • Orquestador LangGraph AI (sales_graph.py)            │
         │   • Fallback LLM Inteligente (DeepSeek v3 / OpenRouter)  │
         └──────────────────────┬───────────────────────────────────┘
                                │
        ┌───────────────────────┼────────────────────────┐
        ▼                       ▼                        ▼
┌──────────────────┐  ┌───────────────────┐  ┌───────────────────────┐
│  IdentityStore   │  │ Serv. Auxiliares  │  │ Persistencia / Datos  │
│ • Cross-Channel  │  │ • Whisper Audio   │  │ • PostgreSQL Petroil  │
│ • Mapeo Teléfono │  │ • Geocoding Nomin.│  │ • SQLite Local Dev    │
│ • Libreta Addr.  │  │ • ScheduleManager │  │ • Catálogo de Precios │
└──────────────────┘  └───────────────────┘  └───────────────────────┘
```

---

## 3. Matriz Comparativa Detallada de Canales

| Criterio | Telegram (`telegram_bot.py`) | WhatsApp (`src/channels/whatsapp/`) | Facebook Messenger (`src/channels/messenger/`) | Instagram Direct (`src/channels/instagram/`) |
| :--- | :--- | :--- | :--- | :--- |
| **Tecnología Base** | `python-telegram-bot` v20+ async | Meta WhatsApp Cloud API (Graph v21.0) | Meta Messenger Platform (Send API) | Meta Instagram Graph API |
| **Identificador de Usuario** | `chat_id` (numérico entero) | `wa_id` (teléfono internacional, ej. `521669...`) | `psid` (Page-Scoped ID, alfanumérico) | `igsid` (Instagram-Scoped ID, alfanumérico) |
| **Método de Recepción** | Long Polling asíncrono con HTTPX | Webhook HTTP POST en `/channels/whatsapp/webhook` | Webhook HTTP POST en `/channels/messenger/webhook` | Webhook HTTP POST en `/channels/instagram/webhook` |
| **Seguridad de Entrada** | Token del bot provisto por BotFather | `hub.verify_token` en GET handshake | Firma HMAC-SHA256 (`X-Hub-Signature-256`) | Firma HMAC-SHA256 (`X-Hub-Signature-256`) |
| **Interfaz: Botones** | `InlineKeyboardMarkup` ilimitado (filas/cols) | `Interactive Buttons` (máximo 3 botones) | `Quick Replies` y `Button Templates` (hasta 3) | `Quick Replies` deslizables (hasta 13 botones) |
| **Interfaz: Menú Catálogo** | Botones Inline en cuadrícula 2x2 | `Interactive List` (1 sección, hasta 10 filas) | `Generic Template` (Carrusel con imágenes) | `Generic Template` (Carrusel de tarjetas) |
| **Compartir Teléfono** | Botón `KeyboardButton(request_contact=True)` | Texto libre o mensaje de contacto VCard | Texto libre (validado regex 10 dígitos) | Texto libre (validado regex 10 dígitos) |
| **Compartir Ubicación** | Botón `KeyboardButton(request_location=True)` | Mensaje nativo de tipo `location` de WhatsApp | Botón Quick Reply de tipo `location` | Enlace / Texto geocodificado con Nominatim |
| **Notas de Voz** | Audio OGG Opus descargado por Telegram API | Audio OGG Opus descargado vía Graph API Media | Audio MP4/M4A descargado desde URL CDN | Audio M4A/AAC descargado desde URL CDN |
| **Transcripción Audio** | Whisper AI (`audio_transcription.py`) | Whisper AI (`audio_transcription.py`) | Whisper AI (`audio_transcription.py`) | Whisper AI (`audio_transcription.py`) |
| **Ventana de Atención** | Sin ventana (siempre disponible) | Ventana estándar de 24 horas de Meta | Ventana de mensajería estándar de Meta | Ventana de mensajería estándar de Meta |
| **Resumen Financiero** | Mensaje de texto formateado Markdown | Mensaje de texto con formato negrita `*...*` | Mensaje estructurado con Quick Replies | Mensaje estructurado con Quick Replies |
| **Encuesta CSAT** | Botones Inline con estrellas (1 a 5 ⭐) | Botones interactivos (1 a 3/5 ⭐) o lista | Quick Replies con estrellas (1 a 5 ⭐) | Quick Replies con estrellas (1 a 5 ⭐) |

---

## 4. Modelo Unificado de Identidad de Usuario (`IdentityStore`)

Uno de los mayores retos de una arquitectura omnicanal es evitar la fragmentación de la información: si un cliente solicita gas hoy por WhatsApp y mañana consulta el estatus de entrega por Instagram, el sistema debe reconocer que se trata de la misma persona y del mismo domicilio.

### La Llave Canónica de Negocio: Teléfono a 10 Dígitos
El número celular a 10 dígitos (formato estándar mexicano sin prefijos internacionales ni guiones, ej. `6691234567`) actúa como el **Ancla de Identidad Universal (Unique Identity Anchor)** en la base de datos de Grupo Petroil.

### Mapeo Persistente entre Procesos (`src/repositories/identity_store.py`)
Dado que los bots corren en procesos concurrentes (ej. `telegram_bot.py` como demonio independiente y `uvicorn` levantando la API de FastAPI con los routers de WhatsApp, Messenger e Instagram), el almacenamiento de identidades se sincroniza en disco en tiempo real:

1. **`channel_identity_cache.json`:** Archivo JSON transaccional con escritura atómica (`.tmp -> replace`) que mantiene:
   * `phone_to_tg`: Mapea teléfonos de 10 dígitos al `chat_id` de Telegram.
   * `tg_to_phone`: Mapea `chat_id` al teléfono a 10 dígitos.
   * `order_channels`: Registra para cada folio de orden (`order_id`):
     ```json
     {
       "channel": "whatsapp",
       "channel_user_id": "5216699876543",
       "phone": "6699876543"
     }
     ```
   * `_deleted_addresses`: Lista negra de direcciones eliminadas expresamente por el cliente para no volver a sugerirlas.
   * `order_ratings`: Registro persistente de calificaciones CSAT emitidas desde los bots.
   * `order_client_messages`: Mensajes adicionales enviados por el cliente hacia el repartidor.

---

## 5. Entidades Principales del Dominio de Clientes

### 5.1. `Customer` (Cliente)
Representa al comprador final en la base de datos relacional de Petroil:
* `id` (int): Identificador interno.
* `tenant_id` (str): `"petroil"`.
* `name` (str): Nombre completo del cliente o titular del servicio.
* `phone` (str): Teléfono normalizado a 10 dígitos.
* `channel` (str): Canal por el que se registró originalmente (`"telegram"`, `"whatsapp"`, `"messenger"`, `"instagram"`).
* `channel_user_id` (str): Identificador específico del canal (`chat_id`, `wa_id`, `psid`, `igsid`).
* `address` (str): Dirección principal por defecto.
* `addresses` (list[CustomerAddress]): Libreta con todas las direcciones guardadas del cliente.

### 5.2. `CustomerAddress` (Dirección del Cliente)
Permite gestionar múltiples domicilios (ej. "Casa", "Restaurante", "Casa de mi mamá"):
* `id` (int): Identificador de la dirección.
* `address` (str): Texto formal de la calle, número, colonia y referencias.
* `alias` (str): Etiqueta corta (ej. "Principal", "Sucursal Centro", "Mi Casa").
* `latitude` / `longitude` (float | None): Coordenadas GPS satelitales.

### 5.3. `DraftOrder` (Borrador de Pedido en Vuelo)
Objeto en memoria (`dataclass`) que acumula los datos recolectados durante la conversación antes de crear el registro formal en la base de datos:
* `service_type` (str): `"cilindro"` o `"estacionario"`.
* `items` (list[dict]): Lista de productos, cantidades y precios unitarios.
* `customer_phone` (str): Teléfono capturado o heredado.
* `customer_name` (str): Nombre del titular.
* `delivery_address` (str): Dirección seleccionada o geocodificada.
* `delivery_lat` / `delivery_lng` (float): Coordenadas geográficas obligatorias para el despacho.
* `notes` (str): Referencias adicionales de entrega (ej. "portón negro frente al parque").
* `delivery_schedule` (str): `"Lo antes posible"` o texto de fecha/hora programada.
* `scheduled_for` (str | None): Timestamp normalizado ISO-8601 si es un pedido programado.
* `payment_method` (str): `"Efectivo"`, `"Tarjeta"` o `"Transferencia"`.

---

## 6. Servicios y Módulos Compartidos

Todos los bots consumen los mismos servicios centrales de la capa `src/services/`:

1. **`flow_router.py` (Enrutador Conversacional Determinista):**
   * Controla la máquina de estados de 10 pasos (`FlowState.INITIAL`, `WAITING_FOR_PRODUCT_OR_QUANTITY`, `WAITING_FOR_PHONE`, `WAITING_FOR_ADDRESS_SELECTION`, `WAITING_FOR_SCHEDULE`, `WAITING_FOR_PAYMENT_METHOD`, `WAITING_FOR_CONFIRMATION`, etc.).
   * Aplica la regla arquitectónica de **Cero Llamadas a LLM** cuando el usuario interactúa con botones, callbacks o textos coincidentes con expresiones regulares, reservando la inferencia de lenguaje natural únicamente para resolver ambigüedades.
2. **`audio_transcription.py` (Transcripción de Voz Whisper):**
   * Descarga el archivo de audio temporal desde los servidores de Telegram o Meta.
   * Procesa el stream de audio con OpenAI Whisper / Faster-Whisper para extraer el texto en español con alta fidelidad.
   * Inyecta el texto transcrito de vuelta en el flujo como si el usuario lo hubiera tecleado.
3. **`geocoding.py` (Geocodificación Satelital y Reversa):**
   * Consume la API de OpenStreetMap Nominatim con filtrado estricto para Mazatlán, Sinaloa (`countrycodes=mx`, `viewbox=-106.50,23.15,-106.30,23.35`).
   * Convierte coordenadas GPS nativas compartidas en chat a nombres legibles de calle y colonia (`resolve_gps_address_to_name`).
4. **`schedule_manager.py` (Gestor de Horarios y Disponibilidad):**
   * Valida si el horario comercial de atención de Petroil está abierto al momento de la interacción.
   * Si está cerrado, propone automáticamente opciones de entrega para el siguiente turno disponible (ej. "Mañana a las 8:00 AM").
5. **`notifications.py` (Servicio Multi-Bot de Notificaciones a Clientes):**
   * Despacha mensajes proactivos al canal exacto por el que ordenó el usuario cuando la orden cambia de estatus (`assigned`, `in_route`, `delivered`).
   * Despliega la tarjeta interactiva de calificación CSAT (1 a 5 ⭐) una vez confirmado el cobro.

---

## 7. Ciclo de Vida del Pedido desde la Perspectiva del Usuario

```
[ PASO 1: CONTACTO INICIAL ]
  Cliente saluda o envía nota de voz en Telegram / WhatsApp / Messenger / Instagram
       │
       ▼
[ PASO 2: TIPO DE SERVICIO ]
  Bot despliega botones: [ 🛢️ Cilindros ] ó [ 🔥 Tanque Estacionario ]
       │
       ▼
[ PASO 3: CATÁLOGO Y CANTIDADES ]
  Selección de capacidad (10, 20, 30, 45 kg) con precio real vigente en pesos.
  Gestión de carrito multi-producto (+ / - unidades).
       │
       ▼
[ PASO 4: TELÉFONO DE CONTACTO ]
  Si el canal provee el número (WhatsApp) se toma automáticamente.
  En Telegram se ofrece botón de compartir contacto. En otros canales se pide a 10 dígitos.
       │
       ▼
[ PASO 5: DIRECCIÓN DE ENTREGA ]
  Si es cliente existente: Muestra botones con sus direcciones guardadas ("Casa", "Trabajo").
  Si es cliente nuevo o desea otra: Permite enviar GPS nativo en 1 clic o escribir dirección con referencias.
       │
       ▼
[ PASO 6: HORARIO DE ENTREGA ]
  Validación de horario de servicio.
  Opciones: "Lo antes posible" (inmediato) ó "Programar fecha y hora".
       │
       ▼
[ PASO 7: MÉTODO DE PAGO ]
  Opciones: [ 💵 Efectivo ] | [ 💳 Tarjeta (Terminal) ] | [ 📱 Transferencia SPEI ]
       │
       ▼
[ PASO 8: RESUMEN Y CONFIRMACIÓN OBLIGATORIA ]
  Bot presenta desglose completo (Productos, Total en MXN, Dirección, Horario, Pago).
  Botón obligatorio: [ ✅ Confirmar Pedido ] | [ ✏️ Modificar ] | [ ❌ Cancelar ]
       │
       ▼
[ PASO 9: SEGUIMIENTO EN TIEMPO REAL ]
  Bot entrega Folio #XXXXX.
  Notificación cuando el chofer es asignado con placas y modelo del vehículo.
  Notificación cuando el chofer va en camino con enlace al mapa de rastreo.
       │
       ▼
[ PASO 10: ENTREGA Y EVALUACIÓN CSAT ]
  Chofer confirma cobro y entrega.
  Bot envía encuesta en el chat: "¿Cómo calificarías el servicio de hoy? (⭐ 1 al 5)".
```
