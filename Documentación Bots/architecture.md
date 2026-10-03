# Architecture Design Document (ADD) — Bots de Usuario Omnicanal

**Cliente:** Grupo Petroil — División Gas (Mazatlán, Sinaloa)  
**Versión:** 3.5.0 Enterprise — Sincronizada con la Arquitectura Real de Canales de Cliente (Telegram, WhatsApp, Facebook Messenger e Instagram Direct)  
**Estado:** Documento de Arquitectura Oficial Aprobado y Operativo  
**Fuentes Oficiales de Verdad:** `product-context.md`, `prd.md`, `telegram_bot.py`, `src/channels/`, `src/services/flow_router.py`  
**Fecha:** Octubre 2026  

---

## Control de Versiones del Documento

| Versión | Fecha | Autor | Descripción del Cambio | Estado |
| :--- | :--- | :--- | :--- | :--- |
| **1.0.0** | 12/08/2026 | Winston (System Architect) | Diseño inicial de adaptadores conversacionales. | Superado |
| **2.0.0** | 25/08/2026 | Arquitectura & AI Team | Arquitectura hexagonal para Telegram y WhatsApp Cloud API. | Superado |
| **3.0.0** | 18/09/2026 | Antigravity AI | Incorporación de routers para Messenger e Instagram con HMAC-SHA256. | Superado |
| **3.5.0** | 02/10/2026 | Antigravity AI & Equipo Petroil | **Consolidación de Arquitectura de Canales de Usuario:**<br>• Modelado C4 exhaustivo (Contexto, Contenedores y Componentes).<br>• Motor conversacional determinista híbrido con cero llamadas LLM en botones.<br>• Mapeo universal de identidades cross-process en `IdentityStore`.<br>• Pipeline de transcripción de voz Whisper desacoplado de la red.<br>• Resiliencia de tokens Meta con refresco dinámico ante errores 401.<br>• Diagramas de secuencia de webhooks, deduplicación e idempotencia. | **Aprobado / Vigente** |

---

# PARTE 1: ESTRATEGIA Y PRINCIPIOS ARQUITECTÓNICOS

---

## 1. Principios de Diseño Arquitectónico

La arquitectura del subsistema de bots de usuario se rige por cinco directrices fundamentales:

### 1.1. Determinismo Primero (Zero-LLM Rule para Opciones Estructuradas)
Para garantizar tiempos de respuesta sub-segundo, eliminar alucinaciones de precios y reducir costos computacionales, la interacción con botones, listas interactivas, callbacks y expresiones regulares no realiza llamadas a modelos de lenguaje (LLMs). El modelo de lenguaje (DeepSeek v3 vía OpenRouter) se invoca exclusivamente como mecanismo de respaldo cuando el usuario redacta mensajes de texto libre con ambigüedad semántica.

### 1.2. Arquitectura de Puertos y Adaptadores (Hexagonal)
La lógica de negocio comercial (catálogo, validación de horarios, cálculo de totales, libreta de direcciones, creación de pedidos en base de datos) reside en el núcleo (`src/services/flow_router.py` y `src/tools/`). Los cuatro canales de usuario son adaptadores periféricos intercambiables que traducen los eventos externos al modelo canónico `InboundMessage` y los estados de respuesta a `OutboundMessage`.

### 1.3. Ancla de Identidad Universal (`IdentityStore`)
El número telefónico de 10 dígitos es la clave primaria lógica del cliente. La capa `IdentityStore` (`channel_identity_cache.json`) desacopla los identificadores volátiles de cada red social (`chat_id`, `wa_id`, `psid`, `igsid`), sincronizando en tiempo real la correspondencia biunívoca entre ellos.

### 1.4. Resiliencia, Idempotencia y No Bloqueo
Las plataformas de Meta reintentan el envío de webhooks si el servidor receptor tarda más de 3 segundos en responder. Para prevenir bloqueos o pedidos duplicados:
* El router responde inmediatamente `HTTP 200 OK`.
* Se implementa un filtro de deduplicación con TTL de 10 minutos para los identificadores de mensaje (`mid`).
* El procesamiento pesado (geocodificación, transcripción de audio, inserciones en base de datos) se delega a `BackgroundTasks` de FastAPI y tareas asíncronas de `asyncio`.

