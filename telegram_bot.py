"""Telegram Bot adapter for the LangGraph multi-tenant sales agent."""

import logging
import re
import sys
from datetime import datetime
from typing import Any

# Forzar UTF-8 en terminal de Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from langchain_core.messages import HumanMessage
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from src.config.settings import get_settings
from src.config.tenant_config import get_tenant
from src.database import init_db
from src.graphs.sales_graph import compile_sales_graph
from src.models.customer import CustomerAddress
from src.repositories import get_repository
from src.services.audio_transcription import transcribe_audio_file
from src.services.flow_router import FlowResponse, FlowState, flow_router, get_or_create_session
from src.services.geocoding import resolve_gps_address_to_name, reverse_geocode
from src.services.notifications import notify_driver
from src.tools.get_order_status import format_clean_driver_status

# Configurar logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Configuración del tenant
TENANT_ID = "petroil"
tenant = get_tenant(TENANT_ID)
graph = compile_sales_graph()

# Token del bot de clientes
settings = get_settings()
TELEGRAM_BOT_TOKEN = settings.telegram_bot_token

# Inicializar base de datos SQLite
init_db()


def get_markup_for_flow_response(flow_res: FlowResponse, phone: str = "", user_id: str = "") -> InlineKeyboardMarkup | None:
    """Selecciona el markup interactivo apropiado según la acción o estado del flujo."""
    if flow_res.action_performed == "show_edit_options":
        return get_botones_editar_opciones()

    # Si la acción solicita explícitamente texto libre para la programación:
    if flow_res.action_performed == "ask_schedule_text":
        return None

    # Los estados que requieren texto libre del usuario NUNCA deben mostrar botones interactivos
    if flow_res.state in (
        FlowState.WAITING_FOR_PHONE,
        FlowState.WAITING_FOR_NEW_CUSTOMER_NAME,
        FlowState.WAITING_FOR_NEW_CUSTOMER_ADDRESS,
        FlowState.WAITING_FOR_STATIONARY_DETAILS,
    ):
        return None

    if flow_res.action_performed == "show_service_buttons" or flow_res.state == FlowState.INITIAL:
        return get_botones_tipo_servicio()
    elif flow_res.action_performed == "show_cylinder_catalog" or flow_res.state == FlowState.WAITING_FOR_PRODUCT_OR_QUANTITY:
        return get_botones_productos_cilindros()
    elif flow_res.action_performed == "show_delete_address_buttons":
        repo = get_repository()
        cust = repo.get_customer_by_phone(TENANT_ID, phone) if phone else None
        if not cust and not phone and user_id:
            cust = repo.get_customer(TENANT_ID, "telegram", str(user_id))
        addrs = cust.addresses if (cust and cust.addresses) else []
        if addrs:
            return get_botones_eliminar_direcciones(addrs)
        return None
    elif flow_res.action_performed == "show_delete_confirm_buttons":
        sess = flow_router.get_session(f"telegram:{TENANT_ID}:{user_id}") if user_id else None
        pending_aid = getattr(sess, "_pending_delete_address_id", "") if sess else ""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑️ Sí, eliminar dirección", callback_data=f"client_addr_del_confirm:{pending_aid}:1")],
            [InlineKeyboardButton("❌ No, cancelar", callback_data="client_addr_del_menu")]
        ])
    elif flow_res.action_performed == "show_address_buttons" or flow_res.state == FlowState.WAITING_FOR_ADDRESS_SELECTION:
        repo = get_repository()
        cust = repo.get_customer_by_phone(TENANT_ID, phone) if phone else None
        if not cust and not phone and user_id:
            cust = repo.get_customer(TENANT_ID, "telegram", str(user_id))
        addrs = cust.addresses if (cust and cust.addresses) else ([CustomerAddress(id=1, address=cust.address, alias="Principal")] if cust and cust.address else [])
        if addrs:
            return get_botones_direcciones_cliente(addrs)
        return None
    elif flow_res.action_performed == "show_schedule_alternative":
        return get_botones_horario_alternativo(flow_res.text)
    elif flow_res.action_performed == "show_schedule_buttons" or flow_res.state == FlowState.WAITING_FOR_SCHEDULE:
        return get_botones_programacion_entrega()
    elif flow_res.action_performed == "show_payment_buttons" or flow_res.state == FlowState.WAITING_FOR_PAYMENT_METHOD:
        return get_botones_metodo_pago()
    elif flow_res.action_performed == "show_confirmation" or flow_res.state == FlowState.WAITING_FOR_CONFIRMATION:
        return get_botones_resumen_confirmacion()

    elif flow_res.action_performed == "order_created":
        match_order = re.search(r"(?:pedido|folio)\s*#?\s*(\d+)", flow_res.text, re.IGNORECASE)
        if match_order:
            return get_botones_pedido_activo(match_order.group(1))
    return detectar_botones_mensaje(flow_res.text, phone=phone, channel_user_id=str(user_id))


def get_teclado_cliente() -> ReplyKeyboardMarkup:
    """Teclado de acceso rápido para el cliente."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📍 Compartir Mi Ubicación Actual", request_location=True)],
        ],
        resize_keyboard=True,
    )


def get_botones_tipo_servicio() -> InlineKeyboardMarkup:
    """Botones interactivos para elegir tipo de servicio al inicio."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🛻 Cilindro de Gas", callback_data="client_svc:cilindro"),
                InlineKeyboardButton("🚛 Tanque Estacionario", callback_data="client_svc:estacionario"),
            ]
        ]
    )


def get_botones_editar_opciones() -> InlineKeyboardMarkup:
    """Botones interactivos para seleccionar qué dato del pedido corregir o editar."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⏰ Cambiar Horario", callback_data="client_edit:schedule"),
                InlineKeyboardButton("📍 Cambiar Dirección", callback_data="client_edit:address"),
            ],
            [
                InlineKeyboardButton("💳 Cambiar Forma de Pago", callback_data="client_edit:payment"),
                InlineKeyboardButton("📦 Cambiar Producto", callback_data="client_edit:product"),
            ],
            [
                InlineKeyboardButton("📱 Cambiar Teléfono", callback_data="client_edit:phone"),
                InlineKeyboardButton("🔙 Volver al Resumen", callback_data="client_edit:back"),
            ],
        ]
    )



def get_catalogo_productos_db(tenant_id: str = "petroil") -> list:
    """Obtiene los productos activos en existencia directamente desde la base de datos SQLite."""
    try:
        repo = get_repository()
        prods = repo.get_all_products(tenant_id)
        # Filtrar cilindros y productos de gas en existencia (in_stock == True / 1)
        cilindros = [
            p for p in prods
            if bool(getattr(p, "in_stock", True)) and (
                (getattr(p, "category", "") or "").lower() in ("cilindros", "gas lp", "gas")
                or "cilindro" in p.name.lower()
                or "gas" in p.name.lower()
                or "kg" in p.name.lower()
            )
            and "estacionario" not in p.name.lower()
            and p.id != "entrega-domicilio"
            and "servicio" not in (getattr(p, "category", "") or "").lower()
        ]
        if cilindros:
            def sort_key(p):
                m = re.search(r"(\d+)\s*kg", p.name, re.IGNORECASE)
                if m:
                    return (0, int(m.group(1)))
                return (1, p.price)
            return sorted(cilindros, key=sort_key)
        elif prods:
            return []
    except Exception as e:
        logger.error(f"Error cargando catálogo desde BD: {e}")

    # Fallback predeterminado de cilindros estándar
    from src.models.product import Product
    return [
        Product(id="gas-lp-10kg", tenant_id="petroil", name="Cilindro 10 kg", price=230.0, description="Cilindro 10 kg", category="CILINDRO", unit="pieza"),
        Product(id="gas-lp-20kg", tenant_id="petroil", name="Cilindro 20 kg", price=450.0, description="Cilindro 20 kg", category="CILINDRO", unit="pieza"),
        Product(id="gas-lp-30kg", tenant_id="petroil", name="Cilindro 30 kg", price=670.0, description="Cilindro 30 kg", category="CILINDRO", unit="pieza"),
        Product(id="gas-lp-45kg", tenant_id="petroil", name="Cilindro 45 kg", price=990.0, description="Cilindro 45 kg", category="CILINDRO", unit="pieza"),
    ]


def get_botones_productos_cilindros(carrito: dict[str, int] | None = None) -> InlineKeyboardMarkup:
    """Botones interactivos dinámicos generados desde la base de datos SQLite."""
    carrito = carrito or {}
    total_items = sum(carrito.values())
    prods = get_catalogo_productos_db()

    botones_fila = []
    filas = []

    for p in prods:
        m_kg = re.search(r"(\d+\s*kg)", p.name, re.IGNORECASE)
        label_size = m_kg.group(1).upper() if m_kg else p.name
        if len(label_size) > 16:
            label_size = label_size[:15] + ".."

        cant = carrito.get(p.id, 0)
        c_tag = f" ({cant})" if cant > 0 else ""

        btn_text = f"+ {label_size} (${p.price:.0f}){c_tag}"
        botones_fila.append(InlineKeyboardButton(btn_text, callback_data=f"cart_add:{p.id}"))

        if len(botones_fila) == 2:
            filas.append(botones_fila)
            botones_fila = []

    if botones_fila:
        filas.append(botones_fila)

    if total_items > 0:
        filas.append([
            InlineKeyboardButton("🗑️ Vaciar", callback_data="cart_clear"),
            InlineKeyboardButton(f"✅ Continuar ({total_items}) ➡️", callback_data="cart_checkout"),
        ])

    return InlineKeyboardMarkup(filas)


def texto_resumen_catalogo(carrito: dict[str, int] | None = None) -> str:
    """Genera el texto de catálogo con el resumen interactivo del carrito sin redundancias."""
    prods = get_catalogo_productos_db()

    if not carrito or sum(carrito.values()) == 0:
        return "🛒 **Selección de Cilindros:**\nSelecciona en los botones de abajo los cilindros que necesitas (o escribe tu pedido si lo prefieres):"

    lineas_carrito = []
    total_pesos = 0.0
    prods_by_id = {p.id: p for p in prods}

    for pid, cant in carrito.items():
        if cant > 0 and pid in prods_by_id:
            p = prods_by_id[pid]
            sub = cant * p.price
            total_pesos += sub
            lineas_carrito.append(f"• **{cant}x {p.name}** — ${sub:.2f} MXN")

    return (
        "🛒 **Tu selección actual:**\n" +
        "\n".join(lineas_carrito) + "\n" +
        f"💰 **Total acumulado:** ${total_pesos:.2f} MXN\n\n" +
        "Puedes tocar más botones para agregar más piezas o presionar **'✅ Continuar'** para seguir con tu pedido."
    )


def get_botones_direcciones_cliente(addresses: list[CustomerAddress]) -> InlineKeyboardMarkup:
    """Genera botones interactivos para cada dirección guardada del cliente + opción de nueva dirección y eliminar."""
    botones = []
    for i, addr in enumerate(addresses, 1):
        addr_text = resolve_gps_address_to_name(addr.address.strip())
        addr_text = re.sub(r"^(?:\[(?:Nueva\s*Direcci[oó]n|Direcci[oó]n(?:\s*\d+)?|Principal)\]\s*)+", "", addr_text, flags=re.I).strip()
        short_addr = f"{i}. 📍 {addr_text}"
        if len(short_addr) > 42:
            short_addr = short_addr[:39] + "..."
        botones.append([InlineKeyboardButton(short_addr, callback_data=f"client_addr:{i}")])

    botones.append([InlineKeyboardButton("➕ Ingresar nueva dirección", callback_data="client_addr:new")])
    if addresses:
        botones.append([InlineKeyboardButton("🗑️ Eliminar una dirección", callback_data="client_addr_del_menu")])
    return InlineKeyboardMarkup(botones)


def get_botones_eliminar_direcciones(addresses: list[CustomerAddress]) -> InlineKeyboardMarkup:
    """Genera botones para seleccionar cuál dirección eliminar de la cuenta."""
    botones = []
    for i, addr in enumerate(addresses, 1):
        addr_text = resolve_gps_address_to_name(addr.address.strip())
        addr_text = re.sub(r"^(?:\[(?:Nueva\s*Direcci[oó]n|Direcci[oó]n(?:\s*\d+)?|Principal)\]\s*)+", "", addr_text, flags=re.I).strip()
        short_addr = f"🗑️ {i}. {addr_text}"
        if len(short_addr) > 42:
            short_addr = short_addr[:39] + "..."
        botones.append([InlineKeyboardButton(short_addr, callback_data=f"client_addr_del:{addr.id}:{i}")])

    botones.append([InlineKeyboardButton("🔙 Volver a selección de dirección", callback_data="client_addr_back")])
    return InlineKeyboardMarkup(botones)


def get_botones_programacion_entrega() -> InlineKeyboardMarkup:
    """Botones interactivos para elegir horario de entrega (Lo antes posible o Programar)."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⚡ Lo antes posible", callback_data="client_sch:asap"),
            ],
            [
                InlineKeyboardButton("📅 Programar entrega", callback_data="client_sch:custom"),
            ],
        ]
    )


