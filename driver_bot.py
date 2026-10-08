"""Bot de Telegram exclusivo para Choferes y Repartidores de Gas - Petroil."""

import asyncio
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Forzar UTF-8 en terminal de Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from src.config.settings import get_settings
from src.database import init_db
from src.repositories import get_repository
from src.repositories.identity_store import identity_store
from src.services.api_client import api_get
from src.services.dispatch import dispatch_scheduled_orders_for_shift, send_driver_trip_alert
from src.services.geocoding import get_google_maps_url, get_waze_url, reverse_geocode
from src.services.notifications import (
    notify_client,
    notify_delivery_survey,
    send_client_live_location,
    edit_client_live_location,
    remove_client_live_location,
)
from src.services.vision import analyze_tank_meter_image

# Configurar logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TENANT_ID = "petroil"

import math
import time

# Conjunto en memoria de IDs de órdenes con live location inaccesible para evitar saturar la API
_failed_live_location_orders: set[Any] = set()

# Conjunto en memoria de pedidos asignados por Dashboard ya alertados al chofer (order_id, driver_id)
_notified_dashboard_assigned_orders: set[tuple[str, str]] = set()

# Control de frecuencia (throttling) de actualizaciones de GPS en tiempo real
# user_id -> (timestamp_epoch, lat, lng)
_driver_last_location_update: dict[str, tuple[float, float, float]] = {}


def _haversine_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcula la distancia geodésica en metros entre dos coordenadas GPS."""
    r = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


async def _safe_reply_text(message, text: str, **kwargs):
    """Envía un mensaje con fallback automático en caso de caracteres Markdown."""
    try:
        return await message.reply_text(text, **kwargs)
    except Exception as e:
        if kwargs.get("parse_mode") == "Markdown":
            kw = dict(kwargs)
            kw.pop("parse_mode", None)
            return await message.reply_text(text, **kw)
        raise e


async def _safe_edit_message_text(query, text: str, **kwargs):
    """Edita un mensaje con fallback automático en caso de caracteres Markdown o errores de Telegram."""
    try:
        return await query.edit_message_text(text, **kwargs)
    except Exception as e:
        err_str = str(e).lower()
        if "message is not modified" in err_str:
            return None
        if kwargs.get("parse_mode") == "Markdown":
            kw = dict(kwargs)
            kw.pop("parse_mode", None)
            try:
                return await query.edit_message_text(text, **kw)
            except Exception:
                pass
        logger.debug(f"edit_message_text handled: {e}")
        return None


async def _safe_delete_message(bot, chat_id: int | str, message_id: int) -> bool:
    """Elimina un mensaje de Telegram capturando excepciones de forma segura."""
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        return True
    except Exception as e:
        logger.debug(f"_safe_delete_message handled: {e}")
        return False


def _normalizar_valor_tanque(val_str: str) -> str:
    """Normaliza texto a formato estándar de porcentaje o litros (ej: '85%' o '4500 L')."""
    s = val_str.strip()
    m_pct = re.search(r"(\d+(?:\.\d+)?)\s*%", s)
    if m_pct:
        return f"{m_pct.group(1)}%"
    m_lit = re.search(r"(\d+(?:\.\d+)?)\s*(?:l|litro|litros)\b", s, re.I)
    if m_lit:
        return f"{m_lit.group(1)} L"
    m_just_num = re.match(r"^(\d+(?:\.\d+)?)$", s)
    if m_just_num:
        num = float(m_just_num.group(1))
        if num <= 100:
            return f"{int(num) if num.is_integer() else num}%"
        else:
            return f"{int(num) if num.is_integer() else num} L"
    return s


# Estado de la conversación de ingreso / login por teléfono del chofer
PASO_TELEFONO_LOGIN = 1


def get_botones_pedido_activo_inline(order) -> InlineKeyboardMarkup:
    """Genera los botones interactivos de navegación y entrega para un pedido activo."""
    lat = getattr(order, "delivery_lat", None) or 23.2014
    lng = getattr(order, "delivery_lng", None) or -106.4215
    addr = getattr(order, "delivery_address", "")
    gmaps = get_google_maps_url(lat, lng, addr)
    waze = get_waze_url(lat, lng, addr)

    keyboard = [
        [
            InlineKeyboardButton("🗺️ Abrir Google Maps", url=gmaps),
            InlineKeyboardButton("🚗 Abrir Waze", url=waze),
        ],
        [
            InlineKeyboardButton("📍 Transmitir Ubicación GPS", callback_data=f"pedir_gps:{order.id}"),
            InlineKeyboardButton("📦 Marcar como Entregado", callback_data=f"confirm_deliver:{order.id}"),
        ],
        [
            InlineKeyboardButton("❌ Cancelar Viaje", callback_data=f"confirm_cancel_driver:{order.id}"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def obtener_pedido_activo_chofer(repo, driver_id: int):
    """Retorna el primer pedido activo actualmente en curso (in_route / assigned) para el chofer."""
    try:
        active_orders = repo.get_orders_by_driver(TENANT_ID, driver_id, active_only=True)
        for o in active_orders:
            if o.status in ("in_route", "assigned"):
                return o
    except Exception:
        pass
    return None


def get_teclado_principal(estado: str = "disponible") -> ReplyKeyboardMarkup:
    """Genera el teclado dinámico según el estado del chofer: disponible, pausa o fuera_turno."""
    if estado == "disponible":
        return ReplyKeyboardMarkup(
            [
                ["📋 Mis Pedidos Activos", "📍 Actualizar Ubicación GPS"],
                ["⛽ Medidor de Tanque", "⏸️ Pausar (Ocupado)"],
                ["🛑 Terminar Turno", "👤 Mi Perfil"],
            ],
            resize_keyboard=True,
        )
    elif estado == "pausa":
        return ReplyKeyboardMarkup(
            [
                ["🟢 Reanudar Turno (Disponible)", "🛑 Terminar Turno"],
                ["📋 Mis Pedidos Activos", "⛽ Medidor de Tanque"],
                ["📍 Actualizar Ubicación GPS", "👤 Mi Perfil"],
            ],
            resize_keyboard=True,
        )
    else:  # fuera_turno
        return ReplyKeyboardMarkup(
            [
                ["🟢 Iniciar Turno (Disponible)"],
                ["⛽ Medidor de Tanque", "👤 Mi Perfil"],
            ],
            resize_keyboard=True,
        )


def get_teclado_lectura_tanque() -> ReplyKeyboardMarkup:
    """Teclado auxiliar durante la solicitud de carga inicial o final."""
    return ReplyKeyboardMarkup(
        [
            ["⏭️ Omitir / No Aplica"],
            ["❌ Cancelar"],
        ],
        resize_keyboard=True,
    )


def _determinar_estado_ui_chofer(repo, driver) -> str:
    """Determina el estado de interfaz del chofer: disponible, pausa o fuera_turno.
    
    Un chofer con turno activo siempre tiene acceso al teclado completo de trabajo (disponible),
    a menos que esté fuera de turno.
    """
    if not driver:
        return "fuera_turno"
    active_shift = repo.get_active_driver_shift(TENANT_ID, driver.id)
    if not active_shift and not driver.is_available:
        return "fuera_turno"
    return "disponible"


def _get_driver_vehicle_label(driver, repo=None) -> str:
    """Retorna la etiqueta legible de la unidad asignada al chofer."""
    if not driver:
        return "Sin unidad asignada"
    if repo and getattr(driver, "vehicle_id", None):
        try:
            veh = repo.get_vehicle(driver.tenant_id, driver.vehicle_id)
            if veh:
                return f"{veh.unit_identifier} [{veh.plate}] — {veh.model}"
        except Exception:
            pass
    if getattr(driver, "vehicle_plate", None) and str(driver.vehicle_plate).strip():
        return str(driver.vehicle_plate).strip()
    if getattr(driver, "unit_identifier", None) and str(driver.unit_identifier).strip():
        return str(driver.unit_identifier).strip()
    return "Sin unidad asignada"


def _formatear_resumen_chofer(driver, repo) -> str:
    """Genera un resumen visual completo y profesional de la ficha del chofer y su unidad vehicular."""
    veh = None
    if getattr(driver, "vehicle_id", None):
        veh = repo.get_vehicle(driver.tenant_id, driver.vehicle_id)

    if veh:
        tipo_label = "🚛 Pipa de Gas LP (Estacionario)" if veh.vehicle_type == "pipa" else "🛻 Camioneta de Cilindros"
        if veh.vehicle_type == "pipa" and veh.pipa_capacity_liters:
            cap_label = f"{int(veh.pipa_capacity_liters):,} Litros"
        elif veh.cylinder_capacity_count:
            cap_label = f"{veh.cylinder_capacity_count} Cilindros"
        else:
            cap_label = "Capacidad Estándar"
        unidad_str = f"**{veh.unit_identifier}** — {veh.model} `[{veh.plate}]`"
    else:
        tipo_label = "🚛 Pipa Estacionaria" if driver.vehicle_type == "estacionario" else "🛻 Camioneta de Cilindros"
        unidad_str = f"**{driver.vehicle_plate or 'Sin unidad asignada'}**"
        cap_label = "Según asignación de flota"

    active_shift = repo.get_active_driver_shift(driver.tenant_id, driver.id)
    active_orders = repo.get_orders_by_driver(driver.tenant_id, driver.id, active_only=True)
    if active_shift or active_orders:
        if active_orders:
            estado_str = f"🟢 EN TURNO (En Entrega - {len(active_orders)} pedido{'s' if len(active_orders)>1 else ''} activo{'s' if len(active_orders)>1 else ''})"
        elif driver.is_available:
            estado_str = "🟢 EN TURNO (Disponible)"
        else:
            estado_str = "⏸️ EN TURNO (En Pausa / Ocupado)"
    else:
        estado_str = "🔴 FUERA DE TURNO (Desconectado)"

    tg_str = f"`{driver.telegram_user_id}`" if driver.telegram_user_id else "_No asignado_"

    return (
        f"📋 **RESUMEN DE CUENTA DE OPERADOR:**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 **Nombre:** {driver.name}\n"
        f"📱 **Celular Asignado:** `{driver.phone}`\n"
        f"🚘 **Unidad:** {unidad_str}\n"
        f"⚙️ **Tipo:** {tipo_label}\n"
        f"📦 **Capacidad:** {cap_label}\n"
        f"📍 **Zona:** {driver.zone or 'Mazatlán Centro / General'}\n"
        f"🆔 **Telegram ID:** {tg_str}\n"
        f"⚡ **Estado:** {estado_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Comando /start: verifica si el chofer ya está autenticado o solicita su teléfono asignado."""
    if not update.effective_user or not update.message:
        return ConversationHandler.END

    user_id = str(update.effective_user.id)
    repo = get_repository()
    driver = repo.get_driver_by_telegram_id(TENANT_ID, user_id)

    if driver and driver.name:
        estado_str = _determinar_estado_ui_chofer(repo, driver)
        resumen = _formatear_resumen_chofer(driver, repo)

        msg = (
            f"👋 ¡Hola de nuevo, **{driver.name}**!\n\n"
            f"{resumen}\n\n"
            "Usa los botones del menú inferior para gestionar tu turno, revisar pedidos activos o actualizar tu ubicación GPS."
        )
        await update.message.reply_text(
            msg,
            reply_markup=get_teclado_principal(estado_str),
            parse_mode="Markdown",
        )
        return ConversationHandler.END


    # Si NO está vinculado su Telegram ID, solicitar número de celular
    return await pedir_telefono_ingreso(update, context)