---

# PARTE 2: MODELADO C4 DEL SUBSISTEMA DE BOTS DE USUARIO

---

## 2.1. C4 — Nivel 1: Diagrama de Contexto del Sistema

```mermaid
graph TD
    Client_TG[Cliente en Telegram] -->|Chat, Botones Inline, Contacto, GPS, Audio| TG_Platform[Servidores de Telegram Bot API]
    Client_WA[Cliente en WhatsApp] -->|Chat, Listas, Botones, GPS, Audio OGG| Meta_WA[Meta WhatsApp Cloud API]
    Client_FB[Cliente en Facebook Messenger] -->|Chat, Carruseles, Quick Replies, Audio| Meta_FB[Meta Messenger Platform]
    Client_IG[Cliente en Instagram Direct] -->|Chat, Quick Replies, Fichas, Audio| Meta_IG[Meta Instagram Graph API]

    TG_Platform -->|HTTP Long Polling / Updates| Bot_Subsystem[Subsistema Bots de Usuario Petroil]
    Meta_WA -->|Webhook HTTP POST JSON| Bot_Subsystem
    Meta_FB -->|Webhook HTTP POST HMAC-SHA256| Bot_Subsystem
    Meta_IG -->|Webhook HTTP POST HMAC-SHA256| Bot_Subsystem

    Bot_Subsystem -->|Inferencia Semántica Fallback| OpenRouter[OpenRouter API / DeepSeek v3]
    Bot_Subsystem -->|Transcripción de Audio| Whisper[OpenAI Whisper Engine]
    Bot_Subsystem -->|Geocodificación Satelital| Nominatim[OpenStreetMap Nominatim]
    Bot_Subsystem -->|Persistencia y Catálogo| Database[(PostgreSQL Petroil / SQLite)]
    Bot_Subsystem -->|Notificaciones a Choferes| DispatchSys[Motor de Despacho Logístico]
```

---

## 2.2. C4 — Nivel 2: Diagrama de Contenedores

```mermaid
graph TB
    subgraph "Canales Externos de Mensajería"
        TG_API[Telegram Bot API]
        WA_API[Meta WhatsApp Cloud API]
        MSGR_API[Meta Messenger Send API]
        IG_API[Meta Instagram Graph API]
    end

    subgraph "Infraestructura del Servidor Petroil"
        subgraph "Proceso 1: Servidor Webhook FastAPI (src/app.py)"
            WA_Router["WhatsApp Router\n(src/channels/whatsapp/)"]
            MSGR_Router["Messenger Router\n(src/channels/messenger/)"]
            IG_Router["Instagram Router\n(src/channels/instagram/)"]
            Background_Workers["FastAPI BackgroundTasks\n(Procesamiento Asíncrono)"]
        end

        subgraph "Proceso 2: Demonio de Telegram (telegram_bot.py)"
            TG_Handler["Telegram Client App\n(python-telegram-bot v20+)"]
            TG_Poller["HTTPX Polling Engine"]
        end

        subgraph "Capa de Lógica Conversacional Compartida"
            Flow_Router["Motor de Flujo (flow_router.py)\nState Machine / DraftOrder"]
            LangGraph_Agent["Agente LangGraph (sales_graph.py)\nOrquestador de Diálogos"]
        end

        subgraph "Capa de Servicios y Utilidades"
            Audio_Svc["Audio Transcription (Whisper)\naudio_transcription.py"]
            Geo_Svc["Geocoding Service (Nominatim)\ngeocoding.py"]
            Sched_Svc["Schedule Manager\nschedule_manager.py"]
            Notif_Svc["Multi-Channel Notifications\nnotifications.py"]
            Id_Store["IdentityStore\nchannel_identity_cache.json"]
        end

        subgraph "Persistencia"
            DB[(PostgreSQL Corporativo / SQLite)]
        end
    end

    TG_API <-->|Long Polling HTTPX| TG_Poller
    TG_Poller --> TG_Handler
    WA_API -->|POST /channels/whatsapp/webhook| WA_Router
    MSGR_API -->|POST /channels/messenger/webhook| MSGR_Router
    IG_API -->|POST /channels/instagram/webhook| IG_Router

    WA_Router --> Background_Workers
    MSGR_Router --> Background_Workers
    IG_Router --> Background_Workers

    TG_Handler --> Flow_Router
    Background_Workers --> Flow_Router

    Flow_Router <--> LangGraph_Agent
    Flow_Router --> Audio_Svc
    Flow_Router --> Geo_Svc
    Flow_Router --> Sched_Svc
    Flow_Router <--> Id_Store
    Flow_Router <--> DB

    Notif_Svc --> TG_Handler
    Notif_Svc --> WA_Router
    Notif_Svc --> MSGR_Router
    Notif_Svc --> IG_Router
```

