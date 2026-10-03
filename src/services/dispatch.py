"""Smart dispatch, scheduled orders, and driver assignment service."""

from __future__ import annotations

import logging
from typing import Any

from src.repositories import get_repository
from src.services.geocoding import (
    geocode_address,
    get_google_maps_url,
    get_waze_url,
)
from src.services.notifications import notify_driver

logger = logging.getLogger(__name__)


def is_future_order(schedule: str, ref_time: datetime | None = None) -> bool:
    """Check if the delivery schedule is for a scheduled future time (today later or future days)."""
    if not schedule:
        return False
    from datetime import datetime, timedelta
    from src.repositories.sqlite_repo import parse_schedule_deadline

    now = ref_time or datetime.now()
    deadline_dt = parse_schedule_deadline(schedule, now)
    if deadline_dt:
        # If deadline is more than 30 minutes in the future, it's a scheduled order
        return now < (deadline_dt - timedelta(minutes=30))

    s = schedule.lower().strip()
    if any(today_word in s for today_word in ["lo antes posible", "ahorita", "inmediato", "ahora", "urgente"]):
        return False

    future_signals = [
        "mañana",
        "manana",
        "pasado mañana",
        "pasado manana",
        "el lunes",
        "el martes",
        "el miércoles",
        "el miercoles",
        "el jueves",
        "el viernes",
        "el sábado",
        "el sabado",
        "el domingo",
        "próximo",
        "proximo",
        "siguiente semana",
        "siguiente mes",
        "el día",
        "el dia",
    ]
    return any(sig in s for sig in future_signals)


def determine_required_vehicle_type(items: list[Any]) -> str:
    """Analyze ordered items to decide if a cylinder truck or stationary tank truck is required."""
    text_blob = " ".join(f"{getattr(it, 'product_name', '')} {getattr(it, 'product_id', '')}".lower() for it in items)

    if "estacionario" in text_blob or "litro" in text_blob or "pipa" in text_blob:
        return "estacionario"
    elif "cilindro" in text_blob or "10 kg" in text_blob or "20 kg" in text_blob or "30 kg" in text_blob or "45 kg" in text_blob:
        return "cilindros"
    return "ambos"


def dispatch_order(order_id: int, tenant_id: str = "petroil", force_immediate: bool = False) -> bool:
    """Assign order to available drivers on shift and send the dispatch alert.

    If the order is scheduled for a future day and force_immediate is False,
    it stays in 'scheduled' status and will be dispatched at morning shift start.

    Args:
        order_id: ID of the order to dispatch.
        tenant_id: Tenant identifier.
        force_immediate: If True, dispatches even if scheduled for a future day.

    Returns:
        True if dispatched or scheduled, False otherwise.
    """
    repo = get_repository()
    order = repo.get_order_by_id(tenant_id, order_id)
    if not order:
        logger.error(f"[Dispatch] Order #{order_id} not found.")
        return False

    # 1. Geocode or use existing delivery coordinates
    if order.delivery_lat is not None and order.delivery_lng is not None and order.delivery_lat != 0.0:
        lat = order.delivery_lat
        lng = order.delivery_lng
        formatted_addr = order.delivery_address
        logger.info(f"[Dispatch] Order #{order_id} using existing GPS: ({lat:.5f}, {lng:.5f})")
    else:
        lat, lng, formatted_addr = geocode_address(order.delivery_address)
        logger.info(f"[Dispatch] Order #{order_id} geocoded to ({lat:.5f}, {lng:.5f}) - {formatted_addr}")

    # 2. Check if this order is scheduled for future days or > 30 minutes away
    if not force_immediate:
        from datetime import datetime, timedelta
        from src.repositories.sqlite_repo import parse_schedule_deadline

        now = datetime.now()
        deadline_dt = None
        if order.scheduled_for:
            try:
                deadline_dt = datetime.fromisoformat(order.scheduled_for)
            except Exception:
                deadline_dt = parse_schedule_deadline(order.scheduled_for, now)
        if not deadline_dt and order.delivery_schedule:
            deadline_dt = parse_schedule_deadline(order.delivery_schedule, now)

        if deadline_dt and now < (deadline_dt - timedelta(minutes=30)):
            logger.info(
                f"[Dispatch] Order #{order_id} is scheduled for {deadline_dt.strftime('%Y-%m-%d %H:%M')}. "
                f"Holding in 'scheduled' agenda until 30 minutes before deadline."
            )
            repo.update_order_status(tenant_id, order_id, "scheduled")
            return True
        elif is_future_order(order.delivery_schedule):
            logger.info(
                f"[Dispatch] Order #{order_id} is scheduled for future delivery ({order.delivery_schedule}). "
                f"Holding in 'scheduled' agenda until 30 minutes before deadline."
            )
            repo.update_order_status(tenant_id, order_id, "scheduled")
            return True

    # 3. Determine vehicle type
    vehicle_type = determine_required_vehicle_type(order.items)

    # 4. Find available drivers on shift (is_available = 1)
    available_drivers = repo.get_available_drivers(tenant_id, vehicle_type=vehicle_type)
    if not available_drivers:
        available_drivers = repo.get_available_drivers(tenant_id, vehicle_type="ambos")

    if not available_drivers:
        logger.warning(f"[Dispatch] No available drivers on shift for order #{order_id}.")
        repo.assign_order_to_driver(
            tenant_id, order_id, driver_id=None, delivery_lat=lat, delivery_lng=lng, force_activate=force_immediate
        )
        return False

    # 5. Prioritize drivers with Telegram connected (numeric ID only)
    telegram_drivers = [d for d in available_drivers if d.telegram_user_id and str(d.telegram_user_id).isdigit()]
    selected_driver = telegram_drivers[0] if telegram_drivers else available_drivers[0]

    logger.info(
        f"[Dispatch] Assigned order #{order_id} to driver ID #{selected_driver.id} ({selected_driver.name}) "
        f"[Status: DISPONIBLE, Telegram: {selected_driver.telegram_user_id}]"
    )

    # 6. Assign order in DB
    assigned_order = repo.assign_order_to_driver(
        tenant_id=tenant_id,
        order_id=order_id,
        driver_id=selected_driver.id,
        delivery_lat=lat,
        delivery_lng=lng,
        force_activate=force_immediate,
    )

    # 7. Send alert to assigned driver (or active telegram drivers if unassigned)
    target_drivers = [selected_driver] if (selected_driver and selected_driver.telegram_user_id and str(selected_driver.telegram_user_id).isdigit()) else telegram_drivers
    for d in target_drivers:
        sent = send_driver_trip_alert(
            telegram_user_id=d.telegram_user_id,
            order=order,
            title_header="🚨 **¡NUEVO PEDIDO ASIGNADO!**",
            lat=lat,
            lng=lng,
        )
        if sent:
            logger.info(f"[Dispatch] Order #{order_id} alert sent to driver Telegram {d.name} ({d.telegram_user_id}).")
        else:
            logger.warning(f"[Dispatch] Failed to send Telegram alert to driver {d.name}.")

    # 8. Notify client that their order has been assigned to a driver
    recipient_id = str(order.channel_user_id or order.customer_phone or "").strip()
    if recipient_id:
        from src.services.notifications import notify_client
        v_plate = selected_driver.vehicle_plate or "Unidad de reparto"
        d_phone = selected_driver.phone or ""
        phone_line = f"📞 **Teléfono:** `{d_phone}`\n" if d_phone else ""
        msg_asignacion = (
            f"🛻 **¡Tu pedido #{order.id} ha sido asignado!**\n\n"
            f"👨‍✈️ **Chofer:** {selected_driver.name}\n"
            f"🚘 **Unidad:** {v_plate}\n"
            f"{phone_line}\n"
            f"El operador está preparando su unidad y te avisaremos en cuanto inicie su recorrido hacia tu domicilio. ⛽"
        )
        try:
            notify_client(recipient_id, msg_asignacion, channel=order.channel)
        except Exception as e:
            logger.warning(f"[Dispatch] Error al notificar asignación al cliente: {e}")

    return True