def get_botones_horario_alternativo(text: str = "") -> InlineKeyboardMarkup:
    """Botones interactivos para aceptar horario alternativo sugerido o elegir otro."""
    m = re.search(r"disponibilidad libre a las \*\*([^*]+)\*\*", text)
    time_label = m.group(1).strip() if m else "este horario"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(f"✅ Sí, aceptar {time_label}", callback_data="client_sch_accept"),
            ],
            [
                InlineKeyboardButton("📅 Indicar otro horario", callback_data="client_sch:custom"),
            ],
        ]
    )


def get_botones_metodo_pago() -> InlineKeyboardMarkup:
    """Botones interactivos para seleccionar método de pago."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("💵 Efectivo", callback_data="client_pay:efectivo"),
                InlineKeyboardButton("💳 Terminal (Tarjeta)", callback_data="client_pay:terminal"),
            ]
        ]
    )


def get_botones_resumen_confirmacion() -> InlineKeyboardMarkup:
    """Botones interactivos para confirmar, editar o cancelar el pedido en el resumen."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Sí, Confirmar Pedido", callback_data="client_confirm:yes"),
            ],
            [
                InlineKeyboardButton("✏️ Modificar Datos", callback_data="client_confirm:edit"),
                InlineKeyboardButton("❌ Cancelar", callback_data="client_confirm:cancel"),
            ],
        ]
    )


def get_botones_pedido_activo(order_id: int | str) -> InlineKeyboardMarkup:
    """Botones interactivos para pedidos activos (confirmados o en camino)."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📍 Ver Estatus", callback_data=f"check_order_status:{order_id}"),
                InlineKeyboardButton("❌ Cancelar Pedido", callback_data=f"cancel_order_client:{order_id}"),
            ]
        ]
    )


def get_botones_confirmar_cancelacion(order_id: int | str) -> InlineKeyboardMarkup:
    """Botones para validar si el cliente realmente desea cancelar su pedido."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⚠️ Sí, Cancelar Pedido", callback_data=f"confirm_cancel_order_client:{order_id}"),
                InlineKeyboardButton("🔙 No, Conservar Pedido", callback_data=f"keep_order_client:{order_id}"),
            ]
        ]
    )


