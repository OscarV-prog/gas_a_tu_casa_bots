# 📋 Checklist Maestro: Configuración, Arquitectura LangGraph y Despliegue de Bots Paso a Paso

Esta guía detalla el proceso integral para configurar, personalizar y desplegar un bot desde cero en la plataforma multi-canal **Gas a Tu Puerta / Petrogas**, abarcando:
1. **Configuración del Motor LangGraph desde cero** (estructura de carpetas, estados, nodos, grafo, cambio de nombre y herramientas).
2. **Sistema de Seguridad 2FA OTP, Unificación de Cuentas y Cancelación en WhatsApp** (*Nuevos Aditamentos*).
3. **Creación en Plataformas Externas** (Telegram, Meta WhatsApp Cloud API, Facebook Messenger, Instagram Direct).
4. **Variables de Entorno y Configuración Multi-Plaza** (`.env`).
5. **Estructura Modular de Canales** (`src/channels/`).
6. **Delimitación Geográfica, Radio de Cobertura y Validación Semántica de Direcciones**.
7. **Pruebas, Reinicio de Servidores con `--reload` y Despliegue**.

---

## 📑 Tabla de Contenidos
1. [Fase 1: Configuración del Motor LangGraph desde Cero](#fase-1-configuración-del-motor-langgraph-desde-cero)
   - [1.1 Estructura de Carpetas del Grafo](#11-estructura-de-carpetas-del-grafo)
   - [1.2 Definición del Estado (`src/state/agent_state.py`)](#12-definición-del-estado-srcstateagent_statepy)
   - [1.3 Implementación de Nodos (`src/nodes/`)](#13-implementación-de-nodos-srcnodes)
   - [1.4 Construcción y Compilación del Grafo (`src/graphs/sales_graph.py`)](#14-construcción-y-compilación-del-grafo-srcgraphssales_graphpy)
   - [1.5 Cambio de Nombre del Bot, Personalidad y Prompts (`tenants/<tenant_id>/`)](#15-cambio-de-nombre-del-bot-personalidad-y-prompts-tenantstenant_id)
   - [1.6 Registro de Herramientas del Agente (`src/tools/`)](#16-registro-de-herramientas-del-agente-srctools)
   - [1.7 Coordinación entre LangGraph y FlowRouter (Flujo Híbrido)](#17-coordinación-entre-langgraph-y-flowrouter-flujo-híbrido)
2. [Fase 2: Unificación de Cuentas, 2FA OTP y Seguridad Cross-Channel](#fase-2-unificación-de-cuentas-2fa-otp-y-seguridad-cross-channel)
   - [2.1 Identidad Unificada e IdentityStore](#21-identidad-unificada-e-identitystore)
   - [2.2 Servicio 2FA OTP (`src/services/otp_service.py`)](#22-servicio-2fa-otp-srcservicesotp_servicepy)
   - [2.3 Botón Oficial en WhatsApp `[❌ No soy esta persona]` (Número Equivocado)](#23-botón-oficial-en-whatsapp--no-soy-esta-persona-número-equivocado)
   - [2.4 Interceptores de Onboarding en Messenger e Instagram](#24-interceptores-de-onboarding-en-messenger-e-instagram)
   - [2.5 Seguridad en Telegram: Bloqueo por Dispositivo y Validación de Nombres](#25-seguridad-en-telegram-bloqueo-por-dispositivo-y-validación-de-nombres)
3. [Fase 3: Creación del Bot en Plataformas Externas](#fase-3-creación-del-bot-en-plataformas-externas)
   - [3.1 Telegram (BotFather)](#31-telegram-botfather)
   - [3.2 Meta WhatsApp Cloud API](#32-meta-whatsapp-cloud-api)
   - [3.3 Facebook Messenger e Instagram Direct](#33-facebook-messenger-e-instagram-direct)
4. [Fase 4: Variables de Entorno y Configuración Multi-Plaza (.env)](#fase-4-variables-de-entorno-y-configuración-multi-plaza-env)
5. [Fase 5: Estructura de Carpetas en el Proyecto (`src/channels/`)](#fase-5-estructura-de-carpetas-en-el-proyecto-srcchannels)
6. [Fase 6: Delimitación Geográfica, Radio de Cobertura y Validación de Domicilios](#fase-6-delimitación-geográfica-radio-de-cobertura-y-validación-de-domicilios)
7. [Fase 7: Pruebas, Reinicio de Servidores y Despliegue](#fase-7-pruebas-reinicio-de-servidores-y-despliegue)
8. [✅ Resumen Rápido de Verificación](#-resumen-rápido-de-verificación)

---

## Fase 1: Configuración del Motor LangGraph desde Cero

El cerebro conversacional de los bots utiliza **LangGraph** para gestionar el estado, la memoria por conversación (`thread_id`), la selección de herramientas y la ejecución asistida por LLMs.

### 1.1 Estructura de Carpetas del Grafo
Si estás configurando un nuevo bot o módulo desde cero, crea las siguientes carpetas en `src/`:

```bash
mkdir -p src/state src/nodes src/graphs src/tools tenants/petroil
```

Estructura de archivos resultante:
```text
src/
├── state/
│   ├── __init__.py
│   └── agent_state.py       # Estado global compartido por todos los nodos
├── nodes/
│   ├── __init__.py
│   ├── assistant.py         # Nodo del LLM: genera respuestas y decide herramientas
│   └── tool_executor.py     # Nodo ejecutor: ejecuta las herramientas invocadas
├── graphs/
│   ├── __init__.py
│   └── sales_graph.py       # Ensamblador del StateGraph y compilación con Checkpointer
└── tools/
    ├── __init__.py          # Exportación de herramientas @tool
    ├── order_tools.py       # create_order, cancel_order, get_order_status
    ├── product_tools.py     # search_products, get_promotions
    └── customer_tools.py    # get_customer_info, delete_customer_address
```

---

### 1.2 Definición del Estado (`src/state/agent_state.py`)
El estado es un `TypedDict` que viaja a través de los nodos del grafo:

```python
# src/state/agent_state.py
from __future__ import annotations
from typing import Annotated
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

class SalesAgentState(TypedDict):
    """Estado compartido para el grafo de ventas."""
    # add_messages es el reducer que acumula mensajes en el historial
    messages: Annotated[list[AnyMessage], add_messages]
    matched_products: list[dict]
    product_images: list[str]
    channel: str              # 'whatsapp', 'telegram', 'messenger', 'instagram'
    channel_user_id: str      # wa_id, chat_id, psid o igsid
```

- [ ] **Crear `src/state/agent_state.py`** con el reducer `add_messages` para evitar que los mensajes anteriores se sobreescriban.

---

### 1.3 Implementación de Nodos (`src/nodes/`)

#### 1. Nodo Asistente (`src/nodes/assistant.py`)
Construye el System Prompt con el catálogo dinámico, enlaza las herramientas (`bind_tools`) e invoca al LLM:

```python
# src/nodes/assistant.py
from langchain_core.messages import SystemMessage, trim_messages
from langgraph.types import Command
from src.config.llm_provider import create_llm
from src.config.tenant_config import get_tenant
from src.state.agent_state import SalesAgentState

def assistant_node(state: SalesAgentState, config=None):
    tenant_id = config.get("configurable", {}).get("tenant_id", "petroil")
    tc = get_tenant(tenant_id)
    
    # 1. Crear modelo LLM según la configuración del tenant
    llm = create_llm(tc.llm.provider, tc.llm.model, tc.llm.temperature)
    tools = get_tenant_tools(tc)
    model_with_tools = llm.bind_tools(tools)
    
    # 2. Inyectar System Prompt con personalidad y catálogo
    sys_prompt = _build_system_prompt(tenant_id, state.get("channel"))
    messages = [SystemMessage(content=sys_prompt)] + state["messages"]
    
    # 3. Invocar al modelo
    response = model_with_tools.invoke(messages)
    
    # 4. Enrutamiento con Command: si requiere herramientas va a "tools", si no finaliza
    if response.tool_calls:
        return Command(goto="tools", update={"messages": [response]})
    return Command(goto="__end__", update={"messages": [response]})
```

#### 2. Nodo Ejecutor de Herramientas (`src/nodes/tool_executor.py`)
Ejecuta las `tool_calls` devueltas por el asistente y devuelve el resultado al nodo asistente:

```python
# src/nodes/tool_executor.py
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from src.tools import ALL_TOOLS

def tool_executor_node(state, config=None):
    last_msg = state["messages"][-1]
    tool_map = {t.name: t for t in ALL_TOOLS}
    results = []
    
    for tc in last_msg.tool_calls:
        tool_fn = tool_map.get(tc["name"])
        res = tool_fn.invoke(tc["args"])
        results.append(ToolMessage(content=str(res), tool_call_id=tc["id"]))
        
    # Regresa al asistente para que formule la respuesta final al cliente
    return Command(goto="assistant", update={"messages": results})
```

- [ ] **Crear `src/nodes/assistant.py` y `src/nodes/tool_executor.py`**.

---

### 1.4 Construcción y Compilación del Grafo (`src/graphs/sales_graph.py`)
Conecta los nodos con `StateGraph` y añade persistencia en memoria por hilo:

```python
# src/graphs/sales_graph.py
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, START
from src.nodes.assistant import assistant_node
from src.nodes.tool_executor import tool_executor_node
from src.state.agent_state import SalesAgentState

def build_sales_graph() -> StateGraph:
    builder = StateGraph(SalesAgentState)
    builder.add_node("assistant", assistant_node)
    builder.add_node("tools", tool_executor_node)
    
    # Entrada directa al asistente
    builder.add_edge(START, "assistant")
    return builder

def compile_sales_graph():
    """Compila el grafo con checkpointer para recordar el contexto de cada usuario."""
    builder = build_sales_graph()
    checkpointer = InMemorySaver()
    return builder.compile(checkpointer=checkpointer)
```

- [ ] **Compilar el grafo** para uso en ejecución:
  ```python
  from src.graphs.sales_graph import compile_sales_graph
  graph = compile_sales_graph()
  
  # Invocación pasando thread_id para mantener memoria por conversación
  response = await graph.ainvoke(
      {"messages": [("user", "Hola, cuánto cuesta el gas de 30kg?")]},
      config={"configurable": {"thread_id": f"wa_{wa_id}", "tenant_id": "petroil"}}
  )
  ```

---

### 1.5 Cambio de Nombre del Bot, Personalidad y Prompts (`tenants/<tenant_id>/`)

Para cambiar el **nombre del bot**, su **personalidad** o crear un bot para otra marca o ciudad:

- [ ] **1. Ubicar el archivo de configuración del Tenant:**
  Ruta: `tenants/<tenant_id>/config.yaml` (ej. `tenants/petroil/config.yaml`).

- [ ] **2. Editar los campos de identidad:**
  ```yaml
  tenant_id: "petroil"
  business_name: "Gas a Tu Puerta - Petroil"    # Nombre comercial
  language: "es"

  agent:
    name: "Luke GasSkywalker"                   # << CAMBIAR NOMBRE DEL ASISTENTE AQUÍ
    role: "Asistente virtual de pedidos de gas"
    
    personality: |
      Eres Luke GasSkywalker, el asistente oficial de Gas a Tu Puerta.
      Atiendes con un tono cordial, eficiente y con sutiles referencias amigables.
      
      REGLAS DE ORO:
      1. Haz exactamente UNA SOLA PREGUNTA por mensaje.
      2. No inventes productos ni precios fuera del catálogo oficial.
      3. Siempre solicita confirmación final antes de registrar el pedido.
  ```

- [ ] **3. Inyección Automática en el System Prompt:**
  En `src/nodes/assistant.py`, la función `_build_system_prompt()` lee automáticamente `agent.name`, `business_name`, `agent.personality` y `agent.rules`. **No es necesario modificar código Python para cambiar el nombre del bot**.

- [ ] **4. Crear un nuevo Tenant para otra gasera o ciudad:**
  1. Duplica la carpeta `tenants/petroil/` a `tenants/gascytsa/`.
  2. Modifica `tenant_id: "gascytsa"`, el nombre y el catálogo de productos en `products.json`.
  3. En tus llamadas al grafo o router, especifica `tenant_id="gascytsa"`.

---

### 1.6 Registro de Herramientas del Agente (`src/tools/`)
Las herramientas se definen con el decorador `@tool` de LangChain:

```python
# src/tools/order_tools.py
from langchain_core.tools import tool

@tool
def create_order(customer_phone: str, delivery_address: str, product_id: str, quantity: int) -> dict:
    """Crea un pedido formal de gas LP en el sistema."""
    # Lógica de guardado en base de datos o llamada a API NestJS
    ...
```

- [ ] **Exportar herramientas en `src/tools/__init__.py`** dentro de la lista `ALL_TOOLS` para que el nodo asistente pueda enlazarlas.

---

### 1.7 Coordinación entre LangGraph y FlowRouter (Flujo Híbrido)

El proyecto utiliza una arquitectura **híbrida ultra-eficiente**:
1. **`FlowRouter` (Máquina de Estados Determinista):**
   Maneja el flujo estructurado de compra por botones (Selección de Cilindro -> Dirección -> Horario -> Pago -> Confirmación) con **cero costo de tokens** y latencia de ~50ms.
2. **`LangGraph` (Grafo Conversacional con LLM):**
   Toma el control automáticamente cuando el cliente formula preguntas abiertas (*"¿Qué diferencia hay entre gas LP y gas natural?"*, *"¿Tienen servicio los domingos?"*, o notas de voz).

---

## Fase 2: Unificación de Cuentas, 2FA OTP y Seguridad Cross-Channel

*Nueva funcionalidad crítica*: Permite que un cliente que interactúa desde **Facebook Messenger**, **Instagram Direct**, **WhatsApp** o **Telegram** comparta exactamente la misma cuenta de cliente, historial de pedidos y direcciones guardadas, **sin permitir la suplantación de identidad**.

```
[Usuario en Messenger o Instagram]
           │
           │ Escribe número de teléfono (ej. 6691234567)
           ▼
┌────────────────────────────────────────────────────────┐
│ 1. OTPService genera PIN seguro de 6 dígitos (TTL 10m) │
└────────────────────────────────────────────────────────┘
           │
           │ Envía reto con Botón Interactivo a WhatsApp
           ▼
┌────────────────────────────────────────────────────────┐
│ 2. WhatsApp del Titular del Número:                    │
│    "Código: 582914"                                    │
│    [❌ No soy esta persona]                            │
└────────────────────────────────────────────────────────┘
           │
     ┌─────┴────────────────────────────────┐
     ▼                                      ▼
[Titular presiona botón o dice "no"]   [Usuario ingresa 6 dígitos]
     │                                      │
     ▼                                      ▼
 Solicitud CANCELADA y código          Cuenta VINCULADA y unificada
 DESTRUIDO de inmediato en disco       en IdentityStore y Customer Repo
 (Messenger es bloqueado con aviso)    (Acceso a direcciones y pedidos)
```

### 2.1 Identidad Unificada e IdentityStore
- [ ] **Archivo de persistencia:** `src/repositories/identity_store.py`.
- [ ] La clave primaria universal es el **número celular de 10 dígitos** (`phone`).
- [ ] Mapea `messenger:psid` e `instagram:igsid` al número verificado en `data/channel_identities.json`.
- [ ] Los procesos concurrentes (`telegram_bot.py`, `uvicorn`, workers) leen y escriben en tiempo real de forma segura.

---

### 2.2 Servicio 2FA OTP (`src/services/otp_service.py`)
- [ ] Administra el ciclo de vida de los retos de verificación con TTL de 600 segundos (10 minutos) y máximo 3 intentos.
- [ ] Almacena el estado en `data/otp_linking_cache.json`.
- [ ] Métodos principales:
  - `create_linking_request(channel, channel_user_id, phone, profile_name)`
  - `verify_code(channel, channel_user_id, input_code)`
  - `reject_linking_request(phone, req_id, reason="not_me")` -> **Destruye el código (`code = ""`)** y cancela la solicitud.
  - `confirm_by_whatsapp(phone, req_id)`

---

### 2.3 Botón Oficial en WhatsApp `[❌ No soy esta persona]` (Número Equivocado)

Cuando el usuario en Messenger/Instagram ingresa un teléfono, el bot de WhatsApp envía:
- **Encabezado:** `🔐 Seguridad Gas a Tu Puerta`
- **Cuerpo:**
  > *Detectamos una solicitud para vincular este número de WhatsApp con tu perfil de Facebook Messenger: Oscar López.*\n\n*Tu código de verificación es: 492015 (Válido por 10 minutos).*\n\n*⚠️ ¿No eres tú o se equivocaron de número? Si tú no solicitaste este código, presiona el botón 'No soy esta persona' abajo para cancelar y borrar la solicitud de inmediato.*
- **Botón Interactivo:** `[❌ No soy esta persona]` (`otp_reject:<req_id>`).

#### Comportamiento ante Número Equivocado:
1. Si el titular presiona el botón o responde con texto (*"no soy yo"*, *"se equivocaron"*, *"número equivocado"*, *"cancelar"*):
   - WhatsApp responde:
     > 🛡️ *Solicitud Cancelada y Borrada: Hemos cancelado la solicitud de vinculación. El código ha sido eliminado e invalidado de inmediato. Tu cuenta permanece protegida.*
   - El código se vacía a nivel de datos (`code = ""`).
2. En Messenger / Instagram:
   - Cualquier intento de introducir el código o enviar mensajes genera la alerta:
     > ⛔ *Vinculación Rechazada: El titular del WhatsApp (******1234) indicó que no es esta persona (número equivocado). Por favor verifica tu número y escribe nuevamente tus 10 dígitos correctos.*

---

### 2.4 Interceptores de Onboarding en Messenger e Instagram
En `src/channels/messenger/router.py` y `src/channels/instagram/router.py`:
- [ ] Si el usuario no tiene teléfono vinculado en `IdentityStore` ni en `CustomerRepo`:
  - Se le permite ver el catálogo público libremente (`client_svc:cilindro`, etc.).
  - Al dar clic en "Comprar" o solicitar un pedido, se activa el interceptor pidiendo sus 10 dígitos.
  - Se genera el reto 2FA hacia su WhatsApp.
  - Una vez confirmado, se unifica con su cuenta de cliente global.

---

### 2.5 Seguridad en Telegram: Bloqueo por Dispositivo y Validación de Nombres
En los bots de Telegram (`telegram_bot_test.py`, `telegram_bot_gascytsa.py`, `telegram_bot_hermosillo.py`):
- [ ] **Bloqueo por Dispositivo:** El cliente sólo puede registrar su teléfono presionando el botón nativo de Telegram `KeyboardButton(text="📱 Compartir mi teléfono", request_contact=True)`. No se permite falsear números escribiéndolos por texto.
- [ ] **Validación Semántica de Nombres con IA (`validate_human_full_name`):**
  - Rechaza groserías, nombres ficticios (*"Batman"*, *"El Chavo"*), cadenas aleatorias (*"asdasd"*) o nombres de una sola letra.
  - Exige Nombre y Apellido válidos antes de crear el perfil de cliente.
- [ ] **Borrado Inmediato de Mensajes no Verificados:** El bot elimina automáticamente de la conversación mensajes con números o textos extraños que no sigan el flujo seguro.

---

## Fase 3: Creación del Bot en Plataformas Externas

### 3.1 Telegram (BotFather)
- [ ] **1. Iniciar conversación con BotFather:**
  - Busca `@BotFather` en Telegram y envía `/newbot`.
- [ ] **2. Nombre y Username:**
  - **Nombre visible:** Ej. `Gas a Tu Puerta - Luke GasSkywalker`.
  - **Username:** Ej. `Luke_GaSkywalker_bot`.
- [ ] **3. Guardar Token:**
  - Guárdalo como `TELEGRAM_BOT_TOKEN`.
- [ ] **4. Comandos del menú (`/setcommands`):**
  ```text
  start - Iniciar toma de pedido o saludar
  pedido - Levantar un pedido de gas
  estatus - Consultar estado de mi pedido
  cancelar - Cancelar mi pedido activo
  ayuda - Hablar con soporte o ver información
  ```

---

### 3.2 Meta WhatsApp Cloud API
- [ ] **1. Crear App en [developers.facebook.com](https://developers.facebook.com/):**
  - Tipo: **Negocio** (Business).
- [ ] **2. Producto WhatsApp:**
  - Copia `Phone Number ID` y `WABA ID`.
  - Genera el token de usuario del sistema permanente con permisos `whatsapp_business_messaging` y `whatsapp_business_management`.
- [ ] **3. Configurar Webhook:**
  - URL de callback: `https://<TU-DOMINIO>/webhooks/whatsapp`
  - Token de verificación: `petroil_gas_webhook_secret`
  - Suscripción al campo: `messages`.

---

### 3.3 Facebook Messenger e Instagram Direct
- [ ] **1. Fan Page y Cuenta Profesional:**
  - Ten tu Fan Page de Facebook y cuenta comercial de Instagram vinculadas en Meta Business Suite.
- [ ] **2. Producto Messenger en Meta Dev:**
  - Genera el `MESSENGER_PAGE_ACCESS_TOKEN`.
- [ ] **3. Permisos en Instagram:**
  - En la app de Instagram -> Configuración -> Privacidad -> Mensajes -> Activar **"Permitir acceso a los mensajes"**.
- [ ] **4. Webhooks:**
  - Messenger: `https://<TU-DOMINIO>/webhooks/messenger` (eventos: `messages`, `messaging_postbacks`).
  - Instagram: `https://<TU-DOMINIO>/webhooks/instagram` (eventos: `messages`, `messaging_postbacks`).

---

## Fase 4: Variables de Entorno y Configuración Multi-Plaza (.env)

- [ ] **1. Configurar archivo `.env`:**

```env
# ==========================================
# 1. PROVEEDORES LLM
# ==========================================
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
OPENROUTER_API_KEY=sk-or-v1-...

# ==========================================
# 2. CANALES TELEGRAM (MULTI-BOT / MULTI-PLAZA)
# ==========================================
TELEGRAM_BOT_TOKEN=8913254382:AAE3FCTlrU0EYiFGdNMsRBxCifTIfh_nba0      # Luke GasSkywalker (Mazatlán)
TELEGRAM_BOT_GASCYTSA_TOKEN=8376224866:AAGyLKjKreB4gDUkYI1IGnCBVah3... # Gascytsa (Culiacán)
TELEGRAM_BOT_HERMOSILLO_TOKEN=8633811568:AAH2qf9biMHCdEM_5_rg1e...     # GasPet (Hermosillo)
TELEGRAM_DRIVER_BOT_TOKEN=987654321:ZYXwvuTsRQPonMlKjIhGfEdCbA          # Bot de Choferes

# ==========================================
# 3. META WHATSAPP CLOUD API
# ==========================================
WHATSAPP_TOKEN=EAAB...
WHATSAPP_PHONE_NUMBER_ID=104928374650192
WHATSAPP_BUSINESS_ACCOUNT_ID=192837465019283
WHATSAPP_VERIFY_TOKEN=petroil_gas_webhook_secret
WHATSAPP_API_VERSION=v21.0

# ==========================================
# 4. FACEBOOK MESSENGER & INSTAGRAM DIRECT
# ==========================================
MESSENGER_PAGE_ACCESS_TOKEN=EAAB...
MESSENGER_VERIFY_TOKEN=petroil_gas_webhook_secret
MESSENGER_PAGE_ID=10928374650192

INSTAGRAM_ACCESS_TOKEN=EAAB...
INSTAGRAM_VERIFY_TOKEN=petroil_gas_webhook_secret
INSTAGRAM_ACCOUNT_ID=178414000000000

# ==========================================
# 5. COBERTURA GEOGRÁFICA Y PLAZA BASE
# ==========================================
DEFAULT_CITY="Mazatlán, Sinaloa, México"
TENANT_ID=petroil
DATA_SOURCE=api
API_BASE_URL=https://tu-api-backend.petroil.dev/api
```

- [ ] **2. Sincronización Dinámica de Credenciales:**
  El endpoint `GET /api/settings/sync` permite refrescar credenciales desde el backend sin reiniciar los servicios.

---

## Fase 5: Estructura de Carpetas en el Proyecto (`src/channels/`)

Cada canal cuenta con su carpeta desacoplada:

```text
src/channels/
├── base.py                   # Contratos e interfaces base
├── telegram/
│   ├── adapter.py            # Formateo y llamadas a Telegram Bot API
│   └── router.py             # Router webhook para Telegram
├── whatsapp/
│   ├── adapter.py            # Envío de botones interactivos, listas y plantillas
│   └── router.py             # Endpoints GET/POST y handlers de 2FA OTP
├── messenger/
│   ├── adapter.py            # Generic templates, botones y quick replies
│   └── router.py             # Interceptor de onboarding 2FA y postbacks
├── instagram/
│   ├── adapter.py            # Quick replies y mensajes directos
│   └── router.py             # Interceptor de onboarding 2FA de Instagram
└── web/
    └── router.py             # Chat widget web
```

- [ ] **Verificar registro de rutas en `src/app.py`:**
  ```python
  app.include_router(whatsapp_router, prefix="/webhooks/whatsapp")
  app.include_router(messenger_router, prefix="/webhooks/messenger")
  app.include_router(instagram_router, prefix="/webhooks/instagram")
  app.include_router(telegram_router, prefix="/webhooks/telegram")
  ```

---

## Fase 6: Delimitación Geográfica, Radio de Cobertura y Validación de Domicilios

Validación en 3 niveles para blindar las entregas:

```
[Dirección ingresada] ──> [1. Filtro Anti-Bromas] ──> [2. Auditor Semántico LLM] ──> [3. Geocodificación y Radio Haversine]
```

- [ ] **1. Ciudad Base en `src/services/geocoding.py`:**
  ```python
  DEFAULT_LAT = 23.201400
  DEFAULT_LNG = -106.421500
  ```
- [ ] **2. Radio Máximo de Cobertura:**
  Valida que el domicilio esté dentro del radio operativo (ej. `<= 75.0 km`).
- [ ] **3. Auditor Semántico de Direcciones (`src/services/address_validator.py`):**
  Exige calle, número exterior y colonia antes de aceptar el pedido.

---

## Fase 7: Pruebas, Reinicio de Servidores y Despliegue

### 7.1 Reinicio de Servidores (¡Crucial para ver cambios en código!)
> [!IMPORTANT]
> En Python, los módulos se cargan en la memoria RAM al arrancar. Cualquier cambio en archivos `.py` requiere reiniciar el proceso o usar la bandera `--reload`.

- [ ] **Servidor FastAPI / Webhooks:**
  ```bash
  # Iniciar con detección de cambios automática:
  .\.venv\Scripts\python.exe -m uvicorn src.app:app --host 0.0.0.0 --port 3000 --reload
  # O con uv:
  uv run uvicorn src.app:app --host 0.0.0.0 --port 3000 --reload
  ```

- [ ] **Bots de Telegram Concurrentes:**
  ```bash
  # Iniciar bot de Mazatlán:
  .\.venv\Scripts\python.exe telegram_bot_test.py
  # Iniciar bot de Culiacán:
  .\.venv\Scripts\python.exe telegram_bot_gascytsa.py
  # Iniciar bot de Hermosillo:
  .\.venv\Scripts\python.exe telegram_bot_hermosillo.py
  ```

---

### 7.2 Ejecución de la Suite Completa de Pruebas Unitarias

- [ ] **1. Pruebas de 2FA OTP, Vinculación Social y Botón Rechazo en WhatsApp:**
  ```bash
  .\.venv\Scripts\python.exe -m unittest tests/test_otp_and_social_linking.py
  ```
- [ ] **2. Pruebas de Ciclo de Vida del Catálogo y Carrusel en Messenger:**
  ```bash
  .\.venv\Scripts\python.exe -m unittest tests/test_messenger_carousel_lifecycle.py
  ```
- [ ] **3. Pruebas de Direcciones y Botones de WhatsApp:**
  ```bash
  .\.venv\Scripts\python.exe -m unittest tests/test_messenger_addresses.py tests/test_whatsapp_extra_features.py
  ```
- [ ] **4. Pruebas de Validación Semántica de Domicilios:**
  ```bash
  .\.venv\Scripts\python.exe -m unittest tests/test_address_validation.py
  ```

---

### 7.3 Despliegue en Servidor con Docker
- [ ] Compilar y levantar contenedores en segundo plano:
  ```bash
  docker compose build
  docker compose up -d
  ```

---

## ✅ Resumen Rápido de Verificación

| # | Elemento / Fase | Archivo / Componente Clave | Estado |
| :-: | :--- | :--- | :-: |
| **1** | Estado TypedDict con reducer `add_messages` | `src/state/agent_state.py` | [ ] |
| **2** | Nodos del Grafo (`assistant_node`, `tool_executor`) | `src/nodes/assistant.py`, `tool_executor.py` | [ ] |
| **3** | Grafo compilado con memoria por hilo | `src/graphs/sales_graph.py` | [ ] |
| **4** | Nombre del bot y personalidad configurados | `tenants/petroil/config.yaml` | [ ] |
| **5** | Herramientas `@tool` exportadas en `ALL_TOOLS` | `src/tools/__init__.py` | [ ] |
| **6** | Servicio 2FA OTP y caché de vinculación | `src/services/otp_service.py` | [ ] |
| **7** | Botón WhatsApp `[❌ No soy esta persona]` (Número equivocado) | `src/channels/whatsapp/router.py` | [ ] |
| **8** | Interceptor de onboarding seguro en Messenger e Instagram | `src/channels/messenger/router.py`, `instagram/` | [ ] |
| **9** | Bloqueo por dispositivo y validación de nombres con IA | `telegram_bot_test.py`, `telegram_bot_*.py` | [ ] |
| **10** | Tokens y variables configuradas en `.env` | `.env` | [ ] |
| **11** | Ciudad base, radio <= 75km y geocodificación | `src/services/geocoding.py` | [ ] |
| **12** | Servidor Uvicorn corriendo con `--reload` | `src/app.py` | [ ] |
| **13** | Pruebas unitarias de OTP y canales aprobadas | `tests/test_otp_and_social_linking.py` | [ ] |