def send_driver_trip_alert(
    telegram_user_id: str,
    order: Any,
    title_header: str = "🚨 **¡NUEVO PEDIDO ASIGNADO!**",
    lat: float | None = None,
    lng: float | None = None,
) -> bool:
    """Send an interactive trip card with Google Maps, Waze, and Accept/Reject buttons to a driver."""
    if not telegram_user_id:
        return False

    order_lat = lat if (lat is not None and lat != 0.0) else getattr(order, "delivery_lat", None)
    order_lng = lng if (lng is not None and lng != 0.0) else getattr(order, "delivery_lng", None)

    gmaps_url = get_google_maps_url(order_lat, order_lng, query_fallback=order.delivery_address)
    waze_url = get_waze_url(order_lat, order_lng, query_fallback=order.delivery_address)

    items_list = getattr(order, "items", []) or []
    if items_list:
        items_summary = "\n".join(
            f"  • {getattr(it, 'quantity', 1)}x {getattr(it, 'product_name', getattr(it, 'name', 'Producto'))}"
            for it in items_list
        )
    else:
        items_summary = "  • Servicio de Gas LP"

    pay_method = getattr(order, "payment_method", "") or "Efectivo"
    pay_icon = "💵" if "efectivo" in pay_method.lower() else "💳"
    currency = getattr(order, "currency", "MXN")
    total_amt = getattr(order, "total_amount", 0.0) or 0.0

    driver_card = (
        f"{title_header}\n\n"
        f"📦 **Pedido #{order.id}**\n"
        f"👤 **Cliente:** {order.customer_name}\n"
        f"📞 **Teléfono:** `{order.customer_phone}`\n"
        f"📍 **Dirección:** {order.delivery_address}\n"
        f"📅 **Horario:** {order.delivery_schedule}\n"
        f"💰 **Total a Cobrar:** ${total_amt:.2f} {currency} ({pay_icon} {pay_method})\n\n"
        f"📦 **Productos:**\n{items_summary}\n"
    )
    notes = getattr(order, "notes", None)
    if notes:
        driver_card += f"\n📝 **Referencias:** {notes}\n"

    inline_keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Aceptar Viaje", "callback_data": f"accept_order:{order.id}"},
                {"text": "📦 Marcar como Entregado", "callback_data": f"confirm_deliver:{order.id}"},
            ],
            [
                {"text": "❌ Rechazar", "callback_data": f"reject_order:{order.id}"},
                {"text": "🗺️ Google Maps", "url": gmaps_url},
                {"text": "🚗 Waze", "url": waze_url},
            ],
        ]
    }

    msg_id = notify_driver(
        telegram_user_id=telegram_user_id,
        message=driver_card,
        reply_markup=inline_keyboard,
        lat=order_lat,
        lng=order_lng,
    )
    if msg_id and getattr(order, "id", None):
        try:
            from src.repositories import get_repository
            repo = get_repository()
            repo.add_order_driver_message_id("petroil", order.id, msg_id)
        except Exception:
            pass
    return bool(msg_id)


def dispatch_scheduled_orders_for_shift(tenant_id: str = "petroil") -> list[int]:
    """Dispatch held scheduled orders whose delivery window is ready or due."""
    repo = get_repository()
    activated_ids = repo.check_and_activate_scheduled_orders(tenant_id)
    return activated_ids