---

## 2.3. C4 — Nivel 3: Diagrama de Componentes de un Canal (Ejemplo: WhatsApp)

```mermaid
graph TD
    subgraph "Paquete src/channels/whatsapp/"
        Endpoint[router.py: /channels/whatsapp/webhook]
        AuthCheck{¿Es Handshake GET o Mensaje POST?}
        VerifyHandler[Manejo hub.challenge GET]
        Deduplicator[Verificador de Idempotencia de Mensajes]
        CartManager["wa_carts (Gestor de Carrito Temporal)"]
        Adapter["WhatsAppAdapter (adapter.py)"]
    end

    subgraph "Servicios Centrales"
        FlowRouter["flow_router.py: process_step()"]
        WhisperSvc["audio_transcription.py"]
    end

    Endpoint --> AuthCheck
    AuthCheck -->|GET| VerifyHandler
    AuthCheck -->|POST| Deduplicator
    Deduplicator -->|Si es Audio| WhisperSvc
    WhisperSvc --> FlowRouter
    Deduplicator -->|Si es Texto o Interactivo| CartManager
    CartManager --> FlowRouter
    FlowRouter --> Adapter
    Adapter -->|POST https://graph.facebook.com/v21.0/| MetaAPI[Meta Graph API Messages]
```

---

# PARTE 3: CONTRATOS DE DATOS Y MODELOS INTERNOS

---

## 3.1. Modelo Canónico de Mensajería (`InboundMessage` / `OutboundMessage`)

Ubicado en `src/models/message.py`, estandariza la comunicación entrante y saliente:

```python
@dataclass
class InboundMessage:
    channel: Literal["telegram", "whatsapp", "messenger", "instagram", "web"]
    channel_user_id: str          # chat_id, wa_id, psid o igsid
    text: str = ""
    message_type: str = "text"    # "text", "location", "contact", "audio", "interactive"
    location_lat: float | None = None
    location_lng: float | None = None
    phone: str | None = None
    audio_url: str | None = None
    payload: str | None = None    # callback_data o quick_reply payload
    raw_event: dict[str, Any] = field(default_factory=dict)

@dataclass
class OutboundMessage:
    recipient_id: str
    text: str
    channel: str
    message_type: str = "text"    # "text", "buttons", "list", "location", "rating"
    buttons: list[dict[str, str]] = field(default_factory=list)
    list_items: list[dict[str, Any]] = field(default_factory=list)
```

---

## 3.2. Estructura de Carritos Temporales en Memoria

Para permitir que el usuario añada varios cilindros antes de proceder al cobro, cada router de canal implementa un almacenamiento temporal:

* **WhatsApp (`wa_carts`):** Diccionario en memoria `dict[str, dict[str, int]]` donde la llave primaria es el `wa_id` y el valor es `{producto_id: cantidad}`.
* **Messenger (`msgr_carts`):** Llave primaria `psid`.
* **Instagram (`ig_carts`):** Llave primaria `igsid`.
* **Telegram:** Almacenado en `user_data["cart"]` administrado por `CallbackContext` de `python-telegram-bot`.