def detectar_botones_mensaje(respuesta: str, phone: str = "", channel_user_id: str = "") -> InlineKeyboardMarkup | None:
    """Detecta si la respuesta del asistente debe llevar botones contextuales."""
    resp_lower = respuesta.lower()

    # 0. ¿Es confirmación de cancelación de pedido?
    if any(k in resp_lower for k in ["confirmación de cancelación", "confirmacion de cancelacion", "¿estás seguro de que deseas cancelar", "seguro de que deseas cancelar"]):
        match_order = re.search(r"(?:pedido|folio)\s*#?\s*(\d+)", respuesta, re.IGNORECASE)
        if match_order:
            return get_botones_confirmar_cancelacion(match_order.group(1))

    # 1. ¿Es un pedido ya creado/confirmado en BD o consulta de historial/estatus? -> GUARD ESTRICTO: NINGÚN BOTÓN
    is_confirmed_order_or_history = any(k in resp_lower for k in [
        "pedido confirmado", "pedido ha sido registrado", "registrado con el folio",
        "pedido registrado", "creado exitosamente", "asignado a chofer",
        "registrado exitosamente", "registrada exitosamente",
        "nuestro repartidor se comunicará", "nuestro repartidor se comunicara",
        "gracias por tu preferencia", "¡gracias por tu preferencia!", "gracias por confiar",
        "historial de tus pedidos", "encontré", "encontre", "pedidos en tu historial",
        "información de tu pedido", "informacion de tu pedido", "estatus de tu pedido",
        "se encontraron", "tus pedidos registrados", "detalles de tu pedido"
    ]) or (
        "pedido #" in resp_lower and any(k in resp_lower for k in ["estado:", "confirmado", "entregado", "en ruta", "cancelado"])
        and not any(k in resp_lower for k in ["¿deseas confirmar", "¿confirmamos", "resumen de tu pedido"])
    )
    if is_confirmed_order_or_history:
        match_order = re.search(r"(?:pedido|folio)\s*#?\s*(\d+)", respuesta, re.IGNORECASE)
        if match_order:
            order_id = match_order.group(1)
            es_inactivo = any(k in resp_lower for k in ["cancelado", "entregado", "finalizado"])
            es_activo = any(k in resp_lower for k in ["confirmado", "en camino", "en ruta", "agendado", "programado", "asignado"])
            if es_activo and not es_inactivo:
                return get_botones_pedido_activo(order_id)
        return None

    # Detectar si el mensaje es una explicación general del servicio, bienvenida o mensaje de seguridad/límites
    es_explicacion_general_o_seguridad = any(k in resp_lower for k in [
        "con gusto te explico", "mi servicio", "mi función", "soy el asistente",
        "asistente virtual", "puedo ayudarte con", "el proceso de pedido es",
        "te pregunto qué necesitas", "no puedo decodificar", "no tengo capacidad ni autorización",
        "únicamente de atención", "payload", "atención al cliente", "asistente de **gas a tu puerta",
        "¿te gustaría hacer un pedido", "¿te gustaría que te ayude con tu pedido",
        "¿te gustaría realizar un pedido", "¿deseas hacer un pedido", "bienvenido a gas a tu puerta"
    ])

    # 2. ¿Es el resumen del pedido esperando confirmación del cliente? (PASO 6)
    if not es_explicacion_general_o_seguridad and (
        any(k in resp_lower for k in [
            "resumen de tu pedido", "datos de tu pedido", "detalles de tu pedido", "información de tu pedido",
            "tu pedido sería", "tu pedido es:", "resumen completo"
        ])
        and any(k in resp_lower for k in [
            "confirmar", "confírmame", "confirmame", "correctos", "proceder", "procesar",
            "procedo", "de acuerdo", "¿está todo bien", "¿esta todo bien"
        ])
        and ("total:" in resp_lower or "$" in resp_lower)
    ):
        return get_botones_resumen_confirmacion()

    # 3. ¿Es pregunta específica sobre cómo pagará el cliente? (PASO 5: Efectivo o Terminal)
    es_pregunta_pago = not es_explicacion_general_o_seguridad and (
        any(k in resp_lower for k in [
            "en efectivo o con terminal", "en efectivo o terminal", "efectivo o tarjeta",
            "efectivo o con tarjeta", "pagarás en efectivo", "pagaras en efectivo",
            "cómo deseas pagar", "como deseas pagar", "cómo te gustaría pagar", "como te gustaria pagar",
            "cómo prefieres pagar", "como prefieres pagar",
            "cómo prefieres realizar el pago", "como prefieres realizar el pago",
            "cómo deseas realizar el pago", "como deseas realizar el pago",
            "deseas realizar el pago", "prefieres realizar el pago",
            "realizar el pago", "realizarás el pago", "realizaras el pago",
            "deseas pagar en efectivo", "cuál será tu forma de pago", "cual sera tu forma de pago",
            "forma de pago será", "forma de pago sera", "cuál eliges", "cual eliges"
        ])
        or (
            ("pago" in resp_lower or "pagar" in resp_lower)
            and any(k in resp_lower for k in [
                "efectivo", "terminal", "tarjeta", "cómo", "como", "cuál", "cual",
                "prefieres", "deseas", "método", "metodo", "forma", "opciones", "medio", "eliges"
            ])
            and not any(k in resp_lower for k in ["te pregunto", "proceso", "guiado", "siguiente paso"])
        )
    )
    if es_pregunta_pago:
        return get_botones_metodo_pago()

    # 4. GUARD ESTRICTO DE HORARIO/FECHA O ESCRITURA DE NUEVA DIRECCIÓN (PASO 4) -> NINGÚN BOTÓN
    es_solicitud_escritura_nueva_direccion = (
        any(k in resp_lower for k in [
            "indícame tu nueva dirección", "indicame tu nueva direccion",
            "indícame la nueva dirección", "indicame la nueva direccion",
            "indícame una nueva dirección", "indicame una nueva direccion",
            "indicarme una nueva dirección", "indicarmela una nueva direccion",
            "proporciona los datos de tu nueva dirección", "proporciona los datos de tu nueva direccion",
            "proporciona tu nueva dirección", "proporciona tu nueva direccion",
            "proporcióname tu nueva dirección", "proporcioname tu nueva direccion",
            "proporcióname los datos de tu nueva dirección", "proporcioname los datos de tu nueva direccion",
            "escribe tu nueva dirección", "escribe tu nueva direccion",
            "escribe tu dirección", "escribe tu direccion",
            "ingresa tu nueva dirección", "ingresa tu nueva direccion",
            "ingresa tu dirección", "ingresa tu direccion",
            "compárteme tu nueva dirección", "comparteme tu nueva direccion",
            "compárteme tu dirección", "comparteme tu direccion",
            "comparte tu nueva dirección", "comparte tu nueva direccion",
            "comparte tu ubicación o escribe", "comparte tu ubicacion o escribe",
            "calle, número", "calle, numero", "calle y número", "calle y numero",
            "colonia y referencias", "número exterior", "numero exterior",
            "indícame la dirección completa", "indicame la direccion completa",
            "indícame tu dirección completa", "indicame tu direccion completa",
            "cuál es tu dirección completa", "cual es tu direccion completa",
            "por favor compárteme tu ubicación", "por favor comparteme tu ubicacion",
            "por favor indícame la calle", "por favor indicame la calle",
            "para registrarla en tu pedido", "para registrarla en el sistema",
            "cuál es la nueva dirección", "cual es la nueva direccion"
        ])
        and not any(k in resp_lower for k in [
            "botones interactivos", "seleccionar tu dirección", "seleccionar tu direccion",
            "selecciona tu dirección", "selecciona tu direccion", "a cuál de tus direcciones", "cual de tus direcciones"
        ])
    )

    if not es_explicacion_general_o_seguridad and es_solicitud_escritura_nueva_direccion:
        return None

    # Pregunta por programación de entrega (Lo antes posible / Programar entrega)
    if not es_explicacion_general_o_seguridad and any(k in resp_lower for k in [
        "qué día", "que dia", "¿qué día", "¿que dia",
        "recibir tu pedido", "cuándo deseas", "cuando deseas", "cuándo te gustaría", "cuando te gustaria",
        "fecha de entrega", "programar tu entrega", "a qué hora", "a que hora", "cuándo requieres", "cuando requieres"
    ]):
        if not any(k in resp_lower for k in ["indícame la hora", "indicame la hora", "escribe la hora", "hora y el día", "hora y el dia"]):
            return get_botones_programacion_entrega()
        return None

    # 5. ¿Es selección de DIRECCIÓN para cliente (PASO 3)?
    # NOTA: Se generan botones para que las direcciones salgan en botones y optimizar_respuesta_con_botones limpia el texto
    es_pregunta_direccion = not es_explicacion_general_o_seguridad and not es_solicitud_escritura_nueva_direccion and any(k in resp_lower for k in [
        "dirección registrada", "direccion registrada", "direcciones registradas",
        "direcciones guardadas", "dirección guardada", "direccion guardada",
        "dirección(es) guardadas", "direccion(es) guardadas",
        "domicilio registrado", "domicilios registrados", "domicilio guardado", "domicilios guardados",
        "siguientes direcciones", "direcciones para ti",
        "seleccionar tu dirección", "seleccionar tu direccion",
        "selecciona tu dirección", "selecciona tu direccion",
        "seleccionar dirección", "seleccionar direccion",
        "selecciona dirección", "selecciona direccion",
        "seleccionar tu domicilio", "seleccionar domicilio", "selecciona tu domicilio",
        "botones interactivos", "botones interactivos de la pantalla", "botones de la pantalla",
        "a cuál de tus direcciones", "cual de tus direcciones",
        "a cuál de tus", "a cual de tus",
        "a cuál de estas direcciones", "cual de estas direcciones",
        "a cuál de ellas", "a cual de ellas",
        "a cuál de esas direcciones", "a cual de esas direcciones",
        "misma dirección", "misma direccion",
        "deseas que entreguemos en", "deseas que enviemos a",
        "deseas que te lo enviemos a", "deseas que te la enviemos a",
        "deseas recibir tu pedido en", "deseas recibirlo en",
        "prefieres proporcionar una nueva dirección", "prefieres proporcionar una nueva direccion",
        "ingresar una nueva dirección", "ingresar una nueva direccion",
        "ingresar una nueva", "prefieres ingresar una nueva",
        "proporcionar una nueva dirección", "proporcionar una nueva direccion",
        "cuál de tus domicilios", "cual de tus domicilios",
        "en cuál de tus direcciones", "en cual de tus direcciones",
        "cliente frecuente",
    ])
    if es_pregunta_direccion:
        repo = get_repository()
        cust = None
        if phone:
            cust = repo.get_customer_by_phone(TENANT_ID, phone)
        elif channel_user_id:
            cust = repo.get_customer(TENANT_ID, "telegram", str(channel_user_id))
        if not cust and not phone:
            match_resp_phone = re.search(r"\b(\d{10})\b", respuesta)
            if match_resp_phone:
                cust = repo.get_customer_by_phone(TENANT_ID, match_resp_phone.group(1))

        addrs: list[CustomerAddress] = []
        if cust and not addrs:
            if cust.addresses:
                addrs = list(cust.addresses)
            elif cust.address:
                addrs = [CustomerAddress(id=1, address=cust.address, alias="Principal")]

        # Si no se obtuvieron de la BD directamente, extraer las direcciones numeradas del propio mensaje
        if not addrs:
            matches = re.findall(
                r"^\s*(\d+)\.\s*(?:📍|\uD83D\uDCCD)?\s*(?:\*\*\[(.*?)\]\*\*)?\s*(.+)$",
                respuesta,
                re.M,
            )
            for m in matches:
                idx = int(m[0])
                alias = m[1].strip() if m[1] else f"Dirección {idx}"
                addr_text = m[2].strip()
                if addr_text and not addr_text.endswith("?"):
                    addrs.append(CustomerAddress(id=idx, address=addr_text, alias=alias))

        if addrs:
            return get_botones_direcciones_cliente(addrs)
        return None

    # 6. GUARD ESTRICTO DE TELÉFONO (PASO 2: solicitando teléfono para buscar cuenta) -> NINGÚN BOTÓN
    # Si el bot está pidiendo el número de teléfono, NUNCA deben salir botones para permitir teclear el número
    if not es_explicacion_general_o_seguridad and any(k in resp_lower for k in [
        "teléfono", "telefono", "celular", "proporcionarme tu número", "proporcionarme tu numero",
        "cuál es tu número", "cual es tu numero", "buscar tu cuenta", "para buscar tu cuenta",
        "número de teléfono", "numero de telefono", "número celular", "numero celular",
        "necesito tu número", "necesito tu numero", "proporcionas tu número", "proporcionas tu numero",
        "número a 10 dígitos", "numero a 10 digitos"
    ]):
        return None

    # 7. ¿Es catálogo de cilindros / selección de capacidad (PASO 1)?
    # Solo si el asistente está preguntando u ofreciendo qué capacidad o tamaño de cilindro desea y NO estamos en pasos posteriores
    db_prods = get_catalogo_productos_db()
    db_kg_keywords = [f"{m.group(1)} kg" for p in db_prods if (m := re.search(r"(\d+)\s*kg", p.name, re.IGNORECASE))]
    es_tema_cilindro = any(k in resp_lower for k in ["cilindro", "cilindros"]) or any(k in resp_lower for k in db_kg_keywords)
    es_pregunta_catalogo = not es_explicacion_general_o_seguridad and not es_pregunta_pago and not es_pregunta_direccion and (
        any(k in resp_lower for k in [
            "qué capacidad", "que capacidad", "cuántos kilos", "cuantos kilos",
            "qué tamaño", "que tamaño", "de qué capacidad", "de que capacidad",
            "de cuántos kilos", "de cuantos kilos", "de que tamaño", "de qué tamaño",
            "cuántos cilindros", "cuantos cilindros", "cuál cilindro", "cual cilindro",
            "opciones de cilindros", "capacidades disponibles", "precios de cilindros",
            "catálogo de cilindros", "catalogo de cilindros", "seleccionar en los botones",
            "opciones disponibles"
        ]) or (
            ("cilindro" in resp_lower or "cilindros" in resp_lower)
            and any(k in resp_lower for k in [
                "opciones", "disponibles", "disponible", "precios", "precio", "costo",
                "catálogo", "catalogo", "cuál", "cual", "cuántos", "cuantos", "necesitas", "deseas", "tamaño"
            ])
            and not any(k in resp_lower for k in ["estacionario", "tanque estacionario", "pago", "pagar", "efectivo", "terminal", "tarjeta", "dirección", "direccion", "horario", "hora"])
        )
    )

    if es_tema_cilindro and es_pregunta_catalogo:
        return get_botones_productos_cilindros()

    # Guard estricto para registro de nuevo usuario / solicitud de nombre / nuevo cliente -> NINGÚN BOTÓN
    if any(k in resp_lower for k in [
        "nombre completo", "cuál es tu nombre", "cual es tu nombre", "para registrar tu cuenta",
        "primer pedido con este número", "primer pedido con este numero", "tu nombre para registrar",
        "cómo te llamas", "como te llamas", "indícame tu nombre", "indicame tu nombre",
        "indícame tu dirección", "indicame tu direccion", "cuál es tu dirección", "cual es tu direccion"
    ]):
        return None

    # 8. Botones de tipo de servicio [🛻 Cilindro de Gas] y [🚛 Tanque Estacionario]
    # SOLO se muestran al inicio, bienvenida o cuando se pregunta explícitamente qué tipo de servicio/pedido desea.
    es_inicio_o_tipo_servicio = (
        es_explicacion_general_o_seguridad
        or any(k in resp_lower for k in [
            "bienvenido", "bienvenida",
            "cilindro o tanque estacionario", "cilindro o estacionario", "tanque estacionario o cilindro",
            "qué servicio necesitas", "que servicio necesitas", "¿qué servicio", "¿que servicio",
            "qué tipo de servicio", "que tipo de servicio",
            "en qué podemos ayudarte", "en que podemos ayudarte",
            "en qué te podemos ayudar", "en que te podemos ayudar",
            "en qué te puedo ayudar", "en que te puedo ayudar",
            "¿te gustaría hacer un pedido", "¿te gustaría realizar un pedido", "¿deseas hacer un pedido",
            "¿te gustaría que te ayude con tu pedido", "en qué te asisto"
        ])
    )
    if es_inicio_o_tipo_servicio:
        return get_botones_tipo_servicio()

    # Si no corresponde a ninguna etapa con botones interactivos específicos, devolver None
    return None