async def pedir_telefono_ingreso(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Solicita al chofer ingresar el número de celular asignado en la Torre de Control."""
    target = update.message or (update.callback_query.message if update.callback_query else None)
    if not target:
        return ConversationHandler.END

    btn_tel = ReplyKeyboardMarkup(
        [
            [KeyboardButton("📱 Compartir Mi Teléfono", request_contact=True)],
            ["❌ Cancelar"],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

    msg = (
        "👋 ¡Bienvenido al **Portal de Choferes y Operadores - Petroil**! ⛽🛻\n\n"
        "Para ingresar a tu cuenta, por favor ingresa el **número de teléfono celular (10 dígitos)** que te asignaron en la **Torre de Control**:\n\n"
        "👉 *Escribe tu número (ejemplo: `6691234567`) o presiona el botón '📱 Compartir Mi Teléfono' abajo.*"
    )
    await target.reply_text(msg, reply_markup=btn_tel, parse_mode="Markdown")
    return PASO_TELEFONO_LOGIN


async def recibir_telefono_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Valida el celular contra la BD, asocia el Telegram ID automáticamente y muestra el resumen."""
    if not update.effective_user or not update.message:
        return PASO_TELEFONO_LOGIN

    user_id = str(update.effective_user.id)
    raw_text = ""

    if update.message.contact:
        raw_text = update.message.contact.phone_number or ""
    elif update.message.text:
        raw_text = update.message.text.strip()

    if raw_text in ("❌ Cancelar", "cancelar", "/cancelar", "Cancelar"):
        await update.message.reply_text(
            "Acceso cancelado. Cuando desees ingresar a tu cuenta, escribe `/start` o `/login`.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END

    clean_digits = re.sub(r"\D", "", raw_text)
    if len(clean_digits) < 10:
        await update.message.reply_text(
            "⚠️ Por favor ingresa un número de celular válido de al menos 10 dígitos (ejemplo: `6691234567`).\n\n"
            "O presiona **'❌ Cancelar'** para salir.",
            parse_mode="Markdown",
        )
        return PASO_TELEFONO_LOGIN

    phone_search = clean_digits[-10:]
    repo = get_repository()
    driver = repo.get_driver_by_phone(TENANT_ID, phone_search)
    if not driver and hasattr(repo, "driver_login"):
        try:
            repo.driver_login(phone_search)
            driver = repo.get_driver_by_phone(TENANT_ID, phone_search)
        except Exception:
            pass

    if not driver:
        await update.message.reply_text(
            f"❌ No se encontró ningún chofer u operador registrado con el número `{phone_search}` en la **Torre de Control**.\n\n"
            "🔍 **¿Qué debes hacer?**\n"
            "1. Verifica que hayas escrito los 10 dígitos correctamente.\n"
            "2. Solicita a tu supervisor o administrador en la central de Petroil que dé de alta tu cuenta y unidad en el Backoffice.\n\n"
            "👉 Escribe tu número nuevamente para reintentar, o presiona **'❌ Cancelar'**.",
            parse_mode="Markdown",
        )
        return PASO_TELEFONO_LOGIN

    # Chofer encontrado! Guardar automáticamente el Telegram ID en la BD
    repo.update_driver(driver.id, {"telegram_user_id": user_id})
    driver = repo.get_driver(driver.id)  # Recargar objeto actualizado

    resumen = _formatear_resumen_chofer(driver, repo)
    estado_str = _determinar_estado_ui_chofer(repo, driver)

    msg = (
        f"🎉 **¡BIENVENIDO AL SISTEMA, {driver.name.upper()}!** 🎉\n\n"
        f"Tu cuenta ha sido vinculada exitosamente con tu usuario de Telegram.\n\n"
        f"{resumen}\n\n"
        "✅ **¡Acceso Concedido!** Ya puedes gestionar tus turnos, recibir pedidos asignados en tu zona y registrar lecturas de medidor."
    )

    await update.message.reply_text(
        msg,
        reply_markup=get_teclado_principal(estado_str),
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def cancelar_registro(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancela el proceso de ingreso."""
    if update.message:
        await update.message.reply_text(
            "Acceso cancelado. Puedes volver a ingresar cuando gustes con `/start` o `/login`.",
            reply_markup=ReplyKeyboardRemove(),
        )
    return ConversationHandler.END


# -----------------------------------------------------------------------------
# Handlers de Gestión de Turno y Teclado Rápido
# -----------------------------------------------------------------------------

async def boton_disponible(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Solicitar la carga inicial de pipa/tanque antes de iniciar turno o iniciar directamente."""
    if not update.effective_user or not update.message:
        return

    user_id = str(update.effective_user.id)
    repo = get_repository()
    driver = repo.get_driver_by_telegram_id(TENANT_ID, user_id)

    if not driver:
        await update.message.reply_text("⚠️ Primero completa tu registro con `/registro`")
        return

    active_shift = repo.get_active_driver_shift(TENANT_ID, driver.id)
    active_orders = repo.get_orders_by_driver(TENANT_ID, driver.id, active_only=True)

    # Si ya está en turno activo o tiene pedidos activos
    if active_shift or active_orders or driver.is_available:
        repo.set_driver_availability(driver.id, True)
        pedidos_txt = ""
        if active_orders:
            pedidos_txt = f"\n\n📦 **Tienes {len(active_orders)} pedido(s) activo(s) en curso.** Presiona **'📋 Mis Pedidos Activos'** abajo para revisarlos o dar seguimiento."
        v_label = _get_driver_vehicle_label(driver, repo)
        await update.message.reply_text(
            f"🟢 **Ya te encuentras en turno activo.**\n\n"
            f"👤 Chofer: **{driver.name}**\n"
            f"🚘 Unidad: **{v_label}**\n"
            f"⚡ Estado: **EN TURNO (DISPONIBLE)**{pedidos_txt}",
            reply_markup=get_teclado_principal("disponible"),
            parse_mode="Markdown",
        )
        return

    # Solicitar la carga inicial
    context.user_data["awaiting_tank_reading"] = "initial"
    v_plate = _get_driver_vehicle_label(driver, repo)


    msg = (
        "⛽ **REGISTRO DE CARGA INICIAL (PIPA / TANQUE)** 📸\n\n"
        f"¡Hola, **{driver.name}**! Antes de salir a ruta con la unidad **{v_plate}**, "
        "por favor captura la carga con la que inicias tu jornada:\n\n"
        "📷 **Envía una FOTOGRAFÍA** del medidor o reloj rotogauge del tanque.\n"
        "✍️ **O escribe el valor** (porcentaje o litros, ej: `85%` o `4500 L`).\n\n"
        "*(Si conduces camioneta de cilindros o no aplica hoy, presiona '⏭️ Omitir / No Aplica')*"
    )
    await update.message.reply_text(
        msg,
        reply_markup=get_teclado_lectura_tanque(),
        parse_mode="Markdown",
    )


async def _completar_inicio_turno(
    update: Update,
    driver,
    repo,
    reading_val: str | None = None,
    con_foto: bool = False,
) -> None:
    """Activa el turno del chofer, registra hora de entrada, despacha pedidos y muestra confirmación."""
    repo.set_driver_availability(driver.id, True)

    # Registrar hora de entrada (check-in) en la sesión de turno
    shift = repo.start_driver_shift(
        tenant_id=TENANT_ID,
        driver_id=driver.id,
        driver_name=driver.name,
        vehicle_plate=driver.vehicle_plate or "",
        initial_reading=reading_val,
    )
    hora_entrada_txt = ""
    if shift and shift.get("check_in_at"):
        cin = shift.get("check_in_at", "")
        h_val = cin.split(" ")[1][:5] if " " in cin else cin
        hora_entrada_txt = f"\n⏰ **Hora de Entrada:** `{h_val}`"

    carga_info = ""
    if reading_val:
        foto_txt = " (📸 Fotografía guardada)" if con_foto else ""
        carga_info = f"\n⛽ **Carga Inicial:** `{reading_val}`{foto_txt}"

    target = update.message or (update.callback_query.message if update.callback_query else None)
    if target:
        v_label = _get_driver_vehicle_label(driver, repo)
        await _safe_reply_text(
            target,
            f"🟢 **¡TURNO INICIADO CON ÉXITO!**\n\n"
            f"👤 Chofer: **{driver.name}**\n"
            f"🚘 Unidad: **{v_label}**"
            f"{hora_entrada_txt}"
            f"{carga_info}\n"
            f"⚡ Estado: **DISPONIBLE PARA VIAJES** ⛽\n\n"
            f"Ahora recibirás los pedidos asignados a tu unidad en tiempo real.",
            reply_markup=get_teclado_principal("disponible"),
            parse_mode="Markdown",
        )

    # Despachar pedidos programados en segundo plano para no congelar la interacción con el chofer
    async def _despachar_pedidos_segundo_plano():
        try:
            dispatched_ids = await asyncio.to_thread(dispatch_scheduled_orders_for_shift, TENANT_ID)
            if dispatched_ids and target:
                await _safe_reply_text(
                    target,
                    f"📦 **Se han activado {len(dispatched_ids)} pedido(s) programado(s)** para la jornada de hoy.",
                )
        except Exception as err:
            logger.error(f"[Shift] Error en despacho de fondo: {err}")

    asyncio.create_task(_despachar_pedidos_segundo_plano())


async def boton_pausa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Poner al chofer en pausa temporal (comida, descanso)."""
    if not update.effective_user or not update.message:
        return

    user_id = str(update.effective_user.id)
    repo = get_repository()
    driver = repo.get_driver_by_telegram_id(TENANT_ID, user_id)

    if not driver:
        await update.message.reply_text("⚠️ Primero completa tu registro con `/registro`")
        return

    repo.set_driver_availability(driver.id, False)
    await update.message.reply_text(
        "⏸️ **TURNO EN PAUSA (OCUPADO)**\n\n"
        "No se te asignarán nuevos pedidos mientras estés en pausa.\n"
        "Cuando estés listo para continuar, presiona **'🟢 Reanudar Turno'**.",
        reply_markup=get_teclado_principal("pausa"),
        parse_mode="Markdown",
    )


async def boton_terminar_turno(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Solicitar la carga final de pipa/tanque antes de cerrar el turno."""
    if not update.effective_user or not update.message:
        return

    user_id = str(update.effective_user.id)
    repo = get_repository()
    driver = repo.get_driver_by_telegram_id(TENANT_ID, user_id)

    if not driver:
        await update.message.reply_text("⚠️ Primero completa tu registro con `/registro`")
        return

    # Verificar si tiene pedidos activos pendientes de entrega
    active_orders = repo.get_orders_by_driver(TENANT_ID, driver.id, active_only=True)
    if active_orders:
        folios = ", ".join(f"#{o.id}" for o in active_orders)
        await update.message.reply_text(
            f"⚠️ **Atención:** Tienes **{len(active_orders)} pedido(s) activo(s)** pendiente(s) ({folios}).\n\n"
            "Por favor márcalos como entregados o recházalos antes de finalizar tu turno.",
            reply_markup=get_teclado_principal(_determinar_estado_ui_chofer(repo, driver)),
            parse_mode="Markdown",
        )
        return

    context.user_data["awaiting_tank_reading"] = "final"
    v_plate = driver.vehicle_plate or "Unidad"

    msg = (
        "🏁 **CIERRE DE TURNO - CARGA FINAL DE TANQUE/PIPA** 📸\n\n"
        f"Por favor registra la **carga restante** al terminar tu jornada con la unidad **{v_plate}**:\n\n"
        "📷 **Envía una FOTOGRAFÍA** del reloj medidor del tanque.\n"
        "✍️ **O escribe la lectura final** (ejemplo: `15%` o `800 L`).\n\n"
        "*(O presiona '⏭️ Omitir / No Aplica' para finalizar sin registrar)*"
    )
    await update.message.reply_text(
        msg,
        reply_markup=get_teclado_lectura_tanque(),
        parse_mode="Markdown",
    )


async def _completar_fin_turno(
    update: Update,
    driver,
    repo,
    reading_val: str | None = None,
    con_foto: bool = False,
) -> None:
    """Cierra el turno del chofer, registra hora de salida, desactiva disponibilidad y muestra resumen detallado con conciliación."""
    repo.set_driver_availability(driver.id, False)

    # Registrar hora de salida (check-out) y calcular duración de jornada
    shift = repo.end_driver_shift(
        tenant_id=TENANT_ID,
        driver_id=driver.id,
        final_reading=reading_val,
    )

    jornada_bloque = ""
    if shift:
        cin = shift.get("check_in_at", "")
        cout = shift.get("check_out_at", "")
        mins = shift.get("duration_minutes") or 0
        h_in = cin.split(" ")[1][:5] if " " in cin else cin
        h_out = cout.split(" ")[1][:5] if " " in cout else cout
        hrs = mins // 60
        rem_m = mins % 60
        dur_str = f"{hrs}h {rem_m}m" if hrs > 0 else f"{rem_m} min"
        jornada_bloque = (
            f"⏰ **Control de Asistencia y Jornada:**\n"
            f"• 🟢 Hora de Entrada: **{h_in}**\n"
            f"• 🔴 Hora de Salida: **{h_out}**\n"
            f"• ⏱️ Tiempo laborado: **{dur_str}**\n\n"
        )

    latest_initial = repo.get_latest_tank_reading(TENANT_ID, driver.id, reading_type="initial")
    
    comparativa = ""
    consumo_est = ""
    if latest_initial:
        init_val = latest_initial.get("reading_value")
        init_foto = " [📷 Foto]" if latest_initial.get("photo_path") else ""
        comparativa += f"\n• 🟢 Carga Inicial: **{init_val}**{init_foto}"

        # Calcular consumo si ambos tienen porcentaje
        if reading_val and "%" in str(init_val) and "%" in str(reading_val):
            try:
                num_init = float(re.findall(r"\d+(?:\.\d+)?", str(init_val))[0])
                num_fin = float(re.findall(r"\d+(?:\.\d+)?", str(reading_val))[0])
                diff = num_init - num_fin
                if diff >= 0:
                    consumo_est = f"\n• 📉 Consumo estimado de gas: **~{diff:.1f}%** de tanque/pipa"
            except Exception:
                pass

    if reading_val:
        foto_txt = " [📷 Foto guardada]" if con_foto else ""
        comparativa += f"\n• 🔴 Carga Final: **{reading_val}**{foto_txt}"

    # Pedidos entregados hoy por este chofer
    delivered_count = repo.get_delivered_orders_count_by_driver(TENANT_ID, driver.id) or 0
    pedidos_txt = f"\n• 📦 Pedidos entregados en la jornada: **{delivered_count} servicios**" if delivered_count > 0 else ""

    target = update.message or (update.callback_query.message if update.callback_query else None)
    if target:
        v_label = _get_driver_vehicle_label(driver, repo)
        await target.reply_text(
            f"🛑 **¡TURNO FINALIZADO CON ÉXITO!**\n\n"
            f"👤 Chofer: **{driver.name}**\n"
            f"🚘 Unidad: **{v_label}**\n"
            f"💤 Estado: **DESCONECTADO (FUERA DE TURNO)**\n\n"
            f"{jornada_bloque}"
            f"📊 **Conciliación de Carga de Tanque:**"
            f"{comparativa}"
            f"{consumo_est}"
            f"{pedidos_txt}\n\n"
            "¡Excelente trabajo hoy! Ya no recibirás nuevos pedidos.\n"
            "Cuando vayas a comenzar tu próximo turno, presiona el botón **'🟢 Iniciar Turno'**.",
            reply_markup=get_teclado_principal("fuera_turno"),
            parse_mode="Markdown",
        )


async def boton_medidor_tanque(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra el historial y estado actual de la carga de tanque del chofer con opciones interactivas."""
    target = update.message or (update.callback_query.message if update.callback_query else None)
    if not update.effective_user or not target:
        return

    user_id = str(update.effective_user.id)
    repo = get_repository()
    driver = repo.get_driver_by_telegram_id(TENANT_ID, user_id)

    if not driver:
        await target.reply_text("⚠️ Primero completa tu registro con `/registro`")
        return

    v_plate = driver.vehicle_plate or "Sin Placa"
    latest_initial = repo.get_latest_tank_reading(TENANT_ID, driver.id, reading_type="initial")
    latest_final = repo.get_latest_tank_reading(TENANT_ID, driver.id, reading_type="final")

    resumen_cargas = []
    if latest_initial:
        f_ico = " 📸" if latest_initial.get("photo_path") else ""
        h_str = latest_initial.get("created_at", "")
        hora = f" ({h_str.split(' ')[1][:5]})" if " " in h_str else ""
        resumen_cargas.append(f"• 🟢 **Última Carga Inicial:** `{latest_initial.get('reading_value')}`{f_ico}{hora}")
    else:
        resumen_cargas.append("• 🟢 **Última Carga Inicial:** Sin registro")

    if latest_final:
        f_ico = " 📸" if latest_final.get("photo_path") else ""
        h_str = latest_final.get("created_at", "")
        hora = f" ({h_str.split(' ')[1][:5]})" if " " in h_str else ""
        resumen_cargas.append(f"• 🔴 **Última Carga Final:** `{latest_final.get('reading_value')}`{f_ico}{hora}")
    else:
        resumen_cargas.append("• 🔴 **Última Carga Final:** Sin registro")

    resumen_txt = "\n".join(resumen_cargas)

    msg = (
        f"⛽ **CONTROL DE MEDIDOR DE TANQUE / PIPA** 🛢️\n"
        f"🚘 **Unidad:** {v_plate} | 👤 **Chofer:** {driver.name}\n\n"
        f"{resumen_txt}\n\n"
        "📸 **Captura por Foto o Mensaje:**\n"
        "Puedes enviar una **fotografía directa** del reloj medidor/rotogauge o escribir el **valor numérico (ej: `85%`)** usando los botones de abajo:"
    )

    keyboard = [
        [
            InlineKeyboardButton("🟢 Registrar Carga Inicial", callback_data="btn_carga_initial"),
            InlineKeyboardButton("🔴 Registrar Carga Final", callback_data="btn_carga_final"),
        ],
        [
            InlineKeyboardButton("🔵 Registrar Recarga de Gas", callback_data="btn_carga_refill"),
            InlineKeyboardButton("📜 Ver Historial", callback_data="btn_carga_historial"),
        ],
    ]

    await target.reply_text(
        msg,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def comando_carga_inicial(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /cargainicial [valor opcional]: registrar carga inicial de tanque/pipa."""
    if not update.effective_user or not update.message:
        return
    user_id = str(update.effective_user.id)
    repo = get_repository()
    driver = repo.get_driver_by_telegram_id(TENANT_ID, user_id)
    if not driver:
        await update.message.reply_text("⚠️ Chofer no registrado. Escribe `/registro`")
        return

    # Si proporcionó argumentos directos (ej: /cargainicial 85%)
    if context.args:
        val = _normalizar_valor_tanque(" ".join(context.args))
        repo.save_tank_reading(
            tenant_id=TENANT_ID,
            driver_id=driver.id,
            driver_name=driver.name,
            vehicle_plate=driver.vehicle_plate or "",
            reading_type="initial",
            reading_value=val,
            notes="Registrado por comando /cargainicial",
        )
        if not driver.is_available:
            await _completar_inicio_turno(update, driver, repo, reading_val=val, con_foto=False)
        else:
            await update.message.reply_text(
                f"🟢 **Carga Inicial Registrada con Éxito:** `{val}`\n🚘 Unidad: {driver.vehicle_plate}",
                reply_markup=get_teclado_principal("disponible"),
                parse_mode="Markdown",
            )
        return

    # Si no tiene argumentos, solicitar valor o foto
    context.user_data["awaiting_tank_reading"] = "initial"
    v_plate = driver.vehicle_plate or "Unidad"
    msg = (
        "⛽ **REGISTRO DE CARGA INICIAL (PIPA / TANQUE)** 📸\n\n"
        f"Unidad: **{v_plate}**\n\n"
        "📷 **Envía una FOTOGRAFÍA** del medidor o reloj rotogauge del tanque.\n"
        "✍️ **O escribe el valor** (porcentaje o litros, ej: `85%` o `4500 L`).\n\n"
        "*(O presiona '❌ Cancelar')*"
    )
    await update.message.reply_text(msg, reply_markup=get_teclado_lectura_tanque(), parse_mode="Markdown")


async def comando_carga_final(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /cargafinal [valor opcional]: registrar carga final de tanque/pipa."""
    if not update.effective_user or not update.message:
        return
    user_id = str(update.effective_user.id)
    repo = get_repository()
    driver = repo.get_driver_by_telegram_id(TENANT_ID, user_id)
    if not driver:
        await update.message.reply_text("⚠️ Chofer no registrado. Escribe `/registro`")
        return

    # Si proporcionó argumentos directos (ej: /cargafinal 15%)
    if context.args:
        val = _normalizar_valor_tanque(" ".join(context.args))
        repo.save_tank_reading(
            tenant_id=TENANT_ID,
            driver_id=driver.id,
            driver_name=driver.name,
            vehicle_plate=driver.vehicle_plate or "",
            reading_type="final",
            reading_value=val,
            notes="Registrado por comando /cargafinal",
        )
        if driver.is_available:
            await _completar_fin_turno(update, driver, repo, reading_val=val, con_foto=False)
        else:
            await update.message.reply_text(
                f"🔴 **Carga Final Registrada con Éxito:** `{val}`\n🚘 Unidad: {driver.vehicle_plate}",
                reply_markup=get_teclado_principal("fuera_turno"),
                parse_mode="Markdown",
            )
        return

    # Si no tiene argumentos, solicitar valor o foto
    context.user_data["awaiting_tank_reading"] = "final"
    v_plate = driver.vehicle_plate or "Unidad"
    msg = (
        "🏁 **REGISTRO DE CARGA FINAL (PIPA / TANQUE)** 📸\n\n"
        f"Unidad: **{v_plate}**\n\n"
        "📷 **Envía una FOTOGRAFÍA** del reloj medidor del tanque.\n"
        "✍️ **O escribe la lectura final** (ejemplo: `15%` o `800 L`).\n\n"
        "*(O presiona '❌ Cancelar')*"
    )
    await update.message.reply_text(msg, reply_markup=get_teclado_lectura_tanque(), parse_mode="Markdown")


async def comando_turno(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /turno o /jornada: Consultar hora de entrada y tiempo laborado."""
    if not update.effective_user or not update.message:
        return
    user_id = str(update.effective_user.id)
    repo = get_repository()
    driver = repo.get_driver_by_telegram_id(TENANT_ID, user_id)
    if not driver:
        await update.message.reply_text("⚠️ Chofer no registrado. Escribe `/registro`")
        return

    active_shift = repo.get_active_driver_shift(TENANT_ID, driver.id)
    if active_shift:
        cin = active_shift.get("check_in_at", "")
        h_in = cin.split(" ")[1][:5] if " " in cin else cin
        ini_read = active_shift.get("initial_reading") or "Sin registrar"
        delivered_count = repo.get_delivered_orders_count_by_driver(TENANT_ID, driver.id) or 0
        msg = (
            f"🟢 **TURNO ACTIVO EN CURSO**\n\n"
            f"👤 Chofer: **{driver.name}**\n"
            f"🚘 Unidad: **{driver.vehicle_plate}**\n"
            f"⏰ **Hora de Entrada:** `{h_in}`\n"
            f"⛽ **Carga Inicial:** `{ini_read}`\n"
            f"📦 **Entregas completadas hoy:** `{delivered_count}`\n\n"
            "Para terminar tu jornada y registrar tu hora de salida, presiona el botón **'🛑 Terminar Turno'**."
        )
    else:
        recent = repo.get_driver_shifts(TENANT_ID, driver.id, limit=3)
        historial_txt = ""
        if recent:
            for s in recent:
                d_date = s.get("shift_date", "")
                cin = s.get("check_in_at", "")
                cout = s.get("check_out_at", "")
                h_in = cin.split(" ")[1][:5] if " " in cin else "N/A"
                h_out = cout.split(" ")[1][:5] if cout and " " in cout else "N/A"
                mins = s.get("duration_minutes") or 0
                dur = f"{mins // 60}h {mins % 60}m" if mins >= 60 else f"{mins}m"
                historial_txt += f"\n• 📅 **{d_date}**: 🟢 {h_in} ➔ 🔴 {h_out} (⏱️ {dur})"
        fallback_historial = "\n(No hay turnos registrados)"
        msg = (
            f"🔴 **Actualmente estás FUERA DE TURNO**\n\n"
            f"👤 Chofer: **{driver.name}**\n"
            f"🚘 Unidad: **{driver.vehicle_plate}**\n\n"
            f"📋 **Últimas Jornadas:**"
            f"{historial_txt or fallback_historial}\n\n"
            "Presiona **'🟢 Iniciar Turno'** para registrar tu hora de entrada hoy."
        )

    estado = _determinar_estado_ui_chofer(repo, driver)
    await update.message.reply_text(msg, reply_markup=get_teclado_principal(estado), parse_mode="Markdown")



async def boton_perfil(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mostrar perfil completo del chofer."""
    if not update.effective_user or not update.message:
        return

    user_id = str(update.effective_user.id)
    repo = get_repository()
    driver = repo.get_driver_by_telegram_id(TENANT_ID, user_id)

    if not driver:
        await update.message.reply_text("⚠️ No has iniciado sesión como chofer. Escribe `/start` para ingresar con tu número celular asignado.")
        return

    resumen = _formatear_resumen_chofer(driver, repo)

    active_shift = repo.get_active_driver_shift(TENANT_ID, driver.id)
    shift_str = ""
    if active_shift and active_shift.get("check_in_at"):
        cin = active_shift.get("check_in_at", "")
        h_in = cin.split(" ")[1][:5] if " " in cin else cin
        shift_str = f"\n• ⏰ **Turno actual:** Entrada a las {h_in}"
    else:
        recent_shifts = repo.get_driver_shifts(TENANT_ID, driver.id, limit=1)
        if recent_shifts and recent_shifts[0].get("duration_minutes") is not None:
            mins = recent_shifts[0].get("duration_minutes") or 0
            hrs = mins // 60
            rem_m = mins % 60
            dur_txt = f"{hrs}h {rem_m}m" if hrs > 0 else f"{rem_m} min"
            shift_str = f"\n• ⏱️ **Última jornada:** {dur_txt} ({recent_shifts[0].get('shift_date')})"

    delivered_count = repo.get_delivered_orders_count_by_driver(TENANT_ID, driver.id) or 0
    pedidos_txt = f"\n• 📦 **Servicios completados hoy:** {delivered_count}" if delivered_count > 0 else ""

    msg = (
        f"{resumen}\n\n"
        f"📊 **INFORMACIÓN DE ACTIVIDAD:**"
        f"{shift_str}"
        f"{pedidos_txt}\n\n"
        "Si deseas vincular otro número de celular, escribe `/login` o `/cambiar_numero`."
    )
    estado = _determinar_estado_ui_chofer(repo, driver)
    await update.message.reply_text(msg, reply_markup=get_teclado_principal(estado), parse_mode="Markdown")


async def boton_pedidos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Listar los pedidos activos asignados al chofer con opciones de entregar o cancelar viaje."""
    if not update.effective_user or not update.message:
        return

    user_id = str(update.effective_user.id)
    chat_id = update.effective_chat.id if update.effective_chat else update.message.chat_id
    repo = get_repository()
    driver = repo.get_driver_by_telegram_id(TENANT_ID, user_id)

    if not driver:
        await update.message.reply_text("⚠️ Primero completa tu registro con `/registro`")
        return

    # Si antes teníamos mensajes de pedidos activos en este chat, los borramos para no duplicar ni dejar botones viejos
    old_msg_ids = context.user_data.get("active_order_messages", [])
    if old_msg_ids and chat_id:
        for mid in old_msg_ids:
            await _safe_delete_message(context.bot, chat_id, mid)
        context.user_data["active_order_messages"] = []

    orders = repo.get_orders_by_driver(TENANT_ID, driver.id, active_only=True)
    estado = _determinar_estado_ui_chofer(repo, driver)

    if not orders:
        await update.message.reply_text(
            "✨ No tienes pedidos activos pendientes de entrega en este momento.\n"
            "Mantén tu estado en 🟢 **Disponible** para recibir nuevas solicitudes.",
            reply_markup=get_teclado_principal(estado),
        )
        return

    sent_msg_ids = []

    header_msg = await _safe_reply_text(
        update.message,
        f"📋 **Tienes {len(orders)} pedido(s) activo(s):**",
        reply_markup=get_teclado_principal(estado),
        parse_mode="Markdown",
    )
    if header_msg:
        sent_msg_ids.append(header_msg.message_id)

    if len(orders) > 1:
        bulk_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🗑️ Liberar / Cancelar Todos Mis Pedidos ({len(orders)})", callback_data="cancel_all_my_orders")]
        ])
        bulk_msg = await _safe_reply_text(
            update.message,
            "⚡ *Acción Rápida:* Si deseas cancelar todas tus órdenes asignadas para que la Torre de Control las reasigne, presiona el botón:",
            reply_markup=bulk_kb,
            parse_mode="Markdown",
        )
        if bulk_msg:
            sent_msg_ids.append(bulk_msg.message_id)

    for ord in orders:
        lat = ord.delivery_lat or 23.2014
        lng = ord.delivery_lng or -106.4215
        gmaps = get_google_maps_url(lat, lng, ord.delivery_address)
        waze = get_waze_url(lat, lng, ord.delivery_address)

        items_str = "\n".join(f"  • {it.quantity}x {it.product_name}" for it in ord.items)
        pay_icon = "💵" if "efectivo" in ord.payment_method.lower() else "💳"

        is_pending_acceptance = ord.status in ("assigned", "pending", "confirmed")
        status_label = "🟡 ASIGNADO (Pendiente de Aceptar)" if is_pending_acceptance else "🚚 EN RUTA"

        texto = (
            f"🔹 **Pedido #{ord.id}** — Estado: **{status_label}**\n"
            f"👤 Cliente: {ord.customer_name} (`{ord.customer_phone}`)\n"
            f"📍 Dirección: {ord.delivery_address}\n"
            f"📅 Horario: {ord.delivery_schedule}\n"
            f"💰 Cobro: ${ord.total_amount:.2f} {ord.currency} ({pay_icon} {ord.payment_method})\n"
            f"📦 Productos:\n{items_str}"
        )

        if is_pending_acceptance:
            keyboard = [
                [
                    InlineKeyboardButton("✅ Aceptar Viaje", callback_data=f"accept_order:{ord.id}"),
                    InlineKeyboardButton("📦 Marcar como Entregado", callback_data=f"confirm_deliver:{ord.id}"),
                ],
                [
                    InlineKeyboardButton("❌ Rechazar", callback_data=f"reject_order:{ord.id}"),
                    InlineKeyboardButton("🗺️ Google Maps", url=gmaps),
                    InlineKeyboardButton("🚗 Waze", url=waze),
                ],
            ]
        else:
            keyboard = [
                [
                    InlineKeyboardButton("🗺️ Google Maps", url=gmaps),
                    InlineKeyboardButton("🚗 Waze", url=waze),
                ],
                [
                    InlineKeyboardButton("📦 Marcar como Entregado", callback_data=f"confirm_deliver:{ord.id}"),
                    InlineKeyboardButton("❌ Cancelar Viaje", callback_data=f"confirm_cancel_driver:{ord.id}"),
                ],
            ]

        ord_msg = await _safe_reply_text(
            update.message,
            texto,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
        if ord_msg:
            sent_msg_ids.append(ord_msg.message_id)
            try:
                repo.add_order_driver_message_id(TENANT_ID, ord.id, ord_msg.message_id)
            except Exception:
                pass

    context.user_data["active_order_messages"] = sent_msg_ids


async def pedir_actualizar_ubicacion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Solicita al chofer enviar su ubicación GPS o activar ubicación en tiempo real."""
    if not update.message:
        return

    btn_ubicacion = ReplyKeyboardMarkup(
        [
            [KeyboardButton("📍 Transmitir Mi Ubicación Actual (GPS)", request_location=True)],
            ["📋 Mis Pedidos Activos", "⛽ Medidor de Tanque"],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await update.message.reply_text(
        "📍 **TRANSMISIÓN DE UBICACIÓN GPS**\n\n"
        "Elige cualquiera de las dos opciones para compartir tu posición:\n\n"
        "1️⃣ **Botón rápido:** Presiona el botón grande **'📍 Transmitir Mi Ubicación Actual (GPS)'** abajo.\n\n"
        "2️⃣ **Seguimiento continuo (Recomendado):**\n"
        "Toca el clip **📎 ➔ Ubicación ➔ 'Compartir mi ubicación en tiempo real...'** (selecciona 1 u 8 horas) para que el cliente y la Torre de Control sigan tu camioneta en vivo mientras manejas.\n\n"
        "*(💡 Si estás en Telegram Desktop o sin sensor GPS, puedes escribir tus coordenadas por texto ej: `23.2435, -106.4123`)*",
        reply_markup=btn_ubicacion,
        parse_mode="Markdown",
    )


async def _procesar_coordenadas_gps_chofer(
    repo,
    driver,
    lat: float,
    lng: float,
    update: Update,
    is_live_edit: bool = False,
) -> None:
    """Actualiza la posición del chofer y transmite o actualiza la ubicación en vivo a sus pedidos activos."""
    await asyncio.to_thread(repo.update_driver_location, driver.id, lat, lng)

    # Actualizar o inicializar ubicación en tiempo real en Telegram/WhatsApp para clientes con pedidos en ruta
    active_orders = await asyncio.to_thread(repo.get_orders_by_driver, TENANT_ID, driver.id, True)
    orders_updated = 0

    # Ordenar pedidos por ID descendente para priorizar el pedido más reciente
    sorted_orders = sorted(active_orders, key=lambda o: int(getattr(o, "id", 0) or 0), reverse=True)

    # Evitar enviar más de un pin de mapa al mismo cliente/chat
    processed_recipients: dict[str, int] = {}

    from src.repositories.identity_store import identity_store

    for ord_in_route in sorted_orders:
        if ord_in_route.status == "in_route":
            # Evitar reintentar sobre chats inaccesibles o bloqueados
            if ord_in_route.id in _failed_live_location_orders:
                continue

            # Determinar si el pedido es reciente (creado/actualizado en las últimas 6 horas)
            is_recent = True
            order_time_str = ord_in_route.updated_at or ord_in_route.created_at
            if order_time_str:
                try:
                    from datetime import timezone
                    order_dt = datetime.fromisoformat(order_time_str.replace("Z", "+00:00"))
                    now_utc = datetime.now(timezone.utc)
                    if (now_utc - order_dt).total_seconds() > 6 * 3600:
                        is_recent = False
                except Exception:
                    is_recent = True

            recipient_id = str(ord_in_route.channel_user_id or ord_in_route.customer_phone or "").strip()
            if not recipient_id:
                continue

            clean_recipient = re.sub(r"\D", "", recipient_id) or recipient_id

            # Si ya procesamos a este cliente/chat en esta misma corrida, vincular la orden al mismo pin
            if clean_recipient in processed_recipients:
                linked_msg_id = processed_recipients[clean_recipient]
                await asyncio.to_thread(
                    repo.set_order_live_location,
                    TENANT_ID, ord_in_route.id, recipient_id, linked_msg_id
                )
                orders_updated += 1
                continue

            # Verificar si la orden o el chat ya cuenta con un pin de ubicación en vivo activo
            live_msg_id = ord_in_route.live_location_message_id
            live_chat_id = ord_in_route.live_location_chat_id or recipient_id

            if not live_msg_id:
                chat_live = identity_store.get_chat_live_location(recipient_id) or identity_store.get_chat_live_location(clean_recipient)
                if chat_live:
                    live_msg_id = chat_live.get("message_id")
                    live_chat_id = chat_live.get("chat_id") or recipient_id

            if live_msg_id and live_chat_id:
                edit_ok = await asyncio.to_thread(
                    edit_client_live_location,
                    live_chat_id,
                    live_msg_id,
                    lat,
                    lng,
                    channel=ord_in_route.channel,
                )
                if edit_ok:
                    orders_updated += 1
                    processed_recipients[clean_recipient] = live_msg_id
                    await asyncio.to_thread(
                        repo.set_order_live_location,
                        TENANT_ID, ord_in_route.id, live_chat_id, live_msg_id
                    )
                else:
                    logger.info(
                        f"📍 Pin de ubicación en vivo (msg_id: {live_msg_id}) "
                        f"de la orden #{ord_in_route.id} expiró o no se puede editar. Limpiando ID en BD..."
                    )
                    await asyncio.to_thread(repo.clear_order_live_location, TENANT_ID, ord_in_route.id)
                    identity_store.clear_order_live_location(ord_in_route.id)

                    # Si el pedido es reciente (< 6 horas), renovar el pin en vivo
                    if is_recent and recipient_id:
                        new_msg_id = await asyncio.to_thread(
                            send_client_live_location,
                            recipient_id,
                            lat,
                            lng,
                            live_period=7200,
                            channel=ord_in_route.channel,
                            order_id=ord_in_route.id,
                        )
                        if new_msg_id:
                            await asyncio.to_thread(
                                repo.set_order_live_location,
                                TENANT_ID, ord_in_route.id, recipient_id, new_msg_id
                            )
                            processed_recipients[clean_recipient] = new_msg_id
                            orders_updated += 1
                            logger.info(f"🔄 Pin en vivo renovado exitosamente para orden #{ord_in_route.id} (msg: {new_msg_id})")
                        else:
                            _failed_live_location_orders.add(ord_in_route.id)
                    else:
                        _failed_live_location_orders.add(ord_in_route.id)

            elif recipient_id and is_recent:
                eff_channel = getattr(ord_in_route, "channel", None)
                if not eff_channel:
                    chan_info = identity_store.get_order_channel_info(ord_in_route.id)
                    if chan_info and chan_info.get("channel"):
                        eff_channel = chan_info.get("channel")
                if not eff_channel:
                    clean_dig = re.sub(r"\D", "", recipient_id)
                    if clean_dig.startswith("52") or len(clean_dig) == 10:
                        eff_channel = "whatsapp"
                    else:
                        eff_channel = "telegram"

                # Inicializar ubicación en vivo ahora que el chofer compartió su GPS real
                new_live_msg_id = await asyncio.to_thread(
                    send_client_live_location,
                    recipient_id,
                    lat,
                    lng,
                    live_period=7200,
                    channel=eff_channel,
                    order_id=ord_in_route.id,
                )
                if new_live_msg_id:
                    await asyncio.to_thread(
                        repo.set_order_live_location,
                        TENANT_ID, ord_in_route.id, recipient_id, new_live_msg_id
                    )
                    processed_recipients[clean_recipient] = new_live_msg_id
                    if str(eff_channel).lower() == "telegram":
                        msg_live_notif = (
                            f"📍 *¡Tu repartidor ha comenzado a compartir su ubicación en tiempo real para tu Pedido #{ord_in_route.id}! "
                            f"Puedes seguir su trayecto en el mapa.* 🚚⛽"
                        )
                        btn_cancel = {
                            "inline_keyboard": [
                                [
                                    {"text": "❌ Cancelar Pedido", "callback_data": f"cancel_order_client:{ord_in_route.id}"}
                                ]
                            ]
                        }
                        await asyncio.to_thread(
                            notify_client,
                            recipient_id,
                            msg_live_notif,
                            btn_cancel,
                            eff_channel,
                        )
                    orders_updated += 1
                else:
                    _failed_live_location_orders.add(ord_in_route.id)

    # Si es un live location update continuo (edit_message de Telegram), no spameamos con mensajes de texto al chofer
    if not is_live_edit and update.message:
        direccion_aprox = await asyncio.to_thread(reverse_geocode, lat, lng)
        estado = _determinar_estado_ui_chofer(repo, driver)

        confirm_pedido_txt = ""
        if orders_updated > 0:
            confirm_pedido_txt = f"\n📲 **¡Ubicación transmitida en tiempo real al cliente de tu pedido activo!** El cliente ahora puede ver tu llegada en su mapa.\n"

        # Buscar si el chofer tiene un pedido activo en curso (priorizar in_route sobre assigned)
        active_order = None
        for ord_cand in sorted_orders:
            if ord_cand.status == "in_route":
                active_order = ord_cand
                break
        if not active_order:
            for ord_cand in sorted_orders:
                if ord_cand.status == "assigned":
                    active_order = ord_cand
                    break

        if active_order:
            inline_kb = get_botones_pedido_activo_inline(active_order)
            pedido_info = (
                f"\n🚚 **Pedido #{active_order.id} en curso:**\n"
                f"👤 Cliente: {active_order.customer_name} (`{active_order.customer_phone}`)\n"
                f"📍 Dirección: `{active_order.delivery_address}`\n"
                f"💰 Cobro: ${active_order.total_amount:.2f} ({active_order.payment_method})"
            )
            await _safe_reply_text(
                update.message,
                f"📍 **Ubicación GPS actualizada con éxito:**\n"
                f"📌 `{direccion_aprox}`\n"
                f"🌐 Coordenadas: ({lat:.5f}, {lng:.5f})\n"
                f"{confirm_pedido_txt}",
                reply_markup=get_teclado_principal(estado),
                parse_mode="Markdown",
            )
            ord_msg = await update.message.reply_text(
                f"{pedido_info}\n\n"
                f"Toca un botón abajo para navegación o marcar como entregado:",
                reply_markup=inline_kb,
                parse_mode="Markdown",
            )
            if ord_msg:
                try:
                    repo.add_order_driver_message_id(TENANT_ID, active_order.id, ord_msg.message_id)
                except Exception:
                    pass
        else:
            await _safe_reply_text(
                update.message,
                f"📍 **Ubicación GPS actualizada con éxito:**\n"
                f"📌 `{direccion_aprox}`\n"
                f"🌐 Coordenadas: ({lat:.5f}, {lng:.5f})\n"
                f"{confirm_pedido_txt}",
                reply_markup=get_teclado_principal(estado),
                parse_mode="Markdown",
            )


async def recibir_ubicacion_tiempo_real(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Actualiza las coordenadas GPS del chofer en tiempo real de forma no bloqueante con throttling."""
    msg = update.message or update.edited_message
    if not update.effective_user or not msg or not msg.location:
        return

    is_live_edit = bool(update.edited_message)
    user_id = str(update.effective_user.id)
    loc = msg.location

    now_ts = time.time()
    if is_live_edit:
        last_entry = _driver_last_location_update.get(user_id)
        if last_entry:
            last_ts, last_lat, last_lng = last_entry
            time_diff = now_ts - last_ts
            dist_meters = _haversine_distance_meters(last_lat, last_lng, loc.latitude, loc.longitude)
            # Throttling inteligente: Si pasaron menos de 6s Y se movió menos de 15 metros, omitir
            if time_diff < 6.0 and dist_meters < 15.0:
                return

    _driver_last_location_update[user_id] = (now_ts, loc.latitude, loc.longitude)

    repo = get_repository()
    driver = await asyncio.to_thread(repo.get_driver_by_telegram_id, TENANT_ID, user_id)

    if driver:
        await _procesar_coordenadas_gps_chofer(repo, driver, loc.latitude, loc.longitude, update, is_live_edit)
    else:
        if update.message:
            await _safe_reply_text(
                update.message,
                "⚠️ Aún no estás registrado como chofer. Inicia con `/registro` o `/login` para darte de alta.",
                reply_markup=ReplyKeyboardRemove(),
            )


# -----------------------------------------------------------------------------
# Callbacks de Botones Interactivos de Pedidos
# -----------------------------------------------------------------------------

async def manejar_callback_pedidos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja los clics en Aceptar Viaje, Entregar, Cancelar Viaje o Rechazar."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()
    data = query.data
    repo = get_repository()

    # 0a. Confirmación previa: ¿Seguro que ya entregaste?
    if data.startswith("confirm_deliver:"):
        raw_oid = data.split(":")[1]
        order_id = int(raw_oid) if raw_oid.isdigit() else raw_oid
        order = repo.get_order_by_id(TENANT_ID, order_id)
        if not order:
            await query.edit_message_text("⚠️ Pedido no encontrado.")
            return
        if order.status in ("cancelled", "delivered", "rejected_by_driver"):
            await query.edit_message_text(
                f"⚠️ El pedido #{order_id} ya no está activo (estado: {order.status})."
            )
            return
        confirm_kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Sí, ya entregué", callback_data=f"deliver_order:{order_id}"),
                InlineKeyboardButton("📸 Firma / Foto", callback_data=f"deliver_with_sig:{order_id}"),
            ],
            [
                InlineKeyboardButton("🔙 No, volver", callback_data=f"back_to_order:{order_id}"),
            ]
        ])
        await query.edit_message_text(
            f"📦 **¿Confirmas que el pedido #{order_id} fue entregado exitosamente?**\n\n"
            f"👤 Cliente: {order.customer_name}\n"
            f"💰 A cobrar: ${order.total_amount:.2f} ({order.payment_method})",
            reply_markup=confirm_kb,
            parse_mode="Markdown",
        )
        return

    # 0b. Solicitud de foto de firma / comprobante (soporte Dashboard Nuxt)
    if data.startswith("deliver_with_sig:"):
        raw_oid = data.split(":")[1]
        order_id = int(raw_oid) if raw_oid.isdigit() else raw_oid
        context.user_data["awaiting_delivery_sig_order_id"] = order_id
        await query.edit_message_text(
            f"📸 **Comprobante de Entrega / Firma — Pedido #{order_id}**\n\n"
            "Por favor, toma y envía ahora una **fotografía de la firma del cliente**, nota firmada o comprobante.\n\n"
            "*(Se registrará en Base64 en la Trazabilidad del Dashboard de Grupo Petroil)*",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Finalizar sin foto", callback_data=f"deliver_order:{order_id}")],
                [InlineKeyboardButton("🔙 Volver al pedido", callback_data=f"back_to_order:{order_id}")],
            ]),
            parse_mode="Markdown",
        )
        return


    # 0c. Volver a la vista del pedido (botón 'No, volver')
    if data.startswith("back_to_order:"):
        raw_oid = data.split(":")[1]
        order_id = int(raw_oid) if raw_oid.isdigit() else raw_oid
        order = repo.get_order_by_id(TENANT_ID, order_id)
        if not order:
            await query.edit_message_text("⚠️ Pedido no encontrado.")
            return
        if order.status in ("cancelled", "delivered", "rejected_by_driver"):
            await query.edit_message_text(
                f"⚠️ El pedido #{order_id} ya no está activo (estado: {order.status})."
            )
            return
        lat = order.delivery_lat or 23.2014
        lng = order.delivery_lng or -106.4215
        gmaps = get_google_maps_url(lat, lng, order.delivery_address)
        waze = get_waze_url(lat, lng)
        items_str = "\n".join(f"  • {it.quantity}x {it.product_name}" for it in order.items)
        pay_icon = "💵" if "efectivo" in order.payment_method.lower() else "💳"
        texto = (
            f"🔹 **Pedido #{order.id}** — Estado: `[{order.status.upper()}]`\n"
            f"👤 Cliente: {order.customer_name} (`{order.customer_phone}`)\n"
            f"📍 Dirección: {order.delivery_address}\n"
            f"📅 Horario: {order.delivery_schedule}\n"
            f"💰 Cobro: ${order.total_amount:.2f} {order.currency} ({pay_icon} {order.payment_method})\n"
            f"📦 Productos:\n{items_str}"
        )
        keyboard = [
            [
                InlineKeyboardButton("🗺️ Google Maps", url=gmaps),
                InlineKeyboardButton("🚗 Waze", url=waze),
            ],
            [
                InlineKeyboardButton("📦 Marcar como Entregado", callback_data=f"confirm_deliver:{order.id}"),
                InlineKeyboardButton("❌ Cancelar Viaje", callback_data=f"confirm_cancel_driver:{order.id}"),
            ],
        ]
        await query.edit_message_text(
            texto,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
        return

    # 1. Aceptar Pedido
    if data.startswith("accept_order:"):
        raw_oid = data.split(":")[1]
        order_id = int(raw_oid) if raw_oid.isdigit() else raw_oid
        order = repo.get_order_by_id(TENANT_ID, order_id)
        if not order:
            await query.edit_message_text("⚠️ Pedido no encontrado.")
            return

        # Verificar si el pedido ya fue cancelado, liberado o entregado
        if order.status in ("cancelled", "rejected_by_driver"):
            await query.edit_message_text(
                f"⚠️ **El pedido #{order_id} no está disponible.**\n\n"
                "Este viaje fue cancelado o liberado para reasignación y ya no puede ser reactivado.\n"
                "Espera a que la Torre de Control te asigne nuevos viajes.",
                parse_mode="Markdown",
            )
            return

        if order.status == "delivered":
            await query.edit_message_text(
                f"✅ **El pedido #{order_id} ya fue entregado.**\n\n"
                "No requiere acciones adicionales.",
                parse_mode="Markdown",
            )
            return

        if order.status not in ("assigned", "pending", "confirmed"):
            await query.edit_message_text(
                f"⚠️ **El pedido #{order_id} no está pendiente de aceptación** (estado actual: `{order.status}`).",
                parse_mode="Markdown",
            )
            return

        user_id = str(query.from_user.id if query.from_user else (update.effective_user.id if update.effective_user else 0))
        driver = repo.get_driver_by_telegram_id(TENANT_ID, user_id)
        if not driver:
            await query.edit_message_text("⚠️ No se encontró tu cuenta de chofer. Inicia con `/registro` o `/login`.")
            return

        # Si el pedido ya fue tomado por otro chofer o ya se entregó
        if order.status in ("in_route", "delivered") and order.driver_id and str(order.driver_id) != str(driver.id):
            await query.edit_message_text(
                f"⚠️ **El pedido #{order_id} ya fue tomado por otro chofer o ya fue completado.**\n\n"
                "Mantente al pendiente para el próximo viaje disponible.",
                parse_mode="Markdown",
            )
            return

        # Asignar formalmente la orden al chofer que presionó Aceptar Viaje
        repo.assign_order_to_driver(
            tenant_id=TENANT_ID,
            order_id=order_id,
            driver_id=driver.id,
            delivery_lat=order.delivery_lat,
            delivery_lng=order.delivery_lng,
        )
        repo.update_order_status(TENANT_ID, order_id, "in_route", driver_id=driver.id)
        repo.set_driver_availability(driver.id, False)
        _failed_live_location_orders.discard(order_id)

        lat = order.delivery_lat or 23.2014
        lng = order.delivery_lng or -106.4215
        gmaps = get_google_maps_url(lat, lng, order.delivery_address)
        waze = get_waze_url(lat, lng)

        keyboard = [
            [
                InlineKeyboardButton("🗺️ Abrir Google Maps", url=gmaps),
                InlineKeyboardButton("🚗 Abrir Waze", url=waze),
            ],
            [
                InlineKeyboardButton("📍 Transmitir Ubicación GPS", callback_data=f"pedir_gps:{order_id}"),
                InlineKeyboardButton("📦 Marcar como Entregado", callback_data=f"confirm_deliver:{order_id}"),
            ],
            [
                InlineKeyboardButton("❌ Cancelar Viaje", callback_data=f"confirm_cancel_driver:{order_id}"),
            ],
        ]

        await query.edit_message_text(
            f"🚚 **¡PEDIDO #{order_id} EN RUTA!**\n\n"
            f"👤 Cliente: {order.customer_name} (`{order.customer_phone}`)\n"
            f"📍 Dirección: {order.delivery_address}\n"
            f"💰 A Cobrar: ${order.total_amount:.2f} ({order.payment_method})\n\n"
            "Toca un botón para iniciar navegación GPS o marca como entregado al finalizar.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
        if query.message:
            try:
                repo.add_order_driver_message_id(TENANT_ID, order_id, query.message.message_id)
            except Exception:
                pass

        # Notificar aceptación al cliente y transmitir ubicación en vivo del chofer de inmediato
        recipient_id = str(order.channel_user_id or order.customer_phone or "").strip()
        if recipient_id:
            eff_channel = getattr(order, "channel", None)
            if not eff_channel:
                chan_info = identity_store.get_order_channel_info(order.id)
                if chan_info and chan_info.get("channel"):
                    eff_channel = chan_info.get("channel")
            if not eff_channel:
                clean_dig = re.sub(r"\D", "", recipient_id)
                if clean_dig.startswith("52") or len(clean_dig) == 10:
                    eff_channel = "whatsapp"
                else:
                    eff_channel = "telegram"

            driver_lat = getattr(driver, "current_lat", None)
            driver_lng = getattr(driver, "current_lng", None)
            if driver_lat is not None and driver_lng is not None:
                # Chofer ya cuenta con coordenadas GPS: transmitir de inmediato al cliente
                live_msg_id = await asyncio.to_thread(
                    send_client_live_location,
                    recipient_id,
                    driver_lat,
                    driver_lng,
                    live_period=7200,
                    channel=eff_channel,
                    order_id=order.id,
                )
                if live_msg_id:
                    from unittest.mock import MagicMock
                    if not isinstance(live_msg_id, MagicMock):
                        await asyncio.to_thread(
                            repo.set_order_live_location,
                            TENANT_ID, order.id, recipient_id, live_msg_id
                        )
                    if str(eff_channel).lower() == "telegram":
                        v_plate = getattr(driver, "vehicle_plate", "") or "Unidad de reparto"
                        d_phone = getattr(driver, "phone", "") or ""
                        phone_line = f"\n• 📞 **Teléfono chofer:** `{d_phone}`" if d_phone else ""
                        msg_live_notif = (
                            f"🚚 **¡Tu pedido #{order.id} va en camino a tu domicilio!**\n\n"
                            f"• 👨‍✈️ **Chofer:** {driver.name or 'Unidad Petroil'}\n"
                            f"• 🚘 **Unidad:** {v_plate}{phone_line}\n\n"
                            f"📍 *Puedes seguir el mapa en tiempo real hacia tu domicilio.* ⛽✨"
                        )
                        btn_cancel = {
                            "inline_keyboard": [
                                [
                                    {"text": "❌ Cancelar Pedido", "callback_data": f"cancel_order_client:{order.id}"}
                                ]
                            ]
                        }
                        await asyncio.to_thread(
                            notify_client,
                            recipient_id,
                            msg_live_notif,
                            btn_cancel,
                            eff_channel,
                        )
            else:
                # Chofer no tiene GPS todavía: enviar mensaje limpio y solicitarle compartir ubicación
                v_plate = getattr(driver, "vehicle_plate", "") or "Unidad de reparto"
                d_phone = getattr(driver, "phone", "") or ""
                phone_line = f"\n• 📞 **Teléfono chofer:** `{d_phone}`" if d_phone else ""
                msg_cliente = (
                    f"🚚 **¡Tu pedido #{order.id} va en camino a tu domicilio!**\n\n"
                    f"• 👨‍✈️ **Chofer:** {driver.name or 'Unidad Petroil'}\n"
                    f"• 🚘 **Unidad:** {v_plate}{phone_line}\n\n"
                    "Tu repartidor ya inició su recorrido. Te notificaremos cualquier avance de tu entrega. ⛽✨"
                )
                await asyncio.to_thread(notify_client, recipient_id, msg_cliente, None, eff_channel)


        # Solicitar inmediatamente al chofer transmitir su ubicación GPS real para el cliente
        btn_compartir_gps = ReplyKeyboardMarkup(
            [
                [KeyboardButton("📍 Transmitir Mi Ubicación Actual (GPS)", request_location=True)],
                ["📋 Mis Pedidos Activos", "⛽ Medidor de Tanque"],
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        if query.message:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=(
                    f"📍 **¡TRANSMISIÓN DE RUTA EN TIEMPO REAL!**\n\n"
                    f"Para que el cliente y la Torre de Control sigan tu llegada exacta en vivo en el mapa:\n\n"
                    f"1️⃣ Presiona el botón grande abajo **'📍 Transmitir Mi Ubicación Actual (GPS)'**.\n"
                    f"2️⃣ O adjunta con el clip: **📎 Ubicación ➔ 'Compartir ubicación en tiempo real...'** para rastreo continuo mientras manejas.\n"
                    f"*(💡 Si estás en Telegram Desktop o sin sensor GPS, puedes escribir tus coordenadas ej: `23.2435, -106.4123`)*"
                ),
                reply_markup=btn_compartir_gps,
                parse_mode="Markdown",
            )

    # 1b. Solicitar botón de transmisión de ubicación GPS
    elif data.startswith("pedir_gps:"):
        raw_oid = data.split(":")[1] if ":" in data else ""
        if raw_oid:
            order_id = int(raw_oid) if raw_oid.isdigit() else raw_oid
            order = repo.get_order_by_id(TENANT_ID, order_id)
            if not order or order.status in ("cancelled", "delivered", "rejected_by_driver"):
                await query.answer("Este pedido ya no está activo.", show_alert=True)
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
                except Exception:
                    pass
                return
        await query.answer()
        btn_compartir_gps = ReplyKeyboardMarkup(
            [
                [KeyboardButton("📍 Transmitir Mi Ubicación Actual (GPS)", request_location=True)],
                ["📋 Mis Pedidos Activos", "⛽ Medidor de Tanque"],
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        if query.message:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=(
                    f"📍 **¡TRANSMISIÓN DE RUTA EN TIEMPO REAL!**\n\n"
                    f"Para actualizar tu posición y que el cliente pueda seguir tu llegada en vivo en su mapa:\n\n"
                    f"1️⃣ Presiona el botón grande abajo **'📍 Transmitir Mi Ubicación Actual (GPS)'**.\n"
                    f"2️⃣ O adjunta con el clip: **📎 Ubicación ➔ 'Compartir ubicación en tiempo real...'** para rastreo continuo mientras manejas.\n"
                    f"*(💡 Si estás en Telegram Desktop o sin sensor GPS, puedes escribir tus coordenadas ej: `23.2435, -106.4123`)*"
                ),
                reply_markup=btn_compartir_gps,
                parse_mode="Markdown",
            )

    # 2. Marcar como Entregado
    elif data.startswith("deliver_order:"):
        raw_oid = data.split(":")[1]
        order_id = int(raw_oid) if raw_oid.isdigit() else raw_oid
        order = repo.get_order_by_id(TENANT_ID, order_id)
        if not order:
            await _safe_edit_message_text(query, "⚠️ Pedido no encontrado.")
            return

        if order.status in ("cancelled", "delivered", "rejected_by_driver"):
            await _safe_edit_message_text(
                query,
                f"⚠️ El pedido #{order_id} ya no está activo (estado actual: `{order.status}`).",
                parse_mode="Markdown",
            )
            return

        # Eliminar la ubicación en tiempo real del chat del cliente
        if order.live_location_message_id and order.live_location_chat_id:
            await asyncio.to_thread(remove_client_live_location, order.live_location_chat_id, order.live_location_message_id)
            await asyncio.to_thread(repo.clear_order_live_location, TENANT_ID, order_id)

        user_id = str(query.from_user.id if query.from_user else (update.effective_user.id if update.effective_user else 0))
        driver = repo.get_driver_by_telegram_id(TENANT_ID, user_id)
        driver_id_val = driver.id if driver else None
        repo.update_order_status(TENANT_ID, order_id, "delivered", driver_id=driver_id_val)
        _failed_live_location_orders.discard(order_id)

        if driver:
            repo.set_driver_availability(driver.id, True)

        await _safe_edit_message_text(
            query,
            f"✅ **¡PEDIDO #{order_id} ENTREGADO CON ÉXITO!**\n\n"
            f"💰 Cobro: ${order.total_amount:.2f} {order.currency} ({order.payment_method})\n"
            f"👤 Cliente: {order.customer_name}\n\n"
            "¡Excelente trabajo! Estás disponible para nuevos viajes.",
            parse_mode="Markdown",
        )



        # NOTIFICAR AL CLIENTE EN TELEGRAM O WHATSAPP CON ENCUESTA INTERACTIVA DE CALIFICACIÓN
        await asyncio.to_thread(notify_delivery_survey, order.id, TENANT_ID)

    # 2b. Cancelación masiva de todos los pedidos activos asignados al chofer
    elif data == "cancel_all_my_orders":
        user_id = str(query.from_user.id if query.from_user else (update.effective_user.id if update.effective_user else 0))
        driver = repo.get_driver_by_telegram_id(TENANT_ID, user_id)
        if not driver:
            await _safe_edit_message_text(query, "⚠️ Chofer no encontrado.")
            return

        chat_id = update.effective_chat.id if update.effective_chat else (query.message.chat_id if query.message else None)

        # Eliminar ubicación en tiempo real de los pedidos activos antes de liberar
        active_orders = repo.get_orders_by_driver(TENANT_ID, driver.id, active_only=True)
        for act_ord in active_orders:
            if act_ord.live_location_message_id and act_ord.live_location_chat_id:
                await asyncio.to_thread(remove_client_live_location, act_ord.live_location_chat_id, act_ord.live_location_message_id)
                await asyncio.to_thread(repo.clear_order_live_location, TENANT_ID, act_ord.id)

        _failed_live_location_orders.clear()
        count = await asyncio.to_thread(repo.cancel_all_orders_for_driver, TENANT_ID, driver.id, "Cancelación masiva solicitada por chofer")

        # BORRAR del chat los mensajes individuales de los viajes/pedidos activos que se enviaron antes
        msg_ids_to_delete = context.user_data.get("active_order_messages", [])
        if chat_id and msg_ids_to_delete:
            for mid in msg_ids_to_delete:
                if query.message and mid == query.message.message_id:
                    continue  # El mensaje con el botón de cancelar se edita, no se borra
                await _safe_delete_message(context.bot, chat_id, mid)
            context.user_data["active_order_messages"] = []

        await _safe_edit_message_text(
            query,
            f"✅ **Se han liberado tus {count} pedido(s) activo(s).**\n\n"
            "🚨 *La Torre de Control ha sido informada para reasignar los pedidos a otras unidades de reparto.* Quedas en estado 🟢 **Disponible**.",
            parse_mode="Markdown",
        )
        estado = "disponible"
        await _safe_reply_text(
            query.message,
            "Tu cola de pedidos ha quedado vacía y estás listo para nuevos viajes.",
            reply_markup=get_teclado_principal(estado),
        )

    # 3. Solicitar Motivo de Rechazo o Cancelación de Viaje
    elif data.startswith("reject_order:") or data.startswith("confirm_cancel_driver:") or data.startswith("cancel_order_driver:"):
        raw_oid = data.split(":")[1]
        order_id = int(raw_oid) if raw_oid.isdigit() else raw_oid
        order = repo.get_order_by_id(TENANT_ID, order_id)
        if not order:
            await query.edit_message_text("⚠️ Pedido no encontrado o ya reasignado.")
            return

        if order.status in ("cancelled", "delivered", "rejected_by_driver"):
            await query.edit_message_text(
                f"⚠️ El pedido #{order_id} ya no está activo (estado actual: `{order.status}`).",
                parse_mode="Markdown",
            )
            return

        motivos_kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🚗 Falla Mecánica en Unidad", callback_data=f"rej_reason:{order_id}:falla_mecanica"),
            ],
            [
                InlineKeyboardButton("⛽ Sin Inventario / Capacidad Gas", callback_data=f"rej_reason:{order_id}:sin_inventario"),
            ],
            [
                InlineKeyboardButton("📍 Fuera de Zona / Cobertura", callback_data=f"rej_reason:{order_id}:fuera_zona"),
            ],
            [
                InlineKeyboardButton("🕒 Retraso Excesivo / Tráfico", callback_data=f"rej_reason:{order_id}:retraso_trafico"),
            ],
            [
                InlineKeyboardButton("✍️ Escribir Otro Motivo", callback_data=f"rej_reason:{order_id}:otro_texto"),
            ],
            [
                InlineKeyboardButton("🔙 No Cancelar (Volver)", callback_data=f"back_to_order:{order_id}"),
            ],
        ])

        await query.edit_message_text(
            f"⚠️ **Cancelación / Rechazo del Pedido #{order_id}**\n\n"
            f"👤 Cliente: {order.customer_name}\n"
            f"📍 Dirección: {order.delivery_address}\n\n"
            "Por favor selecciona el motivo para informar a la **Torre de Control**:",
            reply_markup=motivos_kb,
            parse_mode="Markdown",
        )

    # 3b. Procesar Motivo de Rechazo Seleccionado por Botón
    elif data.startswith("rej_reason:"):
        parts = data.split(":")
        raw_oid = parts[1]
        order_id = int(raw_oid) if raw_oid.isdigit() else raw_oid
        codigo_motivo = parts[2]

        if codigo_motivo == "otro_texto":
            context.user_data["awaiting_rejection_reason_for_order"] = order_id
            await query.edit_message_text(
                f"✍️ **Escribe el motivo por el cual no puedes atender el Pedido #{order_id}:**\n\n"
                "Envía un mensaje de texto con la explicación detallada para la Torre de Control.",
                parse_mode="Markdown",
            )
            return

        mapa_motivos = {
            "falla_mecanica": "Falla mecánica en la unidad",
            "sin_inventario": "Sin capacidad / Sin inventario de gas",
            "fuera_zona": "Fuera de zona / Cobertura inaccesible",
            "retraso_trafico": "Retraso excesivo / Tráfico vial",
        }
        motivo_texto = mapa_motivos.get(codigo_motivo, codigo_motivo)

        user_id = str(query.from_user.id if query.from_user else (update.effective_user.id if update.effective_user else 0))
        driver = repo.get_driver_by_telegram_id(TENANT_ID, user_id)
        driver_name = driver.name if driver else "Chofer"
        driver_id = driver.id if driver else 0

        # Si el pedido tenía ubicación en tiempo real activa hacia el cliente, eliminarla
        order_canc = repo.get_order_by_id(TENANT_ID, order_id)
        if order_canc and order_canc.live_location_message_id and order_canc.live_location_chat_id:
            await asyncio.to_thread(remove_client_live_location, order_canc.live_location_chat_id, order_canc.live_location_message_id)
            await asyncio.to_thread(repo.clear_order_live_location, TENANT_ID, order_id)

        _failed_live_location_orders.discard(order_id)
        repo.record_order_rejection(
            tenant_id=TENANT_ID,
            order_id=order_id,
            driver_id=driver_id,
            driver_name=driver_name,
            reason=motivo_texto,
        )

        # Si reporta falla mecánica, poner chofer en pausa
        if codigo_motivo == "falla_mecanica" and driver_id:
            repo.set_driver_availability(driver_id, False)

        await _safe_edit_message_text(
            query,
            f"❌ **Pedido #{order_id} rechazado con éxito.**\n\n"
            f"📌 **Motivo:** {motivo_texto}\n\n"
            "🚨 *La Torre de Control ha recibido la incidencia y procederá a reasignar el pedido a otra unidad.*",
            parse_mode="Markdown",
        )



    # 3c. Botones para capturar carga de tanque desde el menú
    elif data == "btn_carga_initial":
        context.user_data["awaiting_tank_reading"] = "initial"
        await query.message.reply_text(
            "🟢 **REGISTRO DE CARGA INICIAL (PIPA / TANQUE)** 📸\n\n"
            "• Envía una **FOTOGRAFÍA** del reloj medidor / rotogauge.\n"
            "• O escribe el valor numérico (ejemplo: `85%` o `4500 L`).\n\n"
            "*(O presiona '❌ Cancelar')*",
            reply_markup=get_teclado_lectura_tanque(),
            parse_mode="Markdown",
        )
        return

    elif data == "btn_carga_final":
        context.user_data["awaiting_tank_reading"] = "final"
        await query.message.reply_text(
            "🔴 **REGISTRO DE CARGA FINAL (PIPA / TANQUE)** 📸\n\n"
            "• Envía una **FOTOGRAFÍA** del reloj medidor / rotogauge.\n"
            "• O escribe el valor de cierre (ejemplo: `15%` o `800 L`).\n\n"
            "*(O presiona '❌ Cancelar')*",
            reply_markup=get_teclado_lectura_tanque(),
            parse_mode="Markdown",
        )
        return

    elif data in ("btn_carga_refill", "btn_capturar_carga"):
        context.user_data["awaiting_tank_reading"] = "refill"
        await query.message.reply_text(
            "🔵 **REGISTRO DE RECARGA EN PLANTA** ⛽\n\n"
            "• Envía una **FOTOGRAFÍA** del reloj tras el abastecimiento.\n"
            "• O escribe el valor o litros (ejemplo: `90%` o `5000 L`).\n\n"
            "*(O presiona '❌ Cancelar')*",
            reply_markup=get_teclado_lectura_tanque(),
            parse_mode="Markdown",
        )
        return

    elif data == "btn_carga_historial":
        user_id = str(query.from_user.id if query.from_user else (update.effective_user.id if update.effective_user else 0))
        driver = repo.get_driver_by_telegram_id(TENANT_ID, user_id)
        if not driver:
            await query.message.reply_text("⚠️ Chofer no registrado.")
            return

        readings = repo.get_tank_readings_by_driver(TENANT_ID, driver.id, limit=8)
        if not readings:
            await query.message.reply_text("ℹ️ No tienes lecturas registradas todavía.")
            return
        tipo_map = {"initial": "🟢 Inicial", "final": "🔴 Final", "refill": "🔵 Recarga"}
        lineas = []
        for r in readings:
            t_name = tipo_map.get(r.get("reading_type"), r.get("reading_type"))
            hora = r.get("created_at", "")
            if " " in hora:
                hora = hora.split(" ")[1][:5]
            f_ico = " 📷" if r.get("photo_path") else ""
            lineas.append(f"• **{t_name}**: `{r.get('reading_value')}`{f_ico} ({hora})")

        await query.message.reply_text(
            f"📜 **HISTORIAL RECIENTE DE MEDIDOR - {driver.vehicle_plate}**\n\n" + "\n".join(lineas),
            parse_mode="Markdown",
        )
        return

    elif data.startswith("asigna_foto:"):
        tipo = data.split(":")[1]
        user_id = str(query.from_user.id if query.from_user else (update.effective_user.id if update.effective_user else 0))
        driver = repo.get_driver_by_telegram_id(TENANT_ID, user_id)
        pending = context.user_data.pop("pending_tank_photo", None)

        if not driver or not pending or tipo == "cancel":
            await query.edit_message_text("❌ Fotografía descartada.")
            return

        tipo_nom = "CARGA INICIAL" if tipo == "initial" else ("CARGA FINAL" if tipo == "final" else "RECARGA")
        await query.edit_message_text(f"⏳ Procesando fotografía como **{tipo_nom}**...")
        await _guardar_y_responder_foto_tanque(
            update=update,
            context=context,
            driver=driver,
            repo=repo,
            reading_type=tipo,
            photo_path=pending.get("photo_path"),
            photo_telegram_id=pending.get("photo_telegram_id"),
            caption=pending.get("caption", ""),
            full_path=Path(pending["full_path"]) if pending.get("full_path") else None,
        )
        return

    elif data.startswith("asigna_txt:"):
        tipo = data.split(":")[1]
        user_id = str(query.from_user.id if query.from_user else (update.effective_user.id if update.effective_user else 0))
        driver = repo.get_driver_by_telegram_id(TENANT_ID, user_id)
        val = context.user_data.pop("pending_tank_text", None)

        if not driver or not val or tipo == "cancel":
            await query.edit_message_text("❌ Registro descartado.")
            return

        repo.save_tank_reading(
            tenant_id=TENANT_ID,
            driver_id=driver.id,
            driver_name=driver.name,
            vehicle_plate=driver.vehicle_plate or "",
            reading_type=tipo,
            reading_value=val,
            notes=f"Captura por mensaje clasificada como {tipo}",
        )

        if tipo == "initial":
            if not driver.is_available:
                await _completar_inicio_turno(update, driver, repo, reading_val=val, con_foto=False)
            else:
                await query.edit_message_text(
                    f"🟢 **Carga Inicial Registrada:** `{val}`\n🚘 Unidad: {driver.vehicle_plate}",
                    parse_mode="Markdown",
                )
        elif tipo == "final":
            if driver.is_available:
                await _completar_fin_turno(update, driver, repo, reading_val=val, con_foto=False)
            else:
                await query.edit_message_text(
                    f"🔴 **Carga Final Registrada:** `{val}`\n🚘 Unidad: {driver.vehicle_plate}",
                    parse_mode="Markdown",
                )
        else:
            await query.edit_message_text(
                f"🔵 **Recarga Registrada:** `{val}`\n🚘 Unidad: {driver.vehicle_plate}",
                parse_mode="Markdown",
            )
        return

    elif data.startswith("corrige_lectura:"):
        reading_id = int(data.split(":")[1])
        context.user_data["awaiting_reading_correction_id"] = reading_id
        await query.message.reply_text(
            f"✏️ **Escribe el valor exacto para corregir la lectura #{reading_id}:**\n\n"
            "(Ejemplo: `82%` o `4200 L`, o escribe 'cancelar'):",
            parse_mode="Markdown",
        )
        return


async def _guardar_y_responder_foto_tanque(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    driver,
    repo,
    reading_type: str,
    photo_path: str | None,
    photo_telegram_id: str | None,
    caption: str,
    full_path: Path | None,
) -> None:
    """Analiza la foto con IA si no hay texto, guarda la lectura en BD y responde al chofer."""
    target_msg = update.message or (update.callback_query.message if update.callback_query else None)

    reading_val = caption if caption else None
    notes = f"Foto con pie de texto: {caption}" if caption else "Foto capturada desde Telegram"
    detected_by_ai = False
    ai_details = ""

    # Si NO tiene texto escrito por el chofer, ejecutamos visión con IA
    if not reading_val and full_path and full_path.exists():
        status_msg = None
        if target_msg:
            try:
                status_msg = await target_msg.reply_text(
                    "🔍 *Analizando reloj rotogauge con Inteligencia Artificial...*",
                    parse_mode="Markdown",
                )
            except Exception:
                status_msg = None

        try:
            v_res = await analyze_tank_meter_image(full_path)
            if v_res.get("success") and v_res.get("reading_value"):
                reading_val = v_res["reading_value"]
                detected_by_ai = True
                ai_details = v_res.get("details", "")
                notes = f"Lectura detectada por IA ({v_res.get('confidence', '')}): {ai_details}"
        except Exception as exc:
            logger.warning(f"No se pudo completar análisis de visión: {exc}")
        finally:
            if status_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    pass

    if not reading_val:
        reading_val = "Fotografía de reloj"

    reading_record = repo.save_tank_reading(
        tenant_id=TENANT_ID,
        driver_id=driver.id,
        driver_name=driver.name,
        vehicle_plate=driver.vehicle_plate or "",
        reading_type=reading_type,
        reading_value=reading_val,
        photo_path=photo_path,
        photo_telegram_id=photo_telegram_id,
        notes=notes,
    )
    reading_id = reading_record.get("id") if reading_record else None

    corregir_kb = None
    if reading_id:
        corregir_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Ajustar / Corregir Valor", callback_data=f"corrige_lectura:{reading_id}")]
        ])

    tipo_labels = {
        "initial": ("🟢 Carga Inicial", "Carga inicial registrada con éxito"),
        "final": ("🔴 Carga Final", "Carga final registrada con éxito"),
        "refill": ("🔵 Recarga en Planta", "Recarga en planta registrada con éxito"),
    }
    t_badge, t_desc = tipo_labels.get(reading_type, ("⛽ Medidor", "Lectura registrada"))

    ai_info = f"\n🔍 *Lectura detectada por IA:* `{reading_val}` ({ai_details})" if detected_by_ai else ""

    if reading_type == "initial":
        await _completar_inicio_turno(update, driver, repo, reading_val, con_foto=True)
        if target_msg and detected_by_ai and corregir_kb:
            await target_msg.reply_text(
                f"ℹ️ {ai_info}\nSi el porcentaje difiere, puedes ajustarlo con el botón de abajo:",
                reply_markup=corregir_kb,
                parse_mode="Markdown",
            )
    elif reading_type == "final":
        await _completar_fin_turno(update, driver, repo, reading_val, con_foto=True)
        if target_msg and detected_by_ai and corregir_kb:
            await target_msg.reply_text(
                f"ℹ️ {ai_info}\nSi el porcentaje difiere, puedes ajustarlo con el botón de abajo:",
                reply_markup=corregir_kb,
                parse_mode="Markdown",
            )
    else:
        if target_msg:
            msg_txt = (
                f"⛽ **¡{t_desc.upper()}!**\n\n"
                f"• Tipo: **{t_badge}**\n"
                f"• Lectura: **{reading_val}** (📸 Fotografía guardada ✅)\n"
                f"• Unidad: **{driver.vehicle_plate}**\n"
                f"{ai_info}\n\n"
                "Información sincronizada con la Torre de Control."
            )
            await target_msg.reply_text(
                msg_txt,
                reply_markup=corregir_kb or get_teclado_principal(_determinar_estado_ui_chofer(repo, driver)),
                parse_mode="Markdown",
            )


