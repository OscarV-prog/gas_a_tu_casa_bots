"""Order lifecycle event dispatcher and notification bridge for PWA and external platforms.

Ensures real-time notifications to customers across all active channels
(WhatsApp, Telegram, Facebook Messenger, Instagram Direct) when orders change
state in the Driver PWA or Central NestJS API:
1. Driver Assigned (notify_order_assigned)
2. In Route / On the way with Live GPS (notify_order_in_route)
3. GPS Location Moving Updates (notify_driver_location_update)
4. Order Delivered with 5-Star Survey (notify_order_delivered)
5. Order Cancelled (notify_order_cancelled)
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from src.repositories import get_repository
from src.repositories.identity_store import identity_store
from src.services.notifications import (
    cleanup_client_order_buttons,
    edit_client_live_location,
    notify_client,
    notify_delivery_survey,
    remove_client_live_location,
    send_client_live_location,
)

logger = logging.getLogger(__name__)

# Deduplication cache: (event_name, order_id) -> timestamp
_EVENT_DEDUP_CACHE: dict[tuple[str, str], float] = {}
_LAST_DRIVER_GPS_NOTIF: dict[str, tuple[float, float, float]] = {}  # driver_id -> (lat, lng, timestamp)


def _is_event_deduped(event_name: str, order_id: Any, ttl_seconds: float = 60.0) -> bool:
    """Check if an event was already dispatched recently to prevent duplicate spam."""
    now = time.time()
    key = (str(event_name).lower(), str(order_id).strip())

    # Periodic cleanup of old keys
    if len(_EVENT_DEDUP_CACHE) > 2000:
        expired = [k for k, ts in _EVENT_DEDUP_CACHE.items() if now - ts > 300]
        for k in expired:
            _EVENT_DEDUP_CACHE.pop(k, None)

    if key in _EVENT_DEDUP_CACHE:
        if now - _EVENT_DEDUP_CACHE[key] < ttl_seconds:
            return True

    _EVENT_DEDUP_CACHE[key] = now
    return False


def _resolve_recipient_and_channel(order: Any, order_id: Any) -> tuple[str, str]:
    """Resolve customer recipient ID and channel accurately from order and identity store."""
    recipient_id = str(getattr(order, "channel_user_id", "") or getattr(order, "customer_phone", "") or "").strip()
    channel = str(getattr(order, "channel", "") or "").lower()

    # Cross-reference with identity_store
    try:
        chan_info = identity_store.get_order_channel_info(order_id)
        if chan_info:
            if not channel or channel == "telegram":
                store_chan = str(chan_info.get("channel", "")).lower()
                if store_chan:
                    channel = store_chan
            if not recipient_id or recipient_id == getattr(order, "customer_phone", ""):
                store_uid = str(chan_info.get("channel_user_id", "")).strip()
                if store_uid:
                    recipient_id = store_uid
    except Exception:
        pass

    if not channel:
        clean_dig = re.sub(r"\D", "", recipient_id)
        if clean_dig.startswith("52") or len(clean_dig) == 10:
            channel = "whatsapp"
        else:
            channel = "telegram"

    return recipient_id, channel


def notify_order_assigned(
    tenant_id: str,
    order_id: Any,
    driver_id: Any = None,
    force: bool = False,
) -> bool:
    """Notify the customer that their order has been assigned to a driver in the PWA."""
    if not force and _is_event_deduped("assigned", order_id, ttl_seconds=120.0):
        logger.debug(f"[OrderEvents] Assignment alert already sent for order #{order_id}, skipping.")
        return True

    repo = get_repository()
    order = repo.get_order_by_id(tenant_id, order_id)
    if not order:
        logger.warning(f"[OrderEvents] Order #{order_id} not found for assignment notification.")
        return False

    eff_driver_id = driver_id or getattr(order, "driver_id", None)
    driver = repo.get_driver(eff_driver_id) if eff_driver_id else None
    driver_name = getattr(driver, "name", "Repartidor Petroil") if driver else "Repartidor Petroil"
    v_plate = getattr(driver, "vehicle_plate", None) or "Unidad de reparto"
    d_phone = getattr(driver, "phone", "") or ""
    phone_line = f"📞 **Teléfono:** `{d_phone}`\n" if d_phone else ""

    recipient_id, channel = _resolve_recipient_and_channel(order, order_id)
    if not recipient_id:
        return False

    msg_asignacion = (
        f"🛻 **¡Tu pedido #{order.id} ha sido asignado!**\n\n"
        f"👨‍✈️ **Chofer:** {driver_name}\n"
        f"🚘 **Unidad:** {v_plate}\n"
        f"{phone_line}\n"
        f"El operador está preparando su unidad y te avisaremos en cuanto inicie su recorrido hacia tu domicilio. ⛽"
    )

    try:
        ok = notify_client(recipient_id, msg_asignacion, None, channel)
        logger.info(f"📣 [OrderEvents] Assignment notification sent for order #{order_id} to {recipient_id} ({channel}) -> {ok}")
        return ok
    except Exception as e:
        logger.error(f"[OrderEvents] Error sending assignment notification for #{order_id}: {e}")
        return False


def notify_order_in_route(
    tenant_id: str,
    order_id: Any,
    driver_id: Any = None,
    force: bool = False,
) -> bool:
    """Notify the customer that the driver is on their way (EN_RUTA) with live GPS tracking."""
    if not force and _is_event_deduped("in_route", order_id, ttl_seconds=120.0):
        logger.debug(f"[OrderEvents] In-route alert already sent for order #{order_id}, skipping.")
        return True

    repo = get_repository()
    order = repo.get_order_by_id(tenant_id, order_id)
    if not order:
        logger.warning(f"[OrderEvents] Order #{order_id} not found for in_route notification.")
        return False

    eff_driver_id = driver_id or getattr(order, "driver_id", None)
    driver = repo.get_driver(eff_driver_id) if eff_driver_id else None

    recipient_id, channel = _resolve_recipient_and_channel(order, order_id)
    if not recipient_id:
        return False

    # Extract driver coordinates if available
    driver_lat = getattr(driver, "current_lat", None) if driver else None
    driver_lng = getattr(driver, "current_lng", None) if driver else None

    # Check cached locations in repo if driver object doesn't have them
    if (driver_lat is None or driver_lng is None) and hasattr(repo, "_driver_locations") and eff_driver_id:
        cached = repo._driver_locations.get(str(eff_driver_id)) or (
            repo._driver_locations.get(str(driver.telegram_user_id)) if driver and getattr(driver, "telegram_user_id", None) else None
        )
        if cached:
            driver_lat, driver_lng = cached

    v_plate = getattr(driver, "vehicle_plate", None) or "Unidad de reparto"
    d_phone = getattr(driver, "phone", "") or ""
    phone_line = f"\n• 📞 **Teléfono chofer:** `{d_phone}`" if d_phone else ""

    if driver_lat is not None and driver_lng is not None and driver_lat != 0.0 and driver_lng != 0.0:
        # Transmit live location pin or tracking card with active map link
        live_msg_id = send_client_live_location(
            channel_user_id=recipient_id,
            latitude=float(driver_lat),
            longitude=float(driver_lng),
            live_period=7200,
            channel=channel,
            order_id=order.id,
        )
        if live_msg_id:
            try:
                repo.set_order_live_location(tenant_id, order.id, recipient_id, live_msg_id)
            except Exception as e:
                logger.debug(f"[OrderEvents] Note setting live location: {e}")

        if channel == "telegram":
            msg_live_notif = (
                f"🚚 **¡Tu pedido #{order.id} va en camino a tu domicilio!**\n\n"
                f"• 👨‍✈️ **Chofer:** {driver.name if driver else 'Unidad Petroil'}\n"
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
            notify_client(recipient_id, msg_live_notif, btn_cancel, channel)

        logger.info(f"📍 [OrderEvents] In-route GPS tracking initiated for order #{order_id} -> {recipient_id} ({channel})")
        return True
    else:
        # Driver GPS not yet transmitted: notify clean in-route message
        msg_cliente = (
            f"🚚 **¡Tu pedido #{order.id} va en camino a tu domicilio!**\n\n"
            f"• 👨‍✈️ **Chofer:** {driver.name if driver else 'Unidad Petroil'}\n"
            f"• 🚘 **Unidad:** {v_plate}{phone_line}\n\n"
            "Tu repartidor ya inició su recorrido hacia tu domicilio. Te notificaremos en cuanto esté por llegar. ⛽✨"
        )
        ok = notify_client(recipient_id, msg_cliente, None, channel)
        logger.info(f"🚚 [OrderEvents] In-route text notification sent for order #{order_id} -> {recipient_id} ({channel})")
        return ok


def notify_driver_location_update(
    tenant_id: str,
    driver_id: Any,
    lat: float,
    lng: float,
) -> int:
    """Update live location tracking for all active in-route orders of this driver."""
    if not driver_id or lat is None or lng is None:
        return 0

    repo = get_repository()
    d_str = str(driver_id).strip()

    # Throttling: prevent rapid spam updates within 10 seconds unless moved > 25 meters (~0.00025 deg)
    now = time.time()
    last_info = _LAST_DRIVER_GPS_NOTIF.get(d_str)
    if last_info:
        last_lat, last_lng, last_time = last_info
        dist_deg = abs(lat - last_lat) + abs(lng - last_lng)
        if now - last_time < 10.0 and dist_deg < 0.00025:
            return 0
    _LAST_DRIVER_GPS_NOTIF[d_str] = (lat, lng, now)

    try:
        active_orders = repo.get_orders_by_driver(tenant_id, driver_id, active_only=True)
    except Exception as e:
        logger.debug(f"[OrderEvents] Error getting driver orders: {e}")
        return 0

    updated_count = 0
    for order in active_orders:
        if str(getattr(order, "status", "")).lower() not in ("in_route", "en_ruta", "en_camino"):
            continue

        recipient_id, channel = _resolve_recipient_and_channel(order, order.id)
        if not recipient_id:
            continue

        live_msg_id = getattr(order, "live_location_message_id", None)
        live_chat_id = getattr(order, "live_location_chat_id", None) or recipient_id

        if live_msg_id:
            edit_client_live_location(
                channel_user_id=str(live_chat_id),
                message_id=int(live_msg_id),
                latitude=float(lat),
                longitude=float(lng),
                channel=channel,
            )
            updated_count += 1
        else:
            # First location broadcast for this active trip
            new_msg_id = send_client_live_location(
                channel_user_id=recipient_id,
                latitude=float(lat),
                longitude=float(lng),
                live_period=7200,
                channel=channel,
                order_id=order.id,
            )
            if new_msg_id:
                try:
                    repo.set_order_live_location(tenant_id, order.id, recipient_id, new_msg_id)
                except Exception:
                    pass
                updated_count += 1

    return updated_count


def notify_order_delivered(
    tenant_id: str,
    order_id: Any,
    force: bool = False,
) -> bool:
    """Notify customer of delivery completion and prompt 5-star interactive satisfaction survey."""
    if not force and _is_event_deduped("delivered", order_id, ttl_seconds=180.0):
        logger.debug(f"[OrderEvents] Delivery survey already dispatched for order #{order_id}, skipping.")
        return True

    repo = get_repository()
    order = repo.get_order_by_id(tenant_id, order_id)
    if not order:
        logger.warning(f"[OrderEvents] Order #{order_id} not found for delivery survey.")
        return False

    # 1. Clean up live location pin and cancel buttons from customer's chat
    try:
        live_msg_id = getattr(order, "live_location_message_id", None)
        live_chat_id = getattr(order, "live_location_chat_id", None)
        if live_msg_id and live_chat_id:
            remove_client_live_location(str(live_chat_id), int(live_msg_id))
            repo.clear_order_live_location(tenant_id, order.id)
    except Exception as e:
        logger.debug(f"[OrderEvents] Live location cleanup note: {e}")

    try:
        cleanup_client_order_buttons(order.id, tenant_id=tenant_id, keep_message_id=None)
    except Exception as e:
        logger.debug(f"[OrderEvents] Cleanup buttons note: {e}")

    # 2. Release driver availability
    if getattr(order, "driver_id", None):
        try:
            repo.set_driver_availability(order.driver_id, True)
        except Exception:
            pass

    # 3. Trigger 5-star satisfaction survey across WhatsApp, Telegram, Messenger, or Instagram
    ok = notify_delivery_survey(order.id, tenant_id)
    logger.info(f"⭐ [OrderEvents] Delivery satisfaction survey dispatched for order #{order_id} -> {ok}")
    return ok


def notify_order_cancelled(
    tenant_id: str,
    order_id: Any,
    reason: str = "",
    cancelled_by: str = "Torre de Control",
    force: bool = False,
) -> bool:
    """Notify customer of order cancellation with clear explanation and apology."""
    if not force and _is_event_deduped("cancelled", order_id, ttl_seconds=120.0):
        return True

    repo = get_repository()
    order = repo.get_order_by_id(tenant_id, order_id)
    if not order:
        return False

    # Clean up buttons and live location
    try:
        cleanup_client_order_buttons(order_id, tenant_id=tenant_id, keep_message_id=None)
        live_msg_id = getattr(order, "live_location_message_id", None)
        live_chat_id = getattr(order, "live_location_chat_id", None)
        if live_msg_id and live_chat_id:
            remove_client_live_location(str(live_chat_id), int(live_msg_id))
            repo.clear_order_live_location(tenant_id, order_id)
    except Exception:
        pass

    explanation = reason or "Incidencia operativa o solicitud de cancelación en sistema."
    client_cancel_msg = (
        f"🚫 **Aviso sobre tu Pedido #{order.id} - Petroil Gas**\n\n"
        f"Estimado/a **{order.customer_name}**,\n\n"
        f"Le informamos que lamentablemente su pedido de gas programado para `{order.delivery_address}` **ha sido cancelado**.\n\n"
        f"📌 **Explicación:** {explanation}\n\n"
        f"🙏 **Le ofrecemos una sincera disculpa por los inconvenientes y contratiempos ocasionados.**\n\n"
        f"💡 Si desea reagendar su servicio o necesita asistencia de un asesor, simplemente respóndanos por este medio en cualquier momento y con gusto le atenderemos. ⛽✨"
    )

    recipient_id, channel = _resolve_recipient_and_channel(order, order_id)
    if recipient_id:
        return notify_client(recipient_id, client_cancel_msg, None, channel)
    return False


def handle_order_transition(
    tenant_id: str,
    order_id: Any,
    new_status: str,
    driver_id: Any = None,
    reason: str = "",
    signature: str | None = None,
) -> bool:
    """Unified handler for order lifecycle status transitions from PWA or Control Tower."""
    raw_status = str(new_status or "").lower().strip()
    status_map = {
        "en_ruta": "in_route",
        "en_camino": "in_route",
        "in_route": "in_route",
        "entregado": "delivered",
        "delivered": "delivered",
        "cancelado": "cancelled",
        "cancelled": "cancelled",
        "asignado": "assigned",
        "assigned": "assigned",
    }
    normalized = status_map.get(raw_status, raw_status)

    if normalized == "assigned":
        return notify_order_assigned(tenant_id, order_id, driver_id=driver_id)
    elif normalized == "in_route":
        return notify_order_in_route(tenant_id, order_id, driver_id=driver_id)
    elif normalized == "delivered":
        return notify_order_delivered(tenant_id, order_id)
    elif normalized == "cancelled":
        return notify_order_cancelled(tenant_id, order_id, reason=reason)

    return True