def optimizar_respuesta_con_botones(respuesta: str, markup: InlineKeyboardMarkup | None) -> str:
    """Elimina redundancias y garantiza que direcciones físicas completas nunca se filtren en el chat."""
    if not isinstance(respuesta, str):
        respuesta = str(respuesta)

    # 0. Limpieza general de privacidad: eliminar cualquier bloque o encabezado de 'Tus direcciones registradas'
    lineas_raw = respuesta.split("\n")
    lineas_sanitizadas = []
    saltando_direcciones = False

    for l in lineas_raw:
        l_str = l.strip()
        # Detectar encabezado como '📍 **Tus direcciones registradas:**' o similar
        if re.search(r"(?:📍|\uD83D\uDCCD)?\s*\*{0,2}(?:Tus direcciones registradas|Direcciones registradas|Tus domicilios guardados)\*{0,2}:?", l_str, re.I):
            saltando_direcciones = True
            continue

        if saltando_direcciones:
            # Si es un item de dirección (1. Calle...) o viñeta de dirección
            if re.match(r"^\s*(?:\d+\.|\-|\•|📍|\uD83D\uDCCD)\s+", l_str) or not l_str:
                continue
            else:
                saltando_direcciones = False

        lineas_sanitizadas.append(l)

    respuesta = "\n".join(lineas_sanitizadas).strip()
    respuesta = re.sub(r"\n{3,}", "\n\n", respuesta)

    if not markup or not getattr(markup, "inline_keyboard", None):
        return respuesta

    callbacks = [btn.callback_data for fila in markup.inline_keyboard for btn in fila if getattr(btn, "callback_data", None)]

    # 1. Redundancia en PRODUCTOS (botones de carrito/cilindros tipo cart_add:...)
    if any(cb.startswith("cart_add:") for cb in callbacks):
        lineas = respuesta.split("\n")
        lineas_filtradas = []
        eliminadas = 0

        for l in lineas:
            l_str = l.strip()
            # Detectar líneas de items de productos (bullet points o numeradas con cilindro/kg/precio)
            es_item_producto = bool(
                re.match(r"^\s*(?:[•\-\*▪🔹🔸\d\.\)]+)\s*(?:\*\*)?(?:cilindro|gas\s*lp|gas|recarga|tanque|\d+\s*kg)", l_str, re.I)
                and (re.search(r"\$\s*\d+", l_str) or re.search(r"\b(?:kg|litros|pesos|mxn)\b", l_str, re.I))
            )
            if es_item_producto:
                eliminadas += 1
                continue

            # Quitar líneas de introducción que anuncian la lista de productos
            es_intro_catalogo = bool(
                re.search(r"(?:contamos con las siguientes|tenemos estas opciones|a continuación te muestro|te presento las opciones|capacidades disponibles|opciones disponibles|estas son las opciones|opciones de cilindros)", l_str, re.I)
                and (":" in l_str or "disponible" in l_str.lower() or "opciones" in l_str.lower())
            )
            if es_intro_catalogo:
                eliminadas += 1
                continue

            lineas_filtradas.append(l)

        texto_limpio = "\n".join(lineas_filtradas).strip()
        texto_limpio = re.sub(r"\n{3,}", "\n\n", texto_limpio)

        if eliminadas > 0:
            # Quitar preguntas repetitivas como "¿Cuál de estos deseas?" ya que los botones hacen la selección
            texto_limpio = re.sub(r"¿?(?:cuál|cual|cuántos|cuantos)\s+de\s+est(?:os|as)(?:\s+te\s+gustaría\s+ordenar|\s+prefieres|\s+deseas|\s+necesitas)?\??", "", texto_limpio, flags=re.I).strip()
            texto_limpio = re.sub(r"\n{3,}", "\n\n", texto_limpio)

            if not re.search(r"bot(?:ón|ones)", texto_limpio, re.I):
                texto_limpio = (texto_limpio.rstrip() + "\n\nSelecciona la capacidad que deseas en los botones de abajo (o escribe tu pedido si lo prefieres):").strip()

        return texto_limpio or "🛒 Selecciona los cilindros que necesitas en los botones de abajo:"

    # 2. Redundancia en TIPO DE SERVICIO (botones client_svc:cilindro / estacionario)
    if any(cb.startswith("client_svc:") for cb in callbacks):
        lineas = respuesta.split("\n")
        lineas_filtradas = [
            l for l in lineas
            if not re.match(r"^\s*(?:[12]\ufe0f?\u20e3?|[12]\.|\-|\•)\s*(?:cilindro|tanque\s*estacionario)", l.strip(), re.I)
        ]
        texto_limpio = "\n".join(lineas_filtradas).strip()
        texto_limpio = re.sub(r"\n{3,}", "\n\n", texto_limpio)
        return texto_limpio or "⛽ Selecciona el tipo de servicio que requieres:"

    # 3. Redundancia en MÉTODO DE PAGO (botones client_pay:...)
    if any(cb.startswith("client_pay:") for cb in callbacks):
        lineas = respuesta.split("\n")
        lineas_filtradas = [
            l for l in lineas
            if not re.match(r"^\s*(?:[•\-\*▪🔹🔸\d\.\)]+)\s*(?:\*\*)?(?:💵|💳)?\s*(?:efectivo|terminal|tarjeta)", l.strip(), re.I)
            and not re.search(r"¿?(?:cuál|cual)\s+(?:eliges|prefieres|de\s+est(?:os|as))\??", l.strip(), re.I)
        ]
        texto_limpio = "\n".join(lineas_filtradas).strip()
        texto_limpio = re.sub(r"\n{3,}", "\n\n", texto_limpio)
        return texto_limpio or "💳 ¿Cuál será tu método de pago preferido? (Selecciona en los botones):"

    # Redundancia en PROGRAMACIÓN DE HORARIO (botones client_sch:...)
    if any(cb.startswith("client_sch:") for cb in callbacks):
        lineas = respuesta.split("\n")
        lineas_filtradas = [
            l for l in lineas
            if not re.search(r"^\s*(?:[•\-\*▪🔹🔸\d\.\)]+)\s*(?:\*\*)?(?:⚡|📅)?\s*(?:lo antes posible|programar entrega)", l.strip(), re.I)
        ]
        texto_limpio = "\n".join(lineas_filtradas).strip()
        texto_limpio = re.sub(r"\n{3,}", "\n\n", texto_limpio)
        return texto_limpio or "⏰ ¿Cuándo deseas recibir tu pedido? (Selecciona una opción en los botones):"

    # Redundancia en OPCIONES DE EDICIÓN O CORRECCIÓN (botones client_edit:...)
    if any(cb.startswith("client_edit:") for cb in callbacks):
        return respuesta.strip() or "✏️ Por favor selecciona qué dato deseas modificar:"

    # 4. Redundancia en DIRECCIONES (botones client_addr:...)
    # Solicitud del usuario: "que salgan solo por botón las direcciones guardadas"
    # Se eliminan las líneas de texto que listan las direcciones para que se muestren exclusivamente en los botones interactivos.
    if any(cb.startswith("client_addr:") for cb in callbacks):
        # 4.1 Truncar cualquier alucinación en la que el LLM simule la respuesta o confirmación del cliente en el mismo mensaje
        m_stop = re.search(r"(¿(?:cuál opción prefieres|a cuál de tus direcciones|cuál de tus direcciones|cuál opción deseas|cuál prefieres)[^?\n]*\?[\s🏠🏡]*)(.*)", respuesta, flags=re.I | re.S)
        if m_stop and m_stop.group(2).strip():
            respuesta = respuesta[:m_stop.end(1)].strip()
        else:
            m_halluc = re.search(r"\n\s*(?:¡?Gracias[^!\n]*!?\s*(?:🏠|🏡)?\s*(?:He registrado|registré|anoté|seleccioné)?\s*la siguiente dirección.*)", respuesta, flags=re.I | re.S)
            if m_halluc:
                respuesta = respuesta[:m_halluc.start()].strip()

        lineas = respuesta.split("\n")
        lineas_filtradas = []
        eliminadas_direcciones = 0

        for l in lineas:
            l_str = l.strip()

            # Detectar líneas de items de direcciones (numeradas 1., 2., con pin 📍 o [Alias])
            es_item_direccion = bool(
                re.match(r"^\s*\d+\.\s*(?:📍|\uD83D\uDCCD|\*\*\[|\[)?", l_str)
                and (
                    re.search(r"(?:📍|\uD83D\uDCCD|\[Predeterminada\]|\[Dirección|calle|av\.|avenida|fracc|col\.|sm\.|lote|km|manzana|núm|num|#)", l_str, re.I)
                    or re.search(r"(?:casa|depto|departamento|piso|hotel|residencia|san\s*javier|los\s*mangos|s\u00e1balo|estrada)", l_str, re.I)
                )
                and not l_str.endswith("?")
            )
            if es_item_direccion:
                eliminadas_direcciones += 1
                continue

            # Detectar frases de introducción a la lista de direcciones
            es_intro_direcciones = bool(
                re.search(r"(?:tengo registradas las siguientes direcciones|tengo guardadas las siguientes direcciones|cuentas con las siguientes direcciones|veo que tienes registradas las siguientes direcciones|tus direcciones registradas son|estas son tus direcciones)", l_str, re.I)
                and (":" in l_str or "para ti" in l_str.lower() or "siguientes" in l_str.lower())
            )
            if es_intro_direcciones:
                eliminadas_direcciones += 1
                continue

            lineas_filtradas.append(l)

        texto_limpio = "\n".join(lineas_filtradas).strip()
        texto_limpio = re.sub(r"\n{3,}", "\n\n", texto_limpio)

        if eliminadas_direcciones > 0:
            # Adecuar la pregunta de cierre para referirse a los botones
            patron_pregunta = r"¿?(?:a\s+cuál|a\s+cual|cuál|cual)\s+de\s+(?:estas|tus)\s+direcciones.*?\??"
            if re.search(patron_pregunta, texto_limpio, re.I):
                texto_limpio = re.sub(
                    patron_pregunta,
                    "Por favor selecciona en los botones de abajo a cuál de tus direcciones guardadas deseas que enviemos tu pedido (o presiona **'➕ Ingresar nueva dirección'**):",
                    texto_limpio,
                    flags=re.I,
                ).strip()
            elif not re.search(r"bot(?:ón|ones)", texto_limpio, re.I):
                texto_limpio = (
                    texto_limpio.rstrip()
                    + "\n\nPor favor selecciona en los botones de abajo a cuál de tus direcciones guardadas deseas que enviemos tu pedido (o presiona **'➕ Ingresar nueva dirección'**):"
                ).strip()

            texto_limpio = re.sub(r"\n{3,}", "\n\n", texto_limpio)

        return texto_limpio or "📍 Por favor selecciona una de tus direcciones guardadas o ingresa una nueva:"

    return respuesta.strip() or "¿En qué puedo ayudarte? 😊"