```json
{
  "5216699876543": {
    "cyl_30": 2,
    "cyl_20": 1
  }
}
```

Al solicitar el resumen del carrito, la función `format_cart_summary` calcula subtotales, totales y pluralización gramatical en tiempo real consultando los precios oficiales de la base de datos.

---

## 3.3. Estructura del Caché de Identidad (`channel_identity_cache.json`)

Mantiene la persistencia atómica en disco compartida entre procesos independientes:

```json
{
  "phone_to_tg": {
    "6691234567": "987654321",
    "6699887766": "554433221"
  },
  "tg_to_phone": {
    "987654321": "6691234567",
    "554433221": "6699887766"
  },
  "order_channels": {
    "10452": {
      "channel": "whatsapp",
      "channel_user_id": "5216691234567",
      "phone": "6691234567"
    }
  },
  "order_ratings": {
    "10452": {
      "order_id": "10452",
      "driver_id": "drv_04",
      "rating": 5,
      "feedback_tag": "Excelente servicio y rapidez",
      "created_at": "2026-10-02T14:30:00Z"
    }
  },
  "deleted_addresses": {
    "6691234567": [
      "calle antigua 123 col obrera"
    ]
  }
}
```

---

# PARTE 4: DIAGRAMAS DE SECUENCIA DETALLADOS

---

## 4.1. Secuencia de Webhook Entrante en Meta (WhatsApp, Messenger, Instagram)

```mermaid
sequenceDiagram
    autonumber
    actor Usuario
    participant Meta as Servidores Meta (Graph API)
    participant Router as Router FastAPI (/channels/*)
    participant Security as Validador HMAC / Dedup
    participant Flow as flow_router.py
    participant DB as PostgreSQL / SQLite
    participant Adapter as Channel Adapter

    Usuario->>Meta: Envía mensaje / Toca botón interactivo
    Meta->>Router: POST /channels/{channel}/webhook (JSON payload)
    Router->>Security: Validar firma X-Hub-Signature-256 (Messenger/IG)
    Security-->>Router: Firma Válida (OK)
    Router->>Security: Verificar Message ID (mid) en caché de deduplicación
    Security-->>Router: Mensaje no procesado previamente
    Router-->>Meta: HTTP 200 OK (Inmediato < 500 ms)

    Note over Router,Flow: Proceso delegado a BackgroundTasks
    Router->>Flow: process_step(session_id, input_data)
    Flow->>DB: Consultar catálogo de precios / libreta de direcciones
    DB-->>Flow: Retorna datos reales
    Flow->>Adapter: Generar respuesta interactiva (OutboundMessage)
    Adapter->>Meta: POST https://graph.facebook.com/.../messages
    Meta->>Usuario: Despliega mensaje interactivo / botones
```

---

## 4.2. Secuencia del Pipeline de Transcripción de Audio (Whisper)

```mermaid
sequenceDiagram
    autonumber
    actor Usuario
    participant Bot as Bot de Usuario (Telegram / WhatsApp / Meta)
    participant Storage as Servidor de Archivos (Telegram / Meta CDN)
    participant Whisper as audio_transcription.py
    participant Flow as flow_router.py

    Usuario->>Bot: Envía nota de voz ("Ocupo un cilindro de 30 a Pradera")
    Bot->>Storage: Descargar stream de audio (OGG / M4A / MP4)
    Storage-->>Bot: Archivo binario temporal en disco
    Bot->>Whisper: transcribe_audio_file(temp_path)
    Whisper->>Whisper: Inferencia OpenAI Whisper (Spanish)
    Whisper-->>Bot: Texto transcrito: "Ocupo un cilindro de 30 a Pradera"
    Bot->>Flow: Enviar texto transcrito a la máquina de estados
    Flow->>Flow: Detecta producto ("Cilindro 30 kg") y colonia ("Pradera")
    Flow-->>Bot: Avanza estado y solicita confirmación de dirección
    Bot->>Usuario: "Detectamos que deseas 1 Cilindro de 30 kg..."
```

---

## 4.3. Secuencia de Notificación Proactiva y Encuesta CSAT Post-Entrega