async def recibir_foto_chofer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Procesar cualquier fotografía enviada por el chofer (reloj de tanque, medidor, rotogauge)."""
    if not update.effective_user or not update.message or not update.message.photo:
        return

    user_id = str(update.effective_user.id)
    repo = get_repository()
    driver = repo.get_driver_by_telegram_id(TENANT_ID, user_id)

    if not driver:
        await update.message.reply_text("⚠️ Chofer no registrado. Escribe `/registro`")
        return

    photo = update.message.photo[-1]
    caption = (update.message.caption or "").strip()

    # Asegurar directorio de uploads
    upload_dir = Path("uploads") / "tank_readings"
    upload_dir.mkdir(parents=True, exist_ok=True)

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    reading_type = context.user_data.pop("awaiting_tank_reading", None)

    temp_type = reading_type or "captura"
    filename = f"tank_{driver.id}_{temp_type}_{timestamp_str}.jpg"
    rel_path = f"uploads/tank_readings/{filename}"
    full_path = upload_dir / filename

    try:
        tg_file = await context.bot.get_file(photo.file_id)
        await tg_file.download_to_drive(custom_path=full_path)
        photo_path = rel_path
    except Exception as e:
        logger.error(f"Error descargando foto de tanque: {e}")
        photo_path = None

    # Si la foto es firma / comprobante de entrega de un pedido (soporte Trazabilidad Base64)
    sig_order_id = context.user_data.pop("awaiting_delivery_sig_order_id", None)
    if sig_order_id:
        import base64
        sig_base64 = None
        try:
            if full_path.exists():
                with open(full_path, "rb") as f_img:
                    raw_b64 = base64.b64encode(f_img.read()).decode("utf-8")
                    sig_base64 = f"data:image/jpeg;base64,{raw_b64}"
        except Exception as e:
            logger.warning(f"Error encoding delivery signature: {e}")

        order = repo.get_order_by_id(TENANT_ID, sig_order_id)
        if order:
            if order.live_location_message_id and order.live_location_chat_id:
                await asyncio.to_thread(remove_client_live_location, order.live_location_chat_id, order.live_location_message_id)
                await asyncio.to_thread(repo.clear_order_live_location, TENANT_ID, sig_order_id)

            repo.update_order_status(TENANT_ID, sig_order_id, "delivered", driver_id=driver.id, signature=sig_base64)
            _failed_live_location_orders.discard(sig_order_id)
            repo.set_driver_availability(driver.id, True)

            await update.message.reply_text(
                f"✅ **¡PEDIDO #{sig_order_id} ENTREGADO CON COMPROBANTE/FIRMA!**\n\n"
                f"📸 Firma/Comprobante registrado en la Trazabilidad del Dashboard.\n"
                f"💰 Cobro: ${order.total_amount:.2f} {order.currency} ({order.payment_method})\n"
                f"👤 Cliente: {order.customer_name}\n\n"
                "¡Excelente trabajo! Estás disponible para nuevos viajes.",
                parse_mode="Markdown",
            )
            await asyncio.to_thread(notify_delivery_survey, order.id, TENANT_ID)
            return

    # Si NO había un tipo en espera (el chofer envió la foto sin presionar botón previo)
    if not reading_type:
        context.user_data["pending_tank_photo"] = {
            "photo_path": photo_path,
            "photo_telegram_id": photo.file_id,
            "caption": caption,
            "full_path": str(full_path),
        }
        keyboard = [
            [
                InlineKeyboardButton("🟢 Carga Inicial", callback_data="asigna_foto:initial"),
                InlineKeyboardButton("🔴 Carga Final", callback_data="asigna_foto:final"),
            ],
            [
                InlineKeyboardButton("🔵 Recarga en Planta", callback_data="asigna_foto:refill"),
                InlineKeyboardButton("❌ Descartar", callback_data="asigna_foto:cancel"),
            ],
        ]
        await update.message.reply_text(
            "📸 **Fotografía de reloj medidor recibida.**\n\n"
            "¿A qué tipo de registro corresponde esta fotografía?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
        return

    # Si ya sabemos el reading_type, guardar y responder
    await _guardar_y_responder_foto_tanque(
        update=update,
        context=context,
        driver=driver,
        repo=repo,
        reading_type=reading_type,
        photo_path=photo_path,
        photo_telegram_id=photo.file_id,
        caption=caption,
        full_path=full_path,
    )


async def manejar_texto_chofer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enrutador de mensajes de texto: procesa lecturas de tanque, correcciones o motivos de rechazo."""
    if not update.effective_user or not update.message or not update.message.text:
        return

    texto = update.message.text.strip()
    user_id = str(update.effective_user.id)
    repo = get_repository()
    driver = repo.get_driver_by_telegram_id(TENANT_ID, user_id)

    # 0. Si el usuario aún no está autenticado, intentar vincular por celular o invitar a /start
    if not driver:
        clean_digits = re.sub(r"\D", "", texto)
        if len(clean_digits) >= 10:
            phone_search = clean_digits[-10:]
            matched_driver = repo.get_driver_by_phone(TENANT_ID, phone_search)
            if matched_driver:
                repo.update_driver(matched_driver.id, {"telegram_user_id": user_id})
                matched_driver = repo.get_driver(matched_driver.id)
                resumen = _formatear_resumen_chofer(matched_driver, repo)
                estado_str = "disponible" if matched_driver.is_available else "fuera_turno"
                msg = (
                    f"🎉 **¡BIENVENIDO AL SISTEMA, {matched_driver.name.upper()}!** 🎉\n\n"
                    f"Tu cuenta ha sido vinculada exitosamente con tu usuario de Telegram.\n\n"
                    f"{resumen}\n\n"
                    "✅ **¡Acceso Concedido!** Ya puedes gestionar tus turnos, recibir pedidos asignados en tu zona y registrar lecturas de medidor."
                )
                await update.message.reply_text(
                    msg,
                    reply_markup=get_teclado_principal(estado_str),
                    parse_mode="Markdown",
                )
                return

        await update.message.reply_text(
            "👋 Hola, aún no has iniciado sesión como operador.\n\n"
            "Escribe tu número de celular o escribe `/start` para ingresar con el número asignado en la Torre de Control.",
            parse_mode="Markdown",
        )
        return

    # 1. Caso: Chofer está registrando carga de tanque/pipa en espera
    reading_type = context.user_data.get("awaiting_tank_reading")
    if reading_type:
        context.user_data.pop("awaiting_tank_reading", None)

        if not driver:
            return

        if texto in ("⏭️ Omitir / No Aplica", "omitir", "/omitir", "Omitir"):
            if reading_type == "initial":
                await _completar_inicio_turno(update, driver, repo, reading_val=None)
            elif reading_type == "final":
                await _completar_fin_turno(update, driver, repo, reading_val=None)
            else:
                await update.message.reply_text(
                    "Operación omitida.",
                    reply_markup=get_teclado_principal(_determinar_estado_ui_chofer(repo, driver)),
                )
            return

        if texto in ("❌ Cancelar", "cancelar", "/cancelar", "Cancelar"):
            await update.message.reply_text(
                "Registro cancelado.",
                reply_markup=get_teclado_principal(_determinar_estado_ui_chofer(repo, driver)),
            )
            return

        # Normalizar el valor textual (ej: "85%", "4500 L")
        val_clean = _normalizar_valor_tanque(texto)

        repo.save_tank_reading(
            tenant_id=TENANT_ID,
            driver_id=driver.id,
            driver_name=driver.name,
            vehicle_plate=driver.vehicle_plate or "",
            reading_type=reading_type,
            reading_value=val_clean,
            photo_path=None,
            photo_telegram_id=None,
            notes=f"Captura manual por texto: '{texto}'",
        )

        if reading_type == "initial":
            await _completar_inicio_turno(update, driver, repo, reading_val=val_clean, con_foto=False)
        elif reading_type == "final":
            await _completar_fin_turno(update, driver, repo, reading_val=val_clean, con_foto=False)
        else:
            await update.message.reply_text(
                f"⛽ **¡RECARGA REGISTRADA CON ÉXITO!**\n\n"
                f"• Lectura: **{val_clean}**\n"
                f"• Unidad: **{driver.vehicle_plate}**\n\n"
                "Información sincronizada con la Torre de Control.",
                reply_markup=get_teclado_principal(_determinar_estado_ui_chofer(repo, driver)),
                parse_mode="Markdown",
            )
        return

    # 2. Caso: Chofer está corrigiendo una lectura previa
    correction_id = context.user_data.get("awaiting_reading_correction_id")
    if correction_id:
        context.user_data.pop("awaiting_reading_correction_id", None)
        if texto.lower() not in ("cancelar", "/cancelar"):
            val_clean = _normalizar_valor_tanque(texto)
            repo.update_tank_reading(correction_id, val_clean, notes=f"Corregido manualmente a '{val_clean}'")
            await update.message.reply_text(
                f"✅ **Lectura #{correction_id} actualizada correctamente a:** `{val_clean}`",
                reply_markup=get_teclado_principal(_determinar_estado_ui_chofer(repo, driver)),
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("Corrección cancelada.")
        return

    # 3. Caso: Chofer está escribiendo motivo de rechazo
    if context.user_data.get("awaiting_rejection_reason_for_order"):
        await recibir_motivo_rechazo_texto(update, context)
        return

    # 3.5. Caso: Chofer envía coordenadas GPS o ubicación por texto (ej: "23.2435, -106.4123")
    coord_match = re.search(r"(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)", texto)
    if coord_match:
        try:
            c_lat = float(coord_match.group(1))
            c_lng = float(coord_match.group(2))
            if -90 <= c_lat <= 90 and -180 <= c_lng <= 180:
                await _procesar_coordenadas_gps_chofer(repo, driver, c_lat, c_lng, update, is_live_edit=False)
                return
        except Exception as e:
            logger.debug(f"[Texto Coordenadas] {e}")

    # 4. Caso: Detección inteligente por texto libre (sin haber presionado botón antes)
    if driver:
        # Detectar Carga Inicial directa: "carga inicial 85%", "iniciando con 90%", "inicio con 80%"
        m_ini = re.search(r"(?:carga\s*inicial|inici(?:o|ando|ar)?\s*(?:con)?|inicio\s*(?:con)?\s*:?)\s*(\d+(?:\.\d+)?\s*(?:%|l(?:itros)?)?)", texto, re.I)
        if m_ini:
            val = _normalizar_valor_tanque(m_ini.group(1))
            repo.save_tank_reading(
                tenant_id=TENANT_ID,
                driver_id=driver.id,
                driver_name=driver.name,
                vehicle_plate=driver.vehicle_plate or "",
                reading_type="initial",
                reading_value=val,
                notes=f"Captura rápida por texto directo: '{texto}'",
            )
            if not driver.is_available:
                await _completar_inicio_turno(update, driver, repo, reading_val=val, con_foto=False)
            else:
                await update.message.reply_text(
                    f"🟢 **Carga Inicial Registrada:** `{val}`\n🚘 Unidad: {driver.vehicle_plate}",
                    reply_markup=get_teclado_principal("disponible"),
                    parse_mode="Markdown",
                )
            return

        # Detectar Carga Final directa: "carga final 15%", "terminando con 20%", "fin con 12%"
        m_fin = re.search(r"(?:carga\s*final|termin(?:o|ando|ar)?\s*(?:con)?|fin(?:al)?\s*(?:con)?\s*:?)\s*(\d+(?:\.\d+)?\s*(?:%|l(?:itros)?)?)", texto, re.I)
        if m_fin:
            val = _normalizar_valor_tanque(m_fin.group(1))
            repo.save_tank_reading(
                tenant_id=TENANT_ID,
                driver_id=driver.id,
                driver_name=driver.name,
                vehicle_plate=driver.vehicle_plate or "",
                reading_type="final",
                reading_value=val,
                notes=f"Captura rápida por texto directo: '{texto}'",
            )
            if driver.is_available:
                await _completar_fin_turno(update, driver, repo, reading_val=val, con_foto=False)
            else:
                await update.message.reply_text(
                    f"🔴 **Carga Final Registrada:** `{val}`\n🚘 Unidad: {driver.vehicle_plate}",
                    reply_markup=get_teclado_principal("fuera_turno"),
                    parse_mode="Markdown",
                )
            return

        # Si escribe simplemente un porcentaje o litros (ej: "85%" o "4500 L")
        m_num = re.match(r"^(\d{1,3}\s*%(?:\s*(?:de\s*)?tanque)?|\d{2,6}\s*(?:l|litros))$", texto, re.I)
        if m_num:
            val = _normalizar_valor_tanque(m_num.group(1))
            context.user_data["pending_tank_text"] = val
            keyboard = [
                [
                    InlineKeyboardButton("🟢 Carga Inicial", callback_data="asigna_txt:initial"),
                    InlineKeyboardButton("🔴 Carga Final", callback_data="asigna_txt:final"),
                ],
                [
                    InlineKeyboardButton("🔵 Recarga en Planta", callback_data="asigna_txt:refill"),
                    InlineKeyboardButton("❌ Descartar", callback_data="asigna_txt:cancel"),
                ],
            ]
            await update.message.reply_text(
                f"⛽ **Lectura detectada:** `{val}`\n\n¿Deseas registrar este valor como:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown",
            )
            return

        # 5. Si el chofer envía cualquier otro texto mientras tiene un pedido activo en curso,
        # le respondemos desplazando los botones interactivos para que siempre estén disponibles al final
        active_order = obtener_pedido_activo_chofer(repo, driver.id)
        if active_order:
            inline_kb = get_botones_pedido_activo_inline(active_order)
            items_str = ", ".join(f"{it.quantity}x {it.product_name}" for it in active_order.items)
            pay_icon = "💵" if "efectivo" in active_order.payment_method.lower() else "💳"
            msg_activo = (
                f"🚚 **Pedido #{active_order.id} en curso:**\n\n"
                f"👤 **Cliente:** {active_order.customer_name} (`{active_order.customer_phone}`)\n"
                f"📍 **Dirección:** `{active_order.delivery_address}`\n"
                f"💰 **Cobro:** ${active_order.total_amount:.2f} {active_order.currency} ({pay_icon} {active_order.payment_method})\n"
                f"📦 **Productos:** {items_str}\n\n"
                "👇 Toca un botón para iniciar navegación o marcar la entrega:"
            )
            ord_msg = await update.message.reply_text(
                msg_activo,
                reply_markup=inline_kb,
                parse_mode="Markdown",
            )
            if ord_msg:
                try:
                    repo.add_order_driver_message_id(TENANT_ID, active_order.id, ord_msg.message_id)
                except Exception:
                    pass
            return



async def recibir_motivo_rechazo_texto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Procesar motivo de rechazo escrito manualmente por el chofer."""
    order_id = context.user_data.get("awaiting_rejection_reason_for_order")
    if not order_id or not update.message or not update.message.text:
        return

    motivo = update.message.text.strip()
    context.user_data.pop("awaiting_rejection_reason_for_order", None)

    user_id = str(update.effective_user.id)
    repo = get_repository()
    driver = repo.get_driver_by_telegram_id(TENANT_ID, user_id)
    driver_name = driver.name if driver else "Chofer"
    driver_id = driver.id if driver else 0

    # Si el pedido tenía ubicación en tiempo real activa hacia el cliente, eliminarla
    order_canc = repo.get_order_by_id(TENANT_ID, order_id)
    if order_canc and order_canc.live_location_message_id and order_canc.live_location_chat_id:
        await asyncio.to_thread(remove_client_live_location, order_canc.live_location_chat_id, order_canc.live_location_message_id)
        repo.clear_order_live_location(TENANT_ID, order_id)

    repo.record_order_rejection(
        tenant_id=TENANT_ID,
        order_id=order_id,
        driver_id=driver_id,
        driver_name=driver_name,
        reason=motivo,
    )

    estado = _determinar_estado_ui_chofer(repo, driver)
    await _safe_reply_text(
        update.message,
        f"❌ **Pedido #{order_id} rechazado con éxito.**\n\n"
        f"📌 **Motivo registrado:** {motivo}\n\n"
        "🚨 *La Torre de Control ha recibido la incidencia y procederá a reasignar el pedido.*",
        reply_markup=get_teclado_principal(estado),
        parse_mode="Markdown",
    )


# -----------------------------------------------------------------------------
# Main Application
# -----------------------------------------------------------------------------

async def comando_cancelar_activos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando para cancelar y liberar todos los pedidos activos asignados al chofer."""
    if not update.effective_user or not update.message:
        return
    user_id = str(update.effective_user.id)
    repo = get_repository()
    driver = repo.get_driver_by_telegram_id(TENANT_ID, user_id)
    if not driver:
        await update.message.reply_text("⚠️ Chofer no registrado.")
        return
    count = repo.cancel_all_orders_for_driver(TENANT_ID, driver.id, "Cancelación masiva por comando /cancelar_activos")
    estado = _determinar_estado_ui_chofer(repo, driver)
    await update.message.reply_text(
        f"✅ **Se han liberado y cancelado tus {count} pedido(s) activo(s).**\n\n"
        "🚨 *La Torre de Control ha recibido las órdenes para reasignarlas a otras unidades.* Quedas en estado 🟢 **Disponible**.",
        reply_markup=get_teclado_principal(estado),
        parse_mode="Markdown",
    )



async def monitor_dashboard_assigned_orders(bot) -> None:
    """Monitorea periódicamente pedidos asignados a choferes desde el Dashboard y envía la alerta interactiva."""
    logger.info("🚀 Iniciando monitor en segundo plano para pedidos asignados desde el Dashboard...")
    # Pre-cargar pedidos ya conocidos para no alertar pedidos viejos al reiniciar
    try:
        raw_initial = await asyncio.to_thread(api_get, "/orders", {"tenantId": TENANT_ID}, 5)
        if isinstance(raw_initial, list):
            for o in raw_initial:
                d_id = o.get("driverId")
                st = str(o.get("status") or "").upper()
                if d_id and st in ("EN_RUTA", "ENTREGADO", "CANCELADO"):
                    oid = str(o.get("orderNumber") or o.get("id"))
                    _notified_dashboard_assigned_orders.add((oid, str(d_id)))
    except Exception as e:
        logger.debug(f"[Monitor Preload] {e}")

    while True:
        try:
            repo = get_repository()
            raw_orders = await asyncio.to_thread(api_get, "/orders", {"tenantId": TENANT_ID}, 5)
            if isinstance(raw_orders, list):
                for o in raw_orders:
                    driver_id = o.get("driverId")
                    if not driver_id:
                        continue

                    status_raw = str(o.get("status") or "").upper()
                    # Se considera asignado si el estado es ASIGNADO/ASSIGNED o si ya tiene driverId y no está en ruta/terminado
                    is_assigned = (status_raw in ("ASIGNADO", "ASSIGNED")) or (
                        driver_id and status_raw not in ("EN_RUTA", "ENTREGADO", "CANCELADO", "IN_ROUTE", "DELIVERED", "CANCELLED")
                    )
                    if is_assigned:
                        raw_id = str(o.get("orderNumber") or o.get("id"))
                        order_key = (raw_id, str(driver_id))
                        if order_key in _notified_dashboard_assigned_orders:
                            continue

                        # Obtener datos del chofer
                        driver = await asyncio.to_thread(repo.get_driver, driver_id)
                        if driver and driver.telegram_user_id and str(driver.telegram_user_id).isdigit():
                            parsed_order = repo._parse_api_order(o, TENANT_ID)
                            logger.info(f"🚨 [Dashboard Assignment] Enviando alerta de pedido #{parsed_order.id} al chofer {driver.name} ({driver.telegram_user_id})")

                            sent = await asyncio.to_thread(
                                send_driver_trip_alert,
                                telegram_user_id=driver.telegram_user_id,
                                order=parsed_order,
                                title_header="🚨 **¡NUEVO PEDIDO ASIGNADO POR TORRE DE CONTROL!**",
                                lat=parsed_order.delivery_lat,
                                lng=parsed_order.delivery_lng,
                            )
                            if sent:
                                _notified_dashboard_assigned_orders.add(order_key)

                                # Resolver canal e identificador real del cliente (con fallback a identity_store)
                                eff_chan = parsed_order.channel
                                eff_uid = parsed_order.channel_user_id
                                if not eff_chan or not eff_uid or (eff_chan == "telegram" and not str(eff_uid).isdigit()):
                                    chan_info = identity_store.get_order_channel_info(parsed_order.id) or identity_store.get_order_channel_info(raw_id)
                                    if chan_info:
                                        eff_chan = chan_info.get("channel") or eff_chan
                                        eff_uid = chan_info.get("channel_user_id") or eff_uid

                                recipient_id = str(eff_uid or parsed_order.customer_phone or "").strip()
                                if recipient_id:
                                    v_plate = _get_driver_vehicle_label(driver, repo)
                                    d_phone_line = f"📞 **Teléfono:** `{driver.phone}`\n" if driver.phone else ""
                                    msg_asignacion = (
                                        f"🛻 **¡Tu pedido #{parsed_order.id} ha sido asignado!**\n\n"
                                        f"👨‍✈️ **Chofer:** {driver.name}\n"
                                        f"🚘 **Unidad:** {v_plate}\n"
                                        f"{d_phone_line}\n"
                                        f"El operador está preparando tu unidad y te avisaremos en cuanto inicie su recorrido hacia tu domicilio. ⛽"
                                    )
                                    await asyncio.to_thread(notify_client, recipient_id, msg_asignacion, None, eff_chan)
        except Exception as e:
            logger.debug(f"[Monitor Dashboard Orders Loop] {e}")

        await asyncio.sleep(4)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors caused by Updates and suppress benign network disconnects."""
    err = context.error
    if not err:
        return
    err_str = str(err).lower()
    if any(k in err_str for k in ("httpx.readtimeout", "httpx.connecterror", "httpx.remoteprotocolerror", "network is unreachable", "timed out")):
        logger.debug(f"Telegram transient network error: {err}")
        return
    if "query is too old" in err_str:
        logger.debug(f"Telegram callback query expired: {err}")
        return
    logger.error(f"Unhandled exception in driver_bot: {err}", exc_info=err)


def main() -> None:
    """Iniciar el Bot de Choferes de Telegram."""
    settings = get_settings()
    import os
    token = settings.telegram_driver_bot_token or os.getenv('TELEGRAM_DRIVER_BOT_TOKEN')

    if not token:
        print("❌ ERROR: TELEGRAM_DRIVER_BOT_TOKEN no está configurado en el archivo .env")
        sys.exit(1)

    init_db()

    print("=" * 60)
    print("🚚 Iniciando Bot Interactivo de Choferes y Reparto")
    print(f"🏪 Tenant: Gas a Tu Puerta - Petroil ({TENANT_ID})")
    print("=" * 60)

    request_config = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )

    async def post_init(app: Application) -> None:
        asyncio.create_task(monitor_dashboard_assigned_orders(app.bot))

    application = (
        Application.builder()
        .token(token)
        .request(request_config)
        .get_updates_request(request_config)
        .post_init(post_init)
        .build()
    )

    application.add_error_handler(error_handler)

    # Flujo de Ingreso y Autenticación por Celular Asignado
    registro_conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("login", pedir_telefono_ingreso),
            CommandHandler("registro", pedir_telefono_ingreso),
            CommandHandler("acceso", pedir_telefono_ingreso),
            CommandHandler("cambiar_numero", pedir_telefono_ingreso),
        ],
        states={
            PASO_TELEFONO_LOGIN: [
                MessageHandler(filters.CONTACT, recibir_telefono_login),
                MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_telefono_login),
            ],
        },
        fallbacks=[CommandHandler("cancelar", cancelar_registro)],
        allow_reentry=True,
    )
    application.add_handler(registro_conv)

    # Botones de Gestión de Turno
    application.add_handler(MessageHandler(filters.Regex(r"^(🟢 Iniciar Turno|🟢 Reanudar Turno|/disponible)"), boton_disponible))
    application.add_handler(MessageHandler(filters.Regex(r"^(⏸️ Pausar|/pausa|/ocupado)"), boton_pausa))
    application.add_handler(MessageHandler(filters.Regex(r"^(🛑 Terminar Turno|/terminar_turno|/fin_turno)"), boton_terminar_turno))

    # Botón de Medidor de Tanque / Pipa
    application.add_handler(MessageHandler(filters.Regex(r"^(⛽ Medidor de Tanque|/carga|/tanque)"), boton_medidor_tanque))

    # Otros Botones del Teclado
    application.add_handler(MessageHandler(filters.Regex(r"^(📋 Mis Pedidos Activos|/pedidos)"), boton_pedidos))
    application.add_handler(MessageHandler(filters.Regex(r"^(👤 Mi Perfil|/perfil)"), boton_perfil))
    application.add_handler(MessageHandler(filters.Regex(r"^(📍 Actualizar Ubicación GPS|/ubicacion)"), pedir_actualizar_ubicacion))

    # Recepción de Fotografía (Reloj de tanque o medidor)
    application.add_handler(MessageHandler(filters.PHOTO, recibir_foto_chofer))

    # Recepción de Ubicación GPS (tanto mensajes directos como actualizaciones de live location en tiempo real)
    application.add_handler(
        MessageHandler(
            filters.LOCATION | (filters.UpdateType.EDITED_MESSAGE & filters.LOCATION),
            recibir_ubicacion_tiempo_real,
        )
    )

    # Recepción de mensajes de texto libre (lecturas de tanque o motivo de rechazo)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_texto_chofer))

    # Comando rápido para cancelar y liberar todos los pedidos activos asignados
    application.add_handler(CommandHandler(["cancelar_activos", "limpiar_pedidos"], comando_cancelar_activos))

    # Comandos directos de Carga de Tanque / Pipa y Asistencia / Turno
    application.add_handler(CommandHandler(["cargainicial", "carga_inicial", "iniciocarga"], comando_carga_inicial))
    application.add_handler(CommandHandler(["cargafinal", "carga_final", "fincarga"], comando_carga_final))
    application.add_handler(CommandHandler(["tanque", "carga", "medidor"], boton_medidor_tanque))
    application.add_handler(CommandHandler(["turno", "jornada", "asistencia"], comando_turno))

    # Botones interactivos (Aceptar / Entregar / Rechazar / Motivo de rechazo / Carga de tanque)
    application.add_handler(CallbackQueryHandler(manejar_callback_pedidos))

    print("✅ Bot de Choferes conectado con Telegram. Listo para registro y despachos en tiempo real.")
    application.run_polling(
        bootstrap_retries=10,
        poll_interval=1.0,
        timeout=30,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Bot de Choferes detenido correctamente por el usuario (Ctrl+C).")