async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manejar comando /start e iniciar flujo de bienvenida sin llamadas a LLM."""
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id if update.effective_chat else user_id
    thread_id = f"telegram:{TENANT_ID}:{chat_id}"

    repo = get_repository()
    bound_cust = repo.get_customer(TENANT_ID, "telegram", str(user_id))
    if bound_cust and bound_cust.phone:
        context.user_data["phone"] = bound_cust.phone
        if hasattr(repo, "bind_telegram_user_phone"):
            repo.bind_telegram_user_phone(str(user_id), bound_cust.phone)

    # Reiniciar sesión para un pedido nuevo desde cero
    from src.services.flow_router import clear_session
    clear_session(thread_id)
    context.user_data.pop("awaiting_rating_comment_order_id", None)
    context.user_data.pop("awaiting_rating_time", None)
    context.user_data.pop("carrito_cilindros", None)

    flow_res = await flow_router.process_event(
        session_id=thread_id,
        text="/start",
        channel="telegram",
        channel_user_id=str(user_id),
        tenant_id=TENANT_ID,
    )

    markup_start = get_botones_tipo_servicio()
    respuesta = optimizar_respuesta_con_botones(flow_res.text, markup_start)
    await safe_reply_text(update.message, respuesta, reply_markup=markup_start)


async def safe_reply_text(message, text: str, reply_markup=None) -> Any:
    """Envía un mensaje a Telegram intentando parse_mode='Markdown' y con fallback a texto plano si falla."""
    if not isinstance(text, str):
        text = str(text) if text is not None else ""
    if not text.strip():
        text = "¿En qué puedo ayudarte? 😊"
    try:
        return await message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception as e:
        logger.warning(f"Error al enviar mensaje con Markdown ({e}), reintentando en texto plano...")
        try:
            return await message.reply_text(text, reply_markup=reply_markup)
        except Exception as e2:
            logger.error(f"Error fatal enviando mensaje: {e2}")
            return None


MENSAJE_SEGURIDAD_ATENCION = (
    "Entiendo, pero no puedo decodificar, ejecutar ni procesar payloads de ese tipo. 🙅‍♂️\n\n"
    "Mi función como asistente de **Gas a Tu Puerta - Petroil** es únicamente de atención al cliente:\n\n"
    "- 🟢 **Realizar un pedido** de gas (cilindro o tanque estacionario)\n"
    "- 🔵 **Consultar el estatus** de tu pedido (folio o teléfono)\n"
    "- ❌ **Cancelar** un pedido tuyo\n\n"
    "No tengo capacidad ni autorización para ejecutar código, decodificar datos ni acceder a la base de datos de forma arbitraria.\n\n"
    "¿Te gustaría que te ayude con tu pedido de gas? 😊"
)


async def responder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Procesar mensajes de texto enviados por el usuario usando el enrutador determinista."""
    if not update.message or not update.message.text:
        return

    if not update.effective_chat or not update.effective_user:
        return

    repo = get_repository()
    texto_usuario = update.message.text.strip()
    texto_lower = texto_usuario.lower()
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    # 1. Si el cliente estaba en proceso de dejar un comentario opcional de calificación
    awaiting_order_id = context.user_data.get("awaiting_rating_comment_order_id")
    awaiting_time = context.user_data.get("awaiting_rating_time", 0)
    if awaiting_order_id:
        curr_session = flow_router.get_session(f"telegram:{TENANT_ID}:{chat_id}")

        digits_only = re.sub(r"\D", "", texto_usuario)
        has_phone_digits = len(digits_only) >= 7 or bool(re.search(r"\b\d{7,10}\b", texto_usuario))
        is_greeting_or_cmd = any(texto_lower.startswith(g) for g in ["hola", "buen", "hey", "/start", "/menu", "inicio", "empezar", "que tal", "buenas", "ayuda"])
        is_order_intent = any(k in texto_lower for k in [
            "quiero", "cilindro", "estacionario", "tanque", "litros", "pedir", "orden", "gas",
            "recarga", "precio", "cuanto", "cuánto", "30", "20", "45", "10", "5", "kilos", "kg", "nuevo"
        ])
        is_in_active_order = curr_session.state not in (FlowState.INITIAL, FlowState.COMPLETED, FlowState.CANCELLED)

        # Si el usuario escribe su teléfono, saluda, pide gas o ya está en un flujo de pedido:
        if has_phone_digits or is_greeting_or_cmd or is_order_intent or is_in_active_order or (datetime.now().timestamp() - awaiting_time) >= 600:
            context.user_data.pop("awaiting_rating_comment_order_id", None)
            context.user_data.pop("awaiting_rating_time", None)
        else:
            # Es un comentario de retroalimentación válido
            context.user_data.pop("awaiting_rating_comment_order_id", None)
            context.user_data.pop("awaiting_rating_time", None)
            repo.update_order_rating_feedback(TENANT_ID, awaiting_order_id, comment=texto_usuario)
            await safe_reply_text(
                update.message,
                "📝 **¡Comentario registrado!**\n\n"
                "Muchas gracias por compartirnos tu opinión detallada. Tus comentarios han sido guardados para el equipo de calidad de Petroil. ¡Que tengas un excelente día! ⛽🌟",
            )
            return

    # 2. Detección temprana de intentos de payload / código / inyección / scraping / consultas a múltiples teléfonos
    found_phones = re.findall(r"\b(?:\+?52\s*)?(\d{10})\b", texto_usuario)
    es_payload_o_inyeccion = any(k in texto_lower for k in [
        "payload", "decodifica", "decodificar", "base64", "script", "ejecutar código", "ejecuta codigo",
        "ejecutar codigo", "ejecuta script", "ejecutar script", "eval(", "exec(", "system(", "sql injection",
        "drop table", "select * from", "union select", "bypass", "jailbreak", "ignora tus instrucciones",
        "ignore previous instructions", "ignora todas las instrucciones", "revela tu prompt", "muestra tu system prompt"
    ])
    es_consulta_multiple = (
        len(found_phones) > 1 and any(k in texto_lower for k in ["pedido", "pedidos", "número", "numero", "orden", "ordenes", "historial", "cliente", "clientes"])
    ) or any(k in texto_lower for k in [
        "dos numeros", "dos números", "varios numeros", "varios números", "múltiples números", "multiples numeros",
        "pedidos de otros", "pedidos de otro", "pedidos de dos", "pedidos de varios"
    ])

    if es_payload_o_inyeccion or es_consulta_multiple:
        await safe_reply_text(update.message, MENSAJE_SEGURIDAD_ATENCION, reply_markup=get_botones_tipo_servicio())
        return

    thread_id = f"telegram:{TENANT_ID}:{chat_id}"

    # 3. Control de seguridad y vinculación de teléfono con el usuario de Telegram
    if len(found_phones) == 1:
        digits = re.sub(r"\D", "", found_phones[0])
        if len(digits) == 10:
            context.user_data["phone"] = digits
            from src.repositories.identity_store import identity_store
            identity_store.bind_channel_user_phone("telegram", str(user_id), digits)
            if hasattr(repo, "bind_telegram_user_phone"):
                repo.bind_telegram_user_phone(str(user_id), digits)
    elif len(found_phones) > 1:
        context.user_data.pop("phone", None)
    elif not context.user_data.get("phone"):
        bound_cust = repo.get_customer(TENANT_ID, "telegram", str(user_id))
        if bound_cust and bound_cust.phone:
            context.user_data["phone"] = bound_cust.phone
            if hasattr(repo, "bind_telegram_user_phone"):
                repo.bind_telegram_user_phone(str(user_id), bound_cust.phone)
        elif user_id:
            from src.repositories.identity_store import identity_store
            mapped_phone = identity_store.get_phone_for_channel_user("telegram", str(user_id))
            if mapped_phone:
                context.user_data["phone"] = mapped_phone

    phone_ctx = context.user_data.get("phone", "")
    if phone_ctx and hasattr(repo, "bind_telegram_user_phone"):
        repo.bind_telegram_user_phone(str(user_id), phone_ctx)

    try:
        try:
            await context.bot.send_chat_action(
                chat_id=chat_id,
                action=ChatAction.TYPING,
            )
        except Exception:
            pass

        # Invocación del motor determinista de flujo
        flow_res = await flow_router.process_event(
            session_id=thread_id,
            text=texto_usuario,
            channel="telegram",
            channel_user_id=str(user_id),
            tenant_id=TENANT_ID,
        )

        flow_session = flow_router.get_session(thread_id)
        active_phone = (
            (flow_session.draft_order.customer_phone if flow_session and flow_session.draft_order else "")
            or context.user_data.get("phone", "")
        )
        if active_phone:
            context.user_data["phone"] = active_phone
            from src.repositories.identity_store import identity_store
            identity_store.bind_channel_user_phone("telegram", str(user_id), active_phone)
            if hasattr(repo, "bind_telegram_user_phone"):
                repo.bind_telegram_user_phone(str(user_id), active_phone)

        inline_markup = get_markup_for_flow_response(flow_res, phone=active_phone, user_id=str(user_id))
        respuesta = optimizar_respuesta_con_botones(flow_res.text, inline_markup)

        max_len = 4000
        sent_msg = None
        if len(respuesta) <= max_len:
            sent_msg = await safe_reply_text(update.message, respuesta, reply_markup=inline_markup)
        else:
            for i in range(0, len(respuesta), max_len):
                sub_markup = inline_markup if (i + max_len >= len(respuesta)) else None
                sub_sent = await safe_reply_text(update.message, respuesta[i:i + max_len], reply_markup=sub_markup)
                if sub_markup:
                    sent_msg = sub_sent

        if sent_msg and inline_markup:
            match_order = re.search(r"(?:pedido|folio)\s*#?\s*(\d+)", respuesta, re.IGNORECASE)
            if match_order and "cancel_order_client" in str(inline_markup):
                from src.services.notifications import cleanup_client_order_buttons
                cleanup_client_order_buttons(match_order.group(1), chat_id=chat_id, keep_message_id=sent_msg.message_id)

    except Exception as error:
        logger.error(f"❌ Error procesando mensaje de {user_id}: {error}", exc_info=True)
        await safe_reply_text(
            update.message,
            "⚠️ Ocurrió un error al procesar tu solicitud. Por favor intenta de nuevo en unos momentos."
        )