```mermaid
sequenceDiagram
    autonumber
    actor Chofer as Chofer en Campo (driver_bot.py)
    participant Core as Núcleo de Despacho & Base de Datos
    participant Notif as notifications.py
    participant IdStore as IdentityStore
    participant ClientBot as Bot del Canal de Compra
    actor Cliente as Cliente Final

    Chofer->>Core: Finaliza viaje y confirma cobro en efectivo
    Core->>Core: Actualiza orden a estado "delivered"
    Core->>Notif: notify_customer_order_status(order_id, "delivered")
    Notif->>IdStore: get_order_channel_info(order_id)
    IdStore-->>Notif: {channel: "whatsapp", channel_user_id: "521669...", phone: "669..."}
    Notif->>ClientBot: Enviar mensaje de entrega + botones de calificación
    ClientBot->>Cliente: "✅ Tu gas ha sido entregado. ¿Cómo calificarías el servicio?" (1-5 ⭐)
    Cliente->>ClientBot: Presiona [ ⭐⭐⭐⭐⭐ ]
    ClientBot->>IdStore: save_order_rating(order_id, rating=5)
    IdStore->>Core: Persiste en tabla ORDER_RATINGS
    ClientBot->>Cliente: "¡Muchas gracias por elegir a Petroil Gas!"
```

---

# PARTE 5: TOPOLOGÍA DE DESPLIEGUE Y CONFIGURACIÓN DE RED

---

## 5.1. Arquitectura de Procesos Concurrentes

El sistema se ejecuta en el servidor mediante dos procesos principales coordinados:

1. **Servidor API Webhook (`src/app.py`):**
   * Servidor ASGI: `uvicorn` sobre Python 3.11+.
   * Expone los endpoints de webhook para WhatsApp, Messenger e Instagram.
   * Administra la conexión a PostgreSQL y ejecuta `BackgroundTasks`.
2. **Demonio Cliente de Telegram (`telegram_bot.py`):**
   * Ejecución como servicio persistente del sistema operativo (Systemd en Linux o demonio de Windows).
   * Mantiene el ciclo de Long Polling asíncrono con Telegram Bot API sin necesidad de exponer un puerto HTTP público para Telegram.

Ambos procesos comparten el almacenamiento atómico de identidades en `data/channel_identity_cache.json` y la base de datos relacional.

---

## 5.2. Variables de Entorno Críticas (`.env`)

```ini
# --- TELEGRAM BOT DE USUARIOS ---
TELEGRAM_BOT_TOKEN="7890123456:AAH..."

# --- META WHATSAPP CLOUD API ---
WHATSAPP_TOKEN="EAAxxxx..."
WHATSAPP_PHONE_NUMBER_ID="109876543210987"
WHATSAPP_VERIFY_TOKEN="petroil_gas_wa_verify_2026"
WHATSAPP_API_VERSION="v21.0"

# --- META FACEBOOK MESSENGER ---
MESSENGER_PAGE_ACCESS_TOKEN="EAAyyyy..."
MESSENGER_VERIFY_TOKEN="petroil_msgr_secret_2026"
MESSENGER_APP_SECRET="a1b2c3d4e5f6..."

# --- META INSTAGRAM DIRECT ---
INSTAGRAM_PAGE_ACCESS_TOKEN="EAAzzzz..."
INSTAGRAM_VERIFY_TOKEN="petroil_ig_secret_2026"
INSTAGRAM_APP_SECRET="f6e5d4c3b2a1..."

# --- MODELOS DE LENGUAJE & AUDIO ---
OPENROUTER_API_KEY="sk-or-v1-..."
PRIMARY_MODEL="deepseek/deepseek-chat"
OPENAI_API_KEY="sk-..."                 # Para Whisper Audio Transcription

# --- PERSISTENCIA & GEOCODIFICACIÓN ---
DATABASE_URL="postgresql://petroil_app:segura2026@10.0.1.50:5432/petroil_gas"
NOMINATIM_BASE_URL="https://nominatim.openstreetmap.org/search"
```