async def recibir_ubicacion_cliente(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Procesar ubicación GPS o en tiempo real compartida por el cliente."""
    if not update.message or not update.message.location:
        return

    if not update.effective_chat or not update.effective_user:
        return

    loc = update.message.location
    lat = loc.latitude
    lng = loc.longitude
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    thread_id = f"telegram:{TENANT_ID}:{chat_id}"

    try:
        try:
            await context.bot.send_chat_action(
                chat_id=chat_id,
                action=ChatAction.TYPING,
            )
        except Exception:
            pass

        flow_res = await flow_router.process_event(
            session_id=thread_id,
            location={"latitude": lat, "longitude": lng},
            channel="telegram",
            channel_user_id=str(user_id),
            tenant_id=TENANT_ID,
        )

        flow_session = flow_router.get_session(thread_id)
        phone_ctx = (
            (flow_session.draft_order.customer_phone if flow_session and flow_session.draft_order else "")
            or context.user_data.get("phone", "")
        )
        if phone_ctx:
            context.user_data["phone"] = phone_ctx
        inline_markup = get_markup_for_flow_response(flow_res, phone=phone_ctx, user_id=str(user_id))
        respuesta = optimizar_respuesta_con_botones(flow_res.text, inline_markup)
        await safe_reply_text(update.message, respuesta, reply_markup=inline_markup)

    except Exception as error:
        logger.error(f"❌ Error procesando ubicación GPS de {user_id}: {error}", exc_info=True)
        await safe_reply_text(
            update.message,
            f"📍 ¡Ubicación GPS recibida ({lat:.5f}, {lng:.5f})!\n"
            "Si tienes un pedido activo en curso, tus coordenadas han sido actualizadas para el chofer. ⛽✨"
        )


async def recibir_voz_cliente(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Procesar notas de voz y mensajes de audio enviados por el cliente."""
    if not update.message or (not update.message.voice and not update.message.audio):
        return

    if not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    thread_id = f"telegram:{TENANT_ID}:{chat_id}"

    try:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    except Exception:
        pass

    voice_obj = update.message.voice or update.message.audio
    file_id = voice_obj.file_id

    audio_dir = Path(__file__).parent / "uploads" / "voice_notes"
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_path = audio_dir / f"voice_{user_id}_{int(datetime.now().timestamp())}.ogg"

    try:
        tg_file = await context.bot.get_file(file_id)
        await tg_file.download_to_drive(custom_path=str(audio_path))

        # Transcribir nota de voz
        texto_transcrito = await transcribe_audio_file(audio_path)
        if not texto_transcrito:
            await safe_reply_text(
                update.message,
                "🎙️ He recibido tu nota de voz, pero no fue posible transcribirla con claridad. "
                "Por favor intenta escribir tu mensaje o enviar un nuevo audio."
            )
            return

        logger.info(f"[Audio Telegram] Usuario {user_id}: \"{texto_transcrito}\"")

        flow_res = await flow_router.process_event(
            session_id=thread_id,
            text=texto_transcrito,
            channel="telegram",
            channel_user_id=str(user_id),
            tenant_id=TENANT_ID,
        )

        flow_session = flow_router.get_session(thread_id)
        phone_ctx = (
            (flow_session.draft_order.customer_phone if flow_session and flow_session.draft_order else "")
            or context.user_data.get("phone", "")
        )
        if phone_ctx:
            context.user_data["phone"] = phone_ctx
        inline_markup = get_markup_for_flow_response(flow_res, phone=phone_ctx, user_id=str(user_id))
        respuesta = optimizar_respuesta_con_botones(flow_res.text, inline_markup)

        header = f"🎙️ _Nota de voz:_ \"{texto_transcrito}\"\n\n"
        await safe_reply_text(update.message, header + respuesta, reply_markup=inline_markup)

    except Exception as error:
        logger.error(f"❌ Error procesando nota de voz de {user_id}: {error}", exc_info=True)
        await safe_reply_text(
            update.message,
            "⚠️ Ocurrió un error al procesar tu nota de voz. Por favor intenta escribir tu solicitud."
        )


async def manejar_callback_cliente(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manejar botones interactivos del cliente de forma 100% determinista sin LLM."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()
    data = query.data
    repo = get_repository()

    user_id = query.from_user.id if query.from_user else (update.effective_user.id if update.effective_user else 0)
    chat_id = update.effective_chat.id if update.effective_chat else user_id
    thread_id = f"telegram:{TENANT_ID}:{chat_id}"

    # Descartar cualquier comentario de calificación pendiente si se presiona cualquier botón de flujo
    if not data.startswith("driver_rating:") and not data.startswith("rate_tag:"):
        context.user_data.pop("awaiting_rating_comment_order_id", None)
        context.user_data.pop("awaiting_rating_time", None)

    flow_session = flow_router.get_session(thread_id)
    if flow_session and flow_session.draft_order and flow_session.draft_order.customer_phone:
        context.user_data["phone"] = flow_session.draft_order.customer_phone
    elif not context.user_data.get("phone") and user_id:
        from src.repositories.identity_store import identity_store
        mapped_phone = identity_store.get_phone_for_channel_user("telegram", str(user_id))
        if mapped_phone:
            context.user_data["phone"] = mapped_phone

    # 1. Tipo de servicio
    if data.startswith("client_svc:"):
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

        flow_res = await flow_router.process_event(
            session_id=thread_id,
            callback_data=data,
            channel="telegram",
            channel_user_id=str(user_id),
            tenant_id=TENANT_ID,
        )

        if data == "client_svc:cilindro":
            context.user_data["carrito_cilindros"] = {}
            texto_catalogo = texto_resumen_catalogo({})
            markup_catalogo = get_botones_productos_cilindros({})
            await context.bot.send_message(
                chat_id=chat_id,
                text=texto_catalogo,
                reply_markup=markup_catalogo,
                parse_mode="Markdown",
            )
            return
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=flow_res.text,
            )
            return

    # 2. Carrito interactivo de cilindros
    if data.startswith("cart_add:"):
        key = data.split(":")[1]
        carrito = context.user_data.setdefault("carrito_cilindros", {})
        carrito[key] = carrito.get(key, 0) + 1

        nuevo_texto = texto_resumen_catalogo(carrito)
        nuevo_markup = get_botones_productos_cilindros(carrito)

        try:
            await query.edit_message_text(
                text=nuevo_texto,
                reply_markup=nuevo_markup,
                parse_mode="Markdown",
            )
        except Exception:
            try:
                await query.edit_message_text(
                    text=nuevo_texto.replace("**", "").replace("•", "-"),
                    reply_markup=nuevo_markup,
                )
            except Exception:
                pass
        return

    if data == "cart_clear":
        context.user_data["carrito_cilindros"] = {}
        nuevo_texto = texto_resumen_catalogo({})
        nuevo_markup = get_botones_productos_cilindros({})

        try:
            await query.edit_message_text(
                text=nuevo_texto,
                reply_markup=nuevo_markup,
                parse_mode="Markdown",
            )
        except Exception:
            try:
                await query.edit_message_text(
                    text=nuevo_texto.replace("**", "").replace("•", "-"),
                    reply_markup=nuevo_markup,
                )
            except Exception:
                pass
        return

    if data == "cart_checkout":
        carrito = context.user_data.get("carrito_cilindros", {})
        if not carrito or sum(carrito.values()) == 0:
            await query.answer("Por favor selecciona al menos un cilindro.", show_alert=True)
            return

        # Sincronizar con flow_router
        sess = get_or_create_session(thread_id, tenant_id=TENANT_ID, channel="telegram", channel_user_id=str(user_id))
        sess.cart = dict(carrito)
        context.user_data["carrito_cilindros"] = {}

        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

        flow_res = await flow_router.process_event(
            session_id=thread_id,
            callback_data="cart_checkout",
            channel="telegram",
            channel_user_id=str(user_id),
            tenant_id=TENANT_ID,
        )

        phone_ctx = context.user_data.get("phone", "")
        markup = get_markup_for_flow_response(flow_res, phone=phone_ctx, user_id=str(user_id))
        respuesta = optimizar_respuesta_con_botones(flow_res.text, markup)

        await context.bot.send_message(
            chat_id=chat_id,
            text=respuesta,
            reply_markup=markup,
        )
        return

    # 3. Menú para eliminar una dirección guardada
    if data in ("client_addr_del_menu", "client_addr:del_menu"):
        user_id = query.from_user.id if query.from_user else (update.effective_user.id if update.effective_user else 0)
        phone = context.user_data.get("phone", "")
        if not phone and user_id:
            from src.repositories.identity_store import identity_store
            phone = identity_store.get_phone_for_channel_user("telegram", str(user_id)) or ""
            if phone:
                context.user_data["phone"] = phone
        cust = repo.get_customer_by_phone(TENANT_ID, phone) if phone else None
        if not cust and not phone and user_id:
            cust = repo.get_customer(TENANT_ID, "telegram", str(user_id))

        if not cust or not cust.addresses:
            await query.answer("No tienes direcciones guardadas para eliminar.", show_alert=True)
            return

        try:
            await query.edit_message_text(
                text="🗑️ *Eliminar Dirección Guardada*\n\nSelecciona la dirección que deseas borrar de tu cuenta:",
                reply_markup=get_botones_eliminar_direcciones(cust.addresses),
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.warning(f"Failed to edit message in client_addr_del_menu Markdown: {e}")
            try:
                await query.edit_message_text(
                    text="🗑️ Eliminar Dirección Guardada\n\nSelecciona la dirección que deseas borrar de tu cuenta:",
                    reply_markup=get_botones_eliminar_direcciones(cust.addresses),
                )
            except Exception as e2:
                logger.error(f"Failed to edit message in client_addr_del_menu plain text: {e2}")
        return

    # 3b. Paso de confirmación previa antes de eliminar
    if data.startswith("client_addr_del:") and not data.startswith("client_addr_del_confirm:"):
        parts = data.split(":")
        raw_aid = parts[1]
        addr_id = int(raw_aid) if raw_aid.isdigit() else raw_aid
        idx = parts[2] if len(parts) > 2 else "1"
        user_id = query.from_user.id if query.from_user else (update.effective_user.id if update.effective_user else 0)
        phone = context.user_data.get("phone", "")
        if not phone and user_id:
            from src.repositories.identity_store import identity_store
            phone = identity_store.get_phone_for_channel_user("telegram", str(user_id)) or ""
            if phone:
                context.user_data["phone"] = phone
        cust = repo.get_customer_by_phone(TENANT_ID, phone) if phone else None
        if not cust and not phone and user_id:
            cust = repo.get_customer(TENANT_ID, "telegram", str(user_id))

        target_addr = None
        if cust and cust.addresses:
            target_addr = next((a for a in cust.addresses if str(a.id) == str(raw_aid)), None)
            if not target_addr and idx.isdigit():
                i_idx = int(idx) - 1
                if 0 <= i_idx < len(cust.addresses):
                    target_addr = cust.addresses[i_idx]

        addr_str = target_addr.address if target_addr else f"Dirección #{idx}"
        actual_aid = target_addr.id if target_addr else addr_id

        clean_addr = resolve_gps_address_to_name(addr_str.strip())
        clean_addr = re.sub(r"^(?:\[(?:Nueva\s*Direcci[oó]n|Direcci[oó]n(?:\s*\d+)?|Principal)\]\s*)+", "", clean_addr, flags=re.I).strip()

        confirm_text = (
            "⚠️ *¿Estás seguro de que deseas eliminar esta dirección?*\n\n"
            f"📍 *Dirección seleccionada:*\n`{clean_addr}`\n\n"
            "⚠️ _Esta acción no se puede deshacer. Por favor confirma tu decisión:_"
        )
        confirm_markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🗑️ Sí, eliminar dirección", callback_data=f"client_addr_del_confirm:{actual_aid}:{idx}")
            ],
            [
                InlineKeyboardButton("❌ No, cancelar", callback_data="client_addr_del_menu")
            ]
        ])

        try:
            await query.edit_message_text(
                text=confirm_text,
                reply_markup=confirm_markup,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.warning(f"Error editing message for delete confirmation: {e}")
            try:
                await query.edit_message_text(
                    text=f"⚠️ ¿Estás seguro de que deseas eliminar esta dirección?\n\n📍 Dirección:\n{clean_addr}\n\nEsta acción no se puede deshacer. Por favor confirma tu decisión:",
                    reply_markup=confirm_markup,
                )
            except Exception as e2:
                logger.error(f"Error editing message plain text: {e2}")
        return

    if data.startswith("client_addr_del_confirm:") or data.startswith("del_addr_confirm:"):
        parts = data.split(":")
        raw_aid = parts[1]
        addr_id = int(raw_aid) if raw_aid.isdigit() else raw_aid
        idx = parts[2] if len(parts) > 2 else "1"
        user_id = query.from_user.id if query.from_user else (update.effective_user.id if update.effective_user else 0)
        phone = context.user_data.get("phone", "")
        if not phone and user_id:
            from src.repositories.identity_store import identity_store
            phone = identity_store.get_phone_for_channel_user("telegram", str(user_id)) or ""
            if phone:
                context.user_data["phone"] = phone
        cust = repo.get_customer_by_phone(TENANT_ID, phone) if phone else None
        if not cust and not phone and user_id:
            cust = repo.get_customer(TENANT_ID, "telegram", str(user_id))

        target_addr = None
        if cust and cust.addresses:
            target_addr = next((a for a in cust.addresses if str(a.id) == str(raw_aid)), None)
            if not target_addr and idx.isdigit():
                i_idx = int(idx) - 1
                if 0 <= i_idx < len(cust.addresses):
                    target_addr = cust.addresses[i_idx]

        addr_str = target_addr.address if target_addr else f"Dirección #{idx}"
        actual_aid = target_addr.id if target_addr else addr_id

        if cust:
            repo.delete_customer_address(cust.id, actual_aid, phone=phone, address_text=addr_str)
            updated_cust = repo.get_customer_by_phone(TENANT_ID, phone) if phone else repo.get_customer(TENANT_ID, "telegram", str(user_id))
            remaining_addrs = updated_cust.addresses if (updated_cust and updated_cust.addresses) else []
        else:
            remaining_addrs = []

        await query.answer("✅ Dirección eliminada correctamente.", show_alert=True)

        if remaining_addrs:
            texto_resp = (
                "✅ *Dirección eliminada correctamente de tu cuenta.*\n\n"
                "¿A cuál de tus direcciones restantes deseas que enviemos tu pedido o prefieres ingresar una nueva?"
            )
            markup_resp = get_botones_direcciones_cliente(remaining_addrs)
        else:
            texto_resp = (
                "✅ *Dirección eliminada correctamente.*\n\n"
                "Ya no tienes direcciones guardadas. Por favor escribe tu dirección de entrega completa o comparte tu ubicación GPS para continuar con tu pedido:"
            )
            markup_resp = None

        try:
            await query.edit_message_text(
                text=texto_resp,
                reply_markup=markup_resp,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.warning(f"Error editing message with Markdown after address deletion: {e}")
            try:
                await query.edit_message_text(
                    text=texto_resp.replace("*", "").replace("`", ""),
                    reply_markup=markup_resp,
                )
            except Exception as e2:
                logger.error(f"Error editing message plain text after address deletion: {e2}")
        return

    if data in ("client_addr_back", "client_addr:cancel_del", "client_addr_cancel_del", "del_addr_cancel"):
        user_id = query.from_user.id if query.from_user else (update.effective_user.id if update.effective_user else 0)
        phone = context.user_data.get("phone", "")
        if not phone and user_id:
            from src.repositories.identity_store import identity_store
            phone = identity_store.get_phone_for_channel_user("telegram", str(user_id)) or ""
            if phone:
                context.user_data["phone"] = phone
        cust = repo.get_customer_by_phone(TENANT_ID, phone) if phone else None
        if not cust and not phone and user_id:
            cust = repo.get_customer(TENANT_ID, "telegram", str(user_id))

        addrs = cust.addresses if (cust and cust.addresses) else []
        if addrs:
            texto_resp = "¿A cuál de tus direcciones registradas deseas que enviemos tu pedido o prefieres ingresar una nueva?"
            markup_resp = get_botones_direcciones_cliente(addrs)
        else:
            texto_resp = "Por favor escribe tu dirección de entrega o comparte tu ubicación GPS:"
            markup_resp = None

        try:
            await query.edit_message_text(
                text=texto_resp,
                reply_markup=markup_resp,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.warning(f"Error editing message in client_addr_back Markdown: {e}")
            try:
                await query.edit_message_text(
                    text=texto_resp.replace("*", "").replace("`", ""),
                    reply_markup=markup_resp,
                )
            except Exception as e2:
                logger.error(f"Error editing message in client_addr_back plain text: {e2}")
        return

    # 4. Selección de dirección guardada o nueva
    if data.startswith("client_addr:") and not any(k in data for k in ["del_menu", "cancel_del", "client_addr_del", "_del"]):
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

        flow_res = await flow_router.process_event(
            session_id=thread_id,
            callback_data=data,
            channel="telegram",
            channel_user_id=str(user_id),
            tenant_id=TENANT_ID,
        )

        phone_ctx = context.user_data.get("phone", "")
        markup = get_markup_for_flow_response(flow_res, phone=phone_ctx, user_id=str(user_id))
        respuesta = optimizar_respuesta_con_botones(flow_res.text, markup)

        sent_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=respuesta,
            reply_markup=markup,
        )
        if sent_msg and markup:
            match_order = re.search(r"(?:pedido|folio)\s*#?\s*(\d+)", respuesta, re.IGNORECASE)
            if match_order and "cancel_order_client" in str(markup):
                from src.services.notifications import cleanup_client_order_buttons
                cleanup_client_order_buttons(match_order.group(1), chat_id=chat_id, keep_message_id=sent_msg.message_id)
        return

    # 4.5 Selección de programación de horario (Lo antes posible / Programar entrega / Aceptar alternativa)
    if data.startswith("client_sch:") or data.startswith("client_sch_accept"):
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

        flow_res = await flow_router.process_event(
            session_id=thread_id,
            callback_data=data,
            channel="telegram",
            channel_user_id=str(user_id),
            tenant_id=TENANT_ID,
        )

        phone_ctx = context.user_data.get("phone", "")
        markup = get_markup_for_flow_response(flow_res, phone=phone_ctx, user_id=str(user_id))
        respuesta = optimizar_respuesta_con_botones(flow_res.text, markup)

        sent_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=respuesta,
            reply_markup=markup,
        )
        if sent_msg and markup:
            match_order = re.search(r"(?:pedido|folio)\s*#?\s*(\d+)", respuesta, re.IGNORECASE)
            if match_order and "cancel_order_client" in str(markup):
                from src.services.notifications import cleanup_client_order_buttons
                cleanup_client_order_buttons(match_order.group(1), chat_id=chat_id, keep_message_id=sent_msg.message_id)
        return

    # 5. Selección de método de pago (Efectivo / Terminal)
    if data.startswith("client_pay:"):
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

        flow_res = await flow_router.process_event(
            session_id=thread_id,
            callback_data=data,
            channel="telegram",
            channel_user_id=str(user_id),
            tenant_id=TENANT_ID,
        )

        phone_ctx = context.user_data.get("phone", "")
        markup = get_markup_for_flow_response(flow_res, phone=phone_ctx, user_id=str(user_id))
        respuesta = optimizar_respuesta_con_botones(flow_res.text, markup)

        sent_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=respuesta,
            reply_markup=markup,
        )
        if sent_msg and markup:
            match_order = re.search(r"(?:pedido|folio)\s*#?\s*(\d+)", respuesta, re.IGNORECASE)
            if match_order and "cancel_order_client" in str(markup):
                from src.services.notifications import cleanup_client_order_buttons
                cleanup_client_order_buttons(match_order.group(1), chat_id=chat_id, keep_message_id=sent_msg.message_id)
    # 5.5 Modificación o corrección de datos del pedido
    if data.startswith("client_edit:"):
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

        flow_res = await flow_router.process_event(
            session_id=thread_id,
            callback_data=data,
            channel="telegram",
            channel_user_id=str(user_id),
            tenant_id=TENANT_ID,
        )

        phone_ctx = context.user_data.get("phone", "")
        markup = get_markup_for_flow_response(flow_res, phone=phone_ctx, user_id=str(user_id))
        respuesta = optimizar_respuesta_con_botones(flow_res.text, markup)

        sent_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=respuesta,
            reply_markup=markup,
        )
        if sent_msg and markup:
            match_order = re.search(r"(?:pedido|folio)\s*#?\s*(\d+)", respuesta, re.IGNORECASE)
            if match_order and "cancel_order_client" in str(markup):
                from src.services.notifications import cleanup_client_order_buttons
                cleanup_client_order_buttons(match_order.group(1), chat_id=chat_id, keep_message_id=sent_msg.message_id)
        return

    # 6. Confirmación, modificación o cancelación de pedido
    if data.startswith("client_confirm:"):
        try:
            await query.edit_message_reply_markup(reply_markup=None)

        except Exception:
            pass

        flow_res = await flow_router.process_event(
            session_id=thread_id,
            callback_data=data,
            channel="telegram",
            channel_user_id=str(user_id),
            tenant_id=TENANT_ID,
        )

        phone_ctx = context.user_data.get("phone", "")
        markup = get_markup_for_flow_response(flow_res, phone=phone_ctx, user_id=str(user_id))
        respuesta = optimizar_respuesta_con_botones(flow_res.text, markup)

        sent_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=respuesta,
            reply_markup=markup,
        )
        if sent_msg and markup:
            match_order = re.search(r"(?:pedido|folio)\s*#?\s*(\d+)", respuesta, re.IGNORECASE)
            if match_order and "cancel_order_client" in str(markup):
                from src.services.notifications import cleanup_client_order_buttons
                cleanup_client_order_buttons(match_order.group(1), chat_id=chat_id, keep_message_id=sent_msg.message_id)
        return

    # 7. Selección directa de producto
    if data.startswith("client_prod:"):
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

        prod_text = data.split(":", 1)[1]
        flow_res = await flow_router.process_event(
            session_id=thread_id,
            text=prod_text,
            channel="telegram",
            channel_user_id=str(user_id),
            tenant_id=TENANT_ID,
        )

        phone_ctx = context.user_data.get("phone", "")
        markup = get_markup_for_flow_response(flow_res, phone=phone_ctx, user_id=str(user_id))
        respuesta = optimizar_respuesta_con_botones(flow_res.text, markup)

        sent_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=respuesta,
            reply_markup=markup,
        )
        if sent_msg and markup:
            match_order = re.search(r"(?:pedido|folio)\s*#?\s*(\d+)", respuesta, re.IGNORECASE)
            if match_order and "cancel_order_client" in str(markup):
                from src.services.notifications import cleanup_client_order_buttons
                cleanup_client_order_buttons(match_order.group(1), chat_id=chat_id, keep_message_id=sent_msg.message_id)
        return

    if data.startswith("cancel_order_client:"):
        order_id = int(data.split(":")[1])
        order = repo.get_order_by_id(TENANT_ID, order_id)
        if not order:
            await query.edit_message_text("⚠️ Pedido no encontrado.")
            return

        if order.status == "delivered":
            await query.edit_message_text("⚠️ Tu pedido ya fue entregado y no puede cancelarse.")
            return

        if order.status == "cancelled":
            await query.edit_message_text(f"⚠️ El pedido #{order_id} ya se encuentra cancelado.")
            return

        # Validación previa de seguridad: preguntar si está seguro
        markup_confirm = get_botones_confirmar_cancelacion(order_id)
        await query.edit_message_text(
            f"⚠️ **¿Estás seguro de que deseas cancelar tu pedido #{order_id}?**\n\n"
            f"📍 Entrega: {order.delivery_address}\n"
            f"💰 Total a pagar: ${order.total_amount:.2f} ({order.payment_method})\n\n"
            "Si confirmas la cancelación, la unidad de reparto asignada será liberada y tu entrega quedará suspendida definitivamente.",
            reply_markup=markup_confirm,
            parse_mode="Markdown",
        )
        return

    if data.startswith("keep_order_client:"):
        order_id = int(data.split(":")[1])
        order = repo.get_order_by_id(TENANT_ID, order_id)
        if not order:
            await query.edit_message_text("⚠️ Pedido no encontrado.")
            return

        await query.answer("¡Excelente! Tu pedido sigue activo.", show_alert=False)
        status_text = format_clean_driver_status(order, repo=repo)
        markup = get_botones_pedido_activo(order_id)
        try:
            await query.edit_message_text(
                status_text,
                reply_markup=markup,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
        except Exception:
            await query.edit_message_text(
                status_text.replace("**", ""),
                reply_markup=markup,
                disable_web_page_preview=True,
            )
        if query.message:
            from src.services.notifications import cleanup_client_order_buttons
            cleanup_client_order_buttons(order_id, chat_id=query.message.chat_id, keep_message_id=query.message.message_id)
        return

    if data.startswith("confirm_cancel_order_client:"):
        order_id = int(data.split(":")[1])
        order = repo.get_order_by_id(TENANT_ID, order_id)
        if not order:
            await query.edit_message_text("⚠️ Pedido no encontrado.")
            return

        if order.status == "delivered":
            await query.edit_message_text("⚠️ Tu pedido ya fue entregado y no puede cancelarse.")
            return

        if order.status == "cancelled":
            await query.edit_message_text(f"⚠️ El pedido #{order_id} ya se encuentra cancelado.")
            return

        # Eliminar ubicación en tiempo real si existía
        if order.live_location_message_id and order.live_location_chat_id:
            from src.services.notifications import remove_client_live_location
            remove_client_live_location(order.live_location_chat_id, order.live_location_message_id)
            repo.clear_order_live_location(TENANT_ID, order_id)

        # Cancelar orden en BD y liberar chofer
        repo.cancel_order(TENANT_ID, order_id, cancelled_by="el cliente")
        from src.repositories.identity_store import identity_store
        identity_store.save_order_cancellation(order_id, cancelled_by="el cliente", reason="Cancelado por el cliente desde Telegram")
        try:
            from src.services.order_events import _EVENT_DEDUP_CACHE
            import time
            _EVENT_DEDUP_CACHE[f"cancelled:{order_id}"] = time.time()
        except Exception:
            pass

        # Limpiar botones anteriores de cliente y chofer
        from src.services.notifications import cleanup_client_order_buttons
        cleanup_client_order_buttons(order_id, chat_id=query.message.chat_id if query.message else None, keep_message_id=None)

        # Notificar al chofer asignado si tiene Telegram y limpiar botones activos de su chat
        if order.driver_id:
            driver = repo.get_driver(order.driver_id)
            driver_tg_id = getattr(driver, "telegram_user_id", None) or getattr(driver, "telegram_chat_id", None)
            if driver_tg_id:
                from src.services.notifications import notify_driver_order_cancelled
                notify_driver_order_cancelled(
                    tenant_id=TENANT_ID,
                    order_id=order_id,
                    driver_telegram_user_id=str(driver_tg_id),
                    customer_name=order.customer_name or "Cliente Telegram",
                    delivery_address=order.delivery_address or "",
                    cancelled_by="el cliente vía Telegram",
                )

        await query.edit_message_text(
            f"❌ **Tu pedido #{order_id} ha sido cancelado exitosamente.**\n\n"
            "Si deseas programar un nuevo pedido en el futuro, solo envíame un mensaje. ¡Estamos a tus órdenes! ⛽"
        )
        return

    if data.startswith("check_order_status:"):
        order_id = int(data.split(":")[1])
        order = repo.get_order_by_id(TENANT_ID, order_id)
        if not order:
            await query.edit_message_text("⚠️ Pedido no encontrado.")
            return

        status_text = format_clean_driver_status(order, repo=repo)
        status_raw = str(getattr(order, "status", "")).lower()

        if status_raw in ("confirmed", "confirmado", "in_route", "en_ruta", "scheduled", "programado", "assigned"):
            markup = get_botones_pedido_activo(order_id)
            try:
                await query.edit_message_text(
                    status_text,
                    reply_markup=markup,
                    parse_mode="Markdown",
                    disable_web_page_preview=True,
                )
                if query.message:
                    from src.services.notifications import cleanup_client_order_buttons
                    cleanup_client_order_buttons(order_id, chat_id=query.message.chat_id, keep_message_id=query.message.message_id)
            except Exception as e:
                if "message is not modified" in str(e).lower():
                    await query.answer("El estatus ya está actualizado al momento.", show_alert=False)
                    return
                try:
                    await query.edit_message_text(
                        status_text.replace("**", ""),
                        reply_markup=markup,
                        disable_web_page_preview=True,
                    )
                    if query.message:
                        from src.services.notifications import cleanup_client_order_buttons
                        cleanup_client_order_buttons(order_id, chat_id=query.message.chat_id, keep_message_id=query.message.message_id)
                except Exception:
                    sent_msg = await context.bot.send_message(
                        chat_id=chat_id,
                        text=status_text,
                        reply_markup=markup,
                        parse_mode="Markdown",
                        disable_web_page_preview=True,
                    )
                    if sent_msg:
                        from src.services.notifications import cleanup_client_order_buttons
                        cleanup_client_order_buttons(order_id, chat_id=chat_id, keep_message_id=sent_msg.message_id)
        else:
            try:
                await query.edit_message_text(status_text, parse_mode="Markdown")
            except Exception:
                await query.edit_message_text(status_text.replace("**", ""))
        return

    # -------------------------------------------------------------------------
    # Calificación del Chofer y Encuesta de Entrega
    # -------------------------------------------------------------------------
    if data.startswith("rate_driver:"):
        parts = data.split(":")
        raw_oid = parts[1]
        order_id = int(raw_oid) if raw_oid.isdigit() else raw_oid
        stars = max(1, min(5, int(parts[2])))

        order = repo.get_order_by_id(TENANT_ID, order_id)
        if not order:
            await query.edit_message_text("⚠️ Pedido no encontrado.")
            return

        # Guardar calificación inicial
        repo.save_order_rating(
            tenant_id=TENANT_ID,
            order_id=order_id,
            driver_id=order.driver_id,
            customer_id=order.customer_id,
            rating=stars,
        )

        driver_name = "tu repartidor"
        if order.driver_id:
            d = repo.get_driver(order.driver_id)
            if d:
                driver_name = d.name

        stars_str = "⭐" * stars
        if stars >= 4:
            texto_encuesta = (
                f"🌟 **¡Muchas gracias por calificar con {stars_str}!** ({stars}/5)\n\n"
                f"¿Qué fue lo que más te agradó del servicio de {driver_name}?\n"
                "Selecciona una opción para completar la encuesta:"
            )
            keyboard = [
                [
                    InlineKeyboardButton("⚡ Rapidez y puntualidad", callback_data=f"rate_tag:{order_id}:Rapidez"),
                    InlineKeyboardButton("😊 Trato muy amable", callback_data=f"rate_tag:{order_id}:Amabilidad"),
                ],
                [
                    InlineKeyboardButton("🛡️ Cuidado y seguridad", callback_data=f"rate_tag:{order_id}:Seguridad"),
                    InlineKeyboardButton("✨ Servicio impecable", callback_data=f"rate_tag:{order_id}:Impecable"),
                ],
                [
                    InlineKeyboardButton("⏩ Finalizar sin detalles", callback_data=f"rate_tag:{order_id}:Omitido"),
                ],
            ]
        else:
            texto_encuesta = (
                f"🙏 **Agradecemos tu calificación de {stars_str}** ({stars}/5)\n\n"
                f"Lamentamos que tu experiencia con {driver_name} no haya sido óptima.\n"
                "¿En qué aspecto podemos mejorar para brindarte un mejor servicio?"
            )
            keyboard = [
                [
                    InlineKeyboardButton("⏳ Demora en la entrega", callback_data=f"rate_tag:{order_id}:Demora"),
                    InlineKeyboardButton("🙁 Actitud del chofer", callback_data=f"rate_tag:{order_id}:Actitud"),
                ],
                [
                    InlineKeyboardButton("📦 Problema con el cilindro", callback_data=f"rate_tag:{order_id}:Cilindro"),
                    InlineKeyboardButton("💵 Cobro o cambio", callback_data=f"rate_tag:{order_id}:Cobro"),
                ],
                [
                    InlineKeyboardButton("⏩ Finalizar sin detalles", callback_data=f"rate_tag:{order_id}:Omitido"),
                ],
            ]

        await query.edit_message_text(
            texto_encuesta,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
        return

    if data.startswith("rate_tag:"):
        parts = data.split(":")
        raw_oid = parts[1]
        order_id = int(raw_oid) if raw_oid.isdigit() else raw_oid
        tag = parts[2]

        tag_labels = {
            "Rapidez": "⚡ Rapidez y puntualidad",
            "Amabilidad": "😊 Trato amable y cordial",
            "Seguridad": "🛡️ Cuidado y manejo seguro",
            "Impecable": "✨ Servicio impecable",
            "Demora": "⏳ Demora o tiempo de espera",
            "Actitud": "🙁 Actitud o atención del chofer",
            "Cilindro": "📦 Estado del cilindro",
            "Cobro": "💵 Inconveniente con el cobro/cambio",
            "Omitido": "Servicio evaluado",
        }
        tag_display = tag_labels.get(tag, tag)
        feedback_to_save = "" if tag == "Omitido" else tag_display

        if feedback_to_save:
            repo.update_order_rating_feedback(TENANT_ID, order_id, feedback_tag=feedback_to_save)

        rating_data = repo.get_order_rating(TENANT_ID, order_id)
        stars_val = rating_data.get("rating", 5) if rating_data else 5
        stars_str = "⭐" * stars_val

        # Guardar en user_data que puede dejar un comentario de texto opcional
        context.user_data["awaiting_rating_comment_order_id"] = order_id
        context.user_data["awaiting_rating_time"] = datetime.now().timestamp()

        detalle_str = f"\n💬 **Aspecto destacado:** {tag_display}" if feedback_to_save else ""

        await query.edit_message_text(
            f"✅ **¡ENCUESTA COMPLETADA CON ÉXITO!**\n\n"
            f"⭐ **Calificación:** {stars_str} ({stars_val}/5){detalle_str}\n\n"
            "¡Muchas gracias por tu tiempo y valiosa retroalimentación! Nos ayuda a premiar a nuestros mejores choferes y elevar continuamente nuestra calidad. ⛽🌟\n\n"
            "_💡 Opcional: Si deseas agregar algún comentario o sugerencia escrita sobre tu repartidor, puedes enviarla en tu siguiente mensaje._",
            parse_mode="Markdown",
        )
        return



def main() -> None:
    """Iniciar el bot de Telegram."""
    if not TELEGRAM_BOT_TOKEN:
        print("❌ ERROR: TELEGRAM_BOT_TOKEN no está configurado en el archivo .env")
        sys.exit(1)

    print("=" * 60)
    print("🤖 Iniciando Bot de Telegram para Ventas de Gas")
    print(f"🏪 Tenant: {tenant.business_name} ({tenant.tenant_id})")
    print(f"🧠 Agente: {tenant.agent.name}")
    print("=" * 60)

    request_config = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .request(request_config)
        .get_updates_request(request_config)
        .build()
    )

    # Comando /start
    application.add_handler(CommandHandler("start", start))

    # Recepción de ubicación GPS / tiempo real
    application.add_handler(MessageHandler(filters.LOCATION, recibir_ubicacion_cliente))

    # Recepción de notas de voz y archivos de audio
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, recibir_voz_cliente))

    # Botones interactivos (Cancelar pedido)
    application.add_handler(CallbackQueryHandler(manejar_callback_cliente))

    # Mensajes de texto normales
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            responder,
        )
    )

    print("✅ Bot conectado con Telegram. Esperando mensajes y ubicaciones GPS...")
    application.run_polling(
        bootstrap_retries=10,
        poll_interval=1.0,
        timeout=30,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Bot de Clientes detenido correctamente por el usuario (Ctrl+C).")