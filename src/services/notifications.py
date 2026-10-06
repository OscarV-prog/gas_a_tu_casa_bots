"""Cross-bot notification service for clients and drivers (Telegram & WhatsApp)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from src.config.settings import get_settings

logger = logging.getLogger(__name__)

# Cache de deduplicación para notificaciones a clientes (evita mensajes duplicados por ráfagas)
_RECENT_CLIENT_NOTIFICATIONS: dict[tuple[str, str], float] = {}


def _send_telegram_api_call(token: str, method: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Send a request directly to Telegram Bot API and return parsed JSON response."""
    if not token:
        logger.debug(f"[Telegram Notification] No token configured for method {method}.")
        return None

    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            if resp.status == 200:
                body = resp.read().decode("utf-8")
                return json.loads(body)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(error_body)
        except Exception:
            parsed = {"ok": False, "error_code": e.code, "description": error_body}

        desc = str(parsed.get("description", "")).lower()
        if "message is not modified" in desc:
            logger.debug(f"Telegram API {method} (not modified): {desc}")
        elif any(k in desc for k in ("message can't be edited", "message to edit not found", "message to delete not found", "chat not found", "bot was blocked by the user", "user is deactivated")):
            logger.info(f"Telegram API {method} (expected/handled): {desc}")
        else:
            logger.warning(f"Telegram API HTTP {e.code} for {method}: {error_body}")
        return parsed
    except Exception as e:
        logger.warning(f"Error sending Telegram notification ({method}): {e}")

    return None


def _send_telegram_api(token: str, method: str, payload: dict[str, Any]) -> bool:
    """Send a request directly to Telegram Bot API via standard HTTP and check success."""
    resp = _send_telegram_api_call(token, method, payload)
    return bool(resp and resp.get("ok"))


def _is_whatsapp_channel(channel_user_id: str, channel: str | None = None) -> bool:
    """Check if the recipient is a WhatsApp user."""
    if channel:
        return channel.lower() == "whatsapp"

    uid_str = str(channel_user_id).strip()
    if not uid_str:
        return False

    clean_digits = re.sub(r"\D", "", uid_str)
    if clean_digits.startswith("52") and len(clean_digits) in (12, 13):
        return True
    if len(clean_digits) == 10 and clean_digits.isdigit():
        return True

    try:
        from src.repositories import get_repository
        repo = get_repository()
        cust = repo.get_customer("petroil", "whatsapp", uid_str)
        if cust:
            return True
        cust_phone = repo.get_customer_by_phone("petroil", clean_digits)
        if cust_phone and getattr(cust_phone, "channel", "") == "whatsapp":
            return True
    except Exception:
        pass

    return False


def _format_markdown_for_whatsapp(text: str) -> str:
    """Convert Telegram Markdown formatting (**bold**) to WhatsApp style (*bold*)."""
    if not text:
        return ""
    # Convert **bold** -> *bold*
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    # Convert __italic__ -> _italic_
    text = re.sub(r"__(.+?)__", r"_\1_", text)
    return text


def _send_whatsapp_message_sync(recipient_wa_id: str, text: str) -> bool:
    """Synchronously send a WhatsApp message using WhatsAppAdapter."""
    from src.channels.whatsapp.adapter import WhatsAppAdapter
    wa = WhatsAppAdapter()
    if not wa.is_configured:
        logger.warning(f"[WhatsApp Notification] Adapter not configured for {recipient_wa_id}")
        return False

    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            loop.create_task(wa.send_text_message(recipient_wa_id, text))
            return True
        else:
            return asyncio.run(wa.send_text_message(recipient_wa_id, text))
    except Exception as e:
        logger.error(f"[WhatsApp Notification] Error sending to {recipient_wa_id}: {e}")
        return False


def _send_whatsapp_buttons_sync(recipient_wa_id: str, text: str, buttons: list[dict[str, str]]) -> bool:
    """Synchronously send WhatsApp interactive buttons using WhatsAppAdapter."""
    from src.channels.whatsapp.adapter import WhatsAppAdapter
    wa = WhatsAppAdapter()
    if not wa.is_configured:
        return False
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            loop.create_task(wa.send_interactive_buttons(recipient_wa_id, text, buttons))
            return True
        else:
            return asyncio.run(wa.send_interactive_buttons(recipient_wa_id, text, buttons))
    except Exception as e:
        logger.error(f"[WhatsApp Notification Buttons] Error sending to {recipient_wa_id}: {e}")
        return False


def _send_whatsapp_location_sync(
    recipient_wa_id: str,
    lat: float,
    lng: float,
    name: str = "Repartidor Petroil en Camino",
    address: str = "",
) -> bool:
    """Synchronously send a WhatsApp location pin using WhatsAppAdapter."""
    from src.channels.whatsapp.adapter import WhatsAppAdapter
    wa = WhatsAppAdapter()
    if not wa.is_configured:
        return False

    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            loop.create_task(wa.send_location(recipient_wa_id, lat, lng, name, address))
            return True
        else:
            return asyncio.run(wa.send_location(recipient_wa_id, lat, lng, name, address))
    except Exception as e:
        logger.error(f"[WhatsApp Location] Error sending to {recipient_wa_id}: {e}")
        return False


def _send_messenger_message_sync(recipient_psid: str, text: str) -> bool:
    """Synchronously send a Facebook Messenger message using MessengerAdapter."""
    from src.channels.messenger.adapter import MessengerAdapter
    msgr = MessengerAdapter()
    if not msgr.is_configured:
        logger.warning(f"[Messenger Notification] Adapter not configured for {recipient_psid}")
        return False
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            loop.create_task(msgr.send_text_message(recipient_psid, text))
            return True
        else:
            return asyncio.run(msgr.send_text_message(recipient_psid, text))
    except Exception as e:
        logger.error(f"[Messenger Notification] Error sending to {recipient_psid}: {e}")
        return False


def _send_messenger_buttons_sync(recipient_psid: str, text: str, buttons: list[dict[str, str]]) -> bool:
    """Synchronously send Facebook Messenger quick replies using MessengerAdapter."""
    from src.channels.messenger.adapter import MessengerAdapter
    msgr = MessengerAdapter()
    if not msgr.is_configured:
        return False
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            loop.create_task(msgr.send_quick_replies(recipient_psid, text, buttons))
            return True
        else:
            return asyncio.run(msgr.send_quick_replies(recipient_psid, text, buttons))
    except Exception as e:
        logger.error(f"[Messenger Notification Buttons] Error sending to {recipient_psid}: {e}")
        return False


def _send_messenger_button_template_sync(
    recipient_psid: str,
    text: str,
    buttons: list[dict[str, Any]],
) -> bool:
    """Synchronously send Facebook Messenger button template using MessengerAdapter."""
    from src.channels.messenger.adapter import MessengerAdapter
    msgr = MessengerAdapter()
    if not msgr.is_configured:
        return False
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            loop.create_task(msgr.send_button_template(recipient_psid, text, buttons))
            return True
        else:
            return asyncio.run(msgr.send_button_template(recipient_psid, text, buttons))
    except Exception as e:
        logger.error(f"[Messenger Notification Button Template] Error sending to {recipient_psid}: {e}")
        return False


def _send_instagram_message_sync(recipient_igsid: str, text: str) -> bool:
    """Synchronously send an Instagram Direct message using InstagramAdapter."""
    from src.channels.instagram.adapter import InstagramAdapter
    ig = InstagramAdapter()
    if not ig.is_configured:
        logger.warning(f"[Instagram Notification] Adapter not configured for {recipient_igsid}")
        return False
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            loop.create_task(ig.send_text_message(recipient_igsid, text))
            return True
        else:
            return asyncio.run(ig.send_text_message(recipient_igsid, text))
    except Exception as e:
        logger.error(f"[Instagram Notification] Error sending to {recipient_igsid}: {e}")
        return False


def _send_instagram_buttons_sync(recipient_igsid: str, text: str, buttons: list[dict[str, str]]) -> bool:
    """Synchronously send Instagram Direct quick replies using InstagramAdapter."""
    from src.channels.instagram.adapter import InstagramAdapter
    ig = InstagramAdapter()
    if not ig.is_configured:
        return False
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            loop.create_task(ig.send_quick_replies(recipient_igsid, text, buttons))
            return True
        else:
            return asyncio.run(ig.send_quick_replies(recipient_igsid, text, buttons))
    except Exception as e:
        logger.error(f"[Instagram Notification Buttons] Error sending to {recipient_igsid}: {e}")
        return False


def _send_instagram_button_template_sync(
    recipient_igsid: str,
    text: str,
    buttons: list[dict[str, Any]],
) -> bool:
    """Synchronously send Instagram Direct button template using InstagramAdapter."""
    from src.channels.instagram.adapter import InstagramAdapter
    ig = InstagramAdapter()
    if not ig.is_configured:
        return False
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            loop.create_task(ig.send_button_template(recipient_igsid, text, buttons))
            return True
        else:
            return asyncio.run(ig.send_button_template(recipient_igsid, text, buttons))
    except Exception as e:
        logger.error(f"[Instagram Notification Button Template] Error sending to {recipient_igsid}: {e}")
        return False


def send_client_live_location(
    channel_user_id: str,
    latitude: float,
    longitude: float,
    live_period: int = 7200,
    channel: str | None = None,
    order_id: Any = None,
) -> int | None:
    """Send a live location pin or tracking card to the customer (Telegram, WhatsApp, Messenger, or Instagram)."""
    if not channel_user_id:
        return None

    from src.repositories import get_repository
    from src.repositories.identity_store import identity_store
    repo = get_repository()

    uid_str = str(channel_user_id).strip()
    clean_digits = re.sub(r"\D", "", uid_str)

    # Si el canal no vino explícito, intentar resolver desde identity_store
    if not channel and order_id:
        try:
            chan_info = identity_store.get_order_channel_info(order_id)
            if chan_info and chan_info.get("channel"):
                channel = chan_info.get("channel")
        except Exception:
            pass

    # 0. Si es Instagram
    if (channel and channel.lower() == "instagram"):
        driver_details = ""
        order_txt = f" #{order_id}" if order_id else ""
        dest_lat = None
        dest_lng = None
        if order_id:
            try:
                ord_obj = repo.get_order_by_id("petroil", order_id)
                if ord_obj:
                    dest_lat = getattr(ord_obj, "delivery_lat", None)
                    dest_lng = getattr(ord_obj, "delivery_lng", None)
                    if ord_obj.driver_id:
                        drv = repo.get_driver(ord_obj.driver_id)
                        if drv:
                            v_plate = getattr(drv, "vehicle_plate", "") or "Unidad de reparto"
                            d_phone = getattr(drv, "phone", "") or ""
                            phone_line = f"\n• 📞 *Teléfono chofer:* {d_phone}" if d_phone else ""
                            driver_details = f"• 👨‍✈️ *Chofer:* {drv.name}\n• 🚘 *Unidad:* {v_plate}{phone_line}\n\n"
            except Exception:
                pass

        settings = get_settings()
        base_url = (getattr(settings, "public_base_url", None) or os.getenv("PUBLIC_BASE_URL", "https://mask-explosion-bell-varied.trycloudflare.com")).rstrip("/")
        live_tracker_url = f"{base_url}/tracking/{order_id}" if order_id else None

        if dest_lat and dest_lng:
            gmaps_nav_url = f"https://www.google.com/maps/dir/?api=1&origin={latitude:.6f},{longitude:.6f}&destination={dest_lat:.6f},{dest_lng:.6f}&travelmode=driving"
        else:
            gmaps_nav_url = f"https://www.google.com/maps/dir/?api=1&destination={latitude:.6f},{longitude:.6f}&travelmode=driving"

        links_block = ""
        if live_tracker_url:
            links_block += f"\n\n🌐 *Monitor GPS en Vivo:*\n{live_tracker_url}"
        links_block += f"\n\n🗺️ *Ruta en Google Maps:*\n{gmaps_nav_url}"

        msg_tracking = (
            f"🚚 *¡Tu pedido{order_txt} va en camino a tu domicilio!* ⛽✨\n\n"
            f"{driver_details}"
            f"Tu repartidor ya inició su recorrido hacia tu domicilio. Puedes seguir su avance en tiempo real tocando las opciones abajo o usando los enlaces: 📍"
            f"{links_block}"
        )
        buttons = []
        if live_tracker_url:
            buttons.append({"type": "web_url", "title": "📍 Monitor GPS en Vivo", "url": live_tracker_url})
        buttons.append({"type": "web_url", "title": "🗺️ Abrir Google Maps", "url": gmaps_nav_url})

        ok = _send_instagram_button_template_sync(uid_str, msg_tracking, buttons[:2])
        if ok and order_id:
            from src.channels.instagram.adapter import InstagramAdapter
            _send_instagram_buttons_sync(
                uid_str,
                "💡 Si deseas consultar el estatus o cancelar este servicio, puedes pulsar:",
                InstagramAdapter().get_order_active_quick_replies(order_id),
            )
        logger.info(f"📍 [send_client_live_location] Instagram live tracking enviado a {uid_str} (order: {order_id}, url: {live_tracker_url or gmaps_nav_url}, ok: {ok})")
        return 777777 if ok else None

    # 0.1 Si es Messenger
    if (channel and channel.lower() == "messenger"):
        driver_details = ""
        order_txt = f" #{order_id}" if order_id else ""
        dest_lat = None
        dest_lng = None
        if order_id:
            try:
                ord_obj = repo.get_order_by_id("petroil", order_id)
                if ord_obj:
                    dest_lat = getattr(ord_obj, "delivery_lat", None)
                    dest_lng = getattr(ord_obj, "delivery_lng", None)
                    if ord_obj.driver_id:
                        drv = repo.get_driver(ord_obj.driver_id)
                        if drv:
                            v_plate = getattr(drv, "vehicle_plate", "") or "Unidad de reparto"
                            d_phone = getattr(drv, "phone", "") or ""
                            phone_line = f"\n• 📞 *Teléfono chofer:* {d_phone}" if d_phone else ""
                            driver_details = f"• 👨‍✈️ *Chofer:* {drv.name}\n• 🚘 *Unidad:* {v_plate}{phone_line}\n\n"
            except Exception:
                pass

        settings = get_settings()
        base_url = (getattr(settings, "public_base_url", None) or os.getenv("PUBLIC_BASE_URL", "https://mask-explosion-bell-varied.trycloudflare.com")).rstrip("/")
        live_tracker_url = f"{base_url}/tracking/{order_id}" if order_id else None

        if dest_lat and dest_lng:
            gmaps_nav_url = f"https://www.google.com/maps/dir/?api=1&origin={latitude:.6f},{longitude:.6f}&destination={dest_lat:.6f},{dest_lng:.6f}&travelmode=driving"
        else:
            gmaps_nav_url = f"https://www.google.com/maps/dir/?api=1&destination={latitude:.6f},{longitude:.6f}&travelmode=driving"

        links_block = ""
        if live_tracker_url:
            links_block += f"\n\n🌐 *Monitor GPS en Vivo:*\n{live_tracker_url}"
        links_block += f"\n\n🗺️ *Ruta en Google Maps:*\n{gmaps_nav_url}"

        msg_tracking = (
            f"🚚 *¡Tu pedido{order_txt} va en camino a tu domicilio!* ⛽✨\n\n"
            f"{driver_details}"
            f"Tu repartidor ya inició su recorrido hacia tu domicilio. Puedes seguir su avance en tiempo real tocando las opciones abajo o usando los enlaces: 📍"
            f"{links_block}"
        )
        buttons = []
        if live_tracker_url:
            buttons.append({"type": "web_url", "title": "📍 Monitor GPS en Vivo", "url": live_tracker_url})
        buttons.append({"type": "web_url", "title": "🗺️ Abrir Google Maps", "url": gmaps_nav_url})

        ok = _send_messenger_button_template_sync(uid_str, msg_tracking, buttons[:2])
        if ok and order_id:
            # Enviar botones como Quick Reply para que desaparezcan al entregarse el pedido
            from src.channels.messenger.adapter import MessengerAdapter
            _send_messenger_buttons_sync(
                uid_str,
                "💡 Si deseas consultar el estatus o cancelar este servicio, puedes pulsar:",
                MessengerAdapter().get_order_active_quick_replies(order_id),
            )
        logger.info(f"📍 [send_client_live_location] Messenger live tracking enviado a {uid_str} (order: {order_id}, url: {live_tracker_url or gmaps_nav_url}, ok: {ok})")
        return 888888 if ok else None

    # 1. Si es explícitamente WhatsApp o el ID corresponde a WhatsApp
    if (channel and channel.lower() == "whatsapp") or _is_whatsapp_channel(uid_str, channel):
        if not order_id:
            try:
                phone_cand = clean_digits or uid_str
                if len(phone_cand) >= 10:
                    recent_orders = repo.get_orders_by_customer_phone("petroil", phone_cand, limit=5)
                    for o in recent_orders:
                        if o.status in ("in_route", "assigned", "confirmed"):
                            order_id = o.id
                            break
            except Exception:
                pass

        # 1. Enviar pin interactivo de mapa de WhatsApp
        _send_whatsapp_location_sync(
            clean_digits or uid_str,
            latitude,
            longitude,
            name="📍 Repartidor en Camino (Gas Petroil)",
            address="Ruta en vivo hacia tu domicilio",
        )
        # 2. Enviar mensaje con enlace de seguimiento en tiempo real en Google Maps
        maps_url = f"https://www.google.com/maps?q={latitude:.6f},{longitude:.6f}"
        driver_details = ""
        order_txt = f" #{order_id}" if order_id else ""
        if order_id:
            try:
                ord_obj = repo.get_order_by_id("petroil", order_id)
                if ord_obj and ord_obj.driver_id:
                    drv = repo.get_driver(ord_obj.driver_id)
                    if drv:
                        v_plate = getattr(drv, "vehicle_plate", "") or "Unidad de reparto"
                        d_phone = getattr(drv, "phone", "") or ""
                        phone_line = f"\n• 📞 *Teléfono chofer:* {d_phone}" if d_phone else ""
                        driver_details = f"• 👨‍✈️ *Chofer:* {drv.name}\n• 🚘 *Unidad:* {v_plate}{phone_line}\n\n"
            except Exception:
                pass

        msg_tracking = (
            f"🚚 *¡Tu pedido{order_txt} va en camino a tu domicilio!* ⛽✨\n\n"
            f"{driver_details}"
            f"Tu repartidor ya inició su recorrido hacia tu domicilio. Puedes consultar su ubicación en el mapa en tiempo real. 📍\n\n"
            f"Mantente al pendiente para recibir tu gas."
        )
        if order_id:
            from src.channels.whatsapp.adapter import WhatsAppAdapter
            wa = WhatsAppAdapter()
            buttons = wa.get_order_active_buttons(order_id)
            _send_whatsapp_buttons_sync(clean_digits or uid_str, msg_tracking, buttons)
        else:
            _send_whatsapp_message_sync(clean_digits or uid_str, msg_tracking)
        return 999999

    # Telegram resolution
    tg_resolved = identity_store.get_telegram_chat_id(uid_str)
    if tg_resolved:
        uid_str = tg_resolved
        if not channel:
            channel = "telegram"
    elif hasattr(repo, "get_telegram_chat_id_for_phone"):
        tg_from_repo = repo.get_telegram_chat_id_for_phone(clean_digits)
        if tg_from_repo:
            uid_str = tg_from_repo
            if not channel:
                channel = "telegram"

    # Telegram
    settings = get_settings()
    token = settings.telegram_bot_token
    if not token:
        return None

    payload = {
        "chat_id": uid_str,
        "latitude": latitude,
        "longitude": longitude,
        "live_period": live_period,
    }
    resp = _send_telegram_api_call(token, "sendLocation", payload)
    if resp and resp.get("ok"):
        result = resp.get("result", {})
        msg_id = result.get("message_id")
        logger.info(f"📍 Ubicación en tiempo real compartida al cliente {uid_str} (msg_id: {msg_id})")
        return msg_id
    elif len(clean_digits) >= 10:
        _send_whatsapp_location_sync(clean_digits, latitude, longitude)
        return 999999
    return None


def edit_client_live_location(
    channel_user_id: str,
    message_id: int,
    latitude: float,
    longitude: float,
    channel: str | None = None,
) -> bool:
    """Update an existing live location pin in the customer's chat (Telegram live location edit, WhatsApp map update)."""
    if not channel_user_id:
        return False

    if (channel and channel.lower() in ("whatsapp", "messenger", "instagram")) or _is_whatsapp_channel(channel_user_id, channel) or message_id in (999999, 888888, 777777):
        # En WhatsApp, Messenger e Instagram confirmamos la recepción exitosa para no desconfigurar la orden en base de datos
        return True

    # Telegram
    settings = get_settings()
    token = settings.telegram_bot_token
    if not token or not message_id:
        return False

    payload = {
        "chat_id": channel_user_id,
        "message_id": message_id,
        "latitude": latitude,
        "longitude": longitude,
    }
    resp = _send_telegram_api_call(token, "editMessageLiveLocation", payload)
    if resp and resp.get("ok"):
        return True
    if resp and "message is not modified" in str(resp.get("description", "")).lower():
        return True
    return False


def remove_client_live_location(channel_user_id: str, message_id: int) -> bool:
    """Delete or stop the live location pin from the customer's chat."""
    if not channel_user_id or not message_id or message_id in (999999, 888888):
        return False

    settings = get_settings()
    token = settings.telegram_bot_token
    if not token:
        return False

    # 1. Intentar eliminar el mensaje por completo para limpiar el chat
    delete_payload = {
        "chat_id": channel_user_id,
        "message_id": message_id,
    }
    del_ok = _send_telegram_api(token, "deleteMessage", delete_payload)
    if del_ok:
        logger.info(f"🗑️ Mensaje de ubicación en vivo {message_id} eliminado del chat del cliente {channel_user_id}")
        return True

    # 2. Fallback: detener la transmisión si no se pudo borrar
    stop_payload = {
        "chat_id": channel_user_id,
        "message_id": message_id,
    }
    stop_ok = _send_telegram_api(token, "stopMessageLiveLocation", stop_payload)
    if stop_ok:
        logger.info(f"⏹️ Transmisión de ubicación en vivo {message_id} detenida en chat {channel_user_id}")
    return stop_ok


def cleanup_client_order_buttons(
    order_id: Any,
    chat_id: str | int | None = None,
    keep_message_id: int | None = None,
    tenant_id: str = "petroil",
) -> None:
    """
    Remove interactive Cancel buttons from previous client messages for an order,
    retaining only keep_message_id if provided (so only the latest message has the button).
    """
    if not order_id:
        return

    from src.repositories.identity_store import identity_store

    settings = get_settings()
    token = settings.telegram_bot_token
    if not token:
        return

    # Si se proporciona keep_message_id y chat_id, registrarlo primero para persistencia
    if keep_message_id and chat_id:
        identity_store.add_order_client_message(order_id, chat_id, keep_message_id)

    # Obtener mensajes previos a limpiar
    to_remove = identity_store.clear_order_client_messages(order_id, keep_message_id=keep_message_id)

    for item in to_remove:
        c_id = item.get("chat_id") or chat_id
        m_id = item.get("message_id")
        if not c_id or not m_id:
            continue
        if keep_message_id and int(m_id) == int(keep_message_id):
            continue

        markup_payload = {
            "chat_id": str(c_id),
            "message_id": int(m_id),
            "reply_markup": {"inline_keyboard": []},
        }
        _send_telegram_api(token, "editMessageReplyMarkup", markup_payload)
        logger.info(f"🧹 [cleanup_client_order_buttons] Botón Cancelar removido de mensaje {m_id} en chat {c_id} para Pedido #{order_id}")


def notify_client(
    channel_user_id: str,
    message: str,
    reply_markup: dict[str, Any] | None = None,
    channel: str | None = None,
) -> bool:
    """Send an automated notification to the customer via Client Bot (Telegram or WhatsApp)."""
    if not channel_user_id:
        return False

    from src.repositories import get_repository
    from src.repositories.identity_store import identity_store
    repo = get_repository()

    uid_str = str(channel_user_id).strip()
    clean_digits = re.sub(r"\D", "", uid_str)

    # Control de deduplicación contra ráfagas o doble clics rápidos
    now = time.time()
    if len(_RECENT_CLIENT_NOTIFICATIONS) > 1000:
        expired = [k for k, ts in _RECENT_CLIENT_NOTIFICATIONS.items() if now - ts > 60]
        for k in expired:
            _RECENT_CLIENT_NOTIFICATIONS.pop(k, None)

    msg_key = (clean_digits or uid_str, message.strip()[:100])
    if msg_key in _RECENT_CLIENT_NOTIFICATIONS and (now - _RECENT_CLIENT_NOTIFICATIONS[msg_key]) < 5:
        logger.info(f"📣 [notify_client] Notificación idéntica omitida por ráfaga rápida (<5s) para {uid_str}")
        return True
    _RECENT_CLIENT_NOTIFICATIONS[msg_key] = now


    m_lower = message.lower()
    order_match = re.search(r"(?:pedido|folio)\s*#?\s*(\d+)", message, re.IGNORECASE)
    is_terminal = any(k in m_lower for k in ["cancelado", "entregado", "califica", "encuesta"])
    if not reply_markup and order_match and not is_terminal:
        order_id = order_match.group(1)
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "❌ Cancelar Pedido", "callback_data": f"cancel_order_client:{order_id}"},
                ]
            ]
        }

    def _dispatch_wa_client_msg(target_phone: str, text: str) -> bool:
        if reply_markup and isinstance(reply_markup, dict):
            ikb = reply_markup.get("inline_keyboard", [])
            wa_buttons = []
            for row in ikb:
                for btn in row:
                    cb_data = btn.get("callback_data", "")
                    title = btn.get("text", "")
                    if cb_data and title:
                        wa_buttons.append({"id": cb_data, "title": title[:20]})
            if wa_buttons:
                return _send_whatsapp_buttons_sync(target_phone, text, wa_buttons[:3])
        return _send_whatsapp_message_sync(target_phone, text)

    def _dispatch_msgr_client_msg(target_psid: str, text: str) -> bool:
        if reply_markup and isinstance(reply_markup, dict):
            ikb = reply_markup.get("inline_keyboard", [])
            msgr_buttons = []
            for row in ikb:
                for btn in row:
                    cb_data = btn.get("callback_data", "")
                    title = btn.get("text", "")
                    if cb_data and title:
                        msgr_buttons.append({"id": cb_data, "title": title[:20]})
            if msgr_buttons:
                return _send_messenger_buttons_sync(target_psid, text, msgr_buttons[:3])
        return _send_messenger_message_sync(target_psid, text)

    def _dispatch_ig_client_msg(target_igsid: str, text: str) -> bool:
        if reply_markup and isinstance(reply_markup, dict):
            ikb = reply_markup.get("inline_keyboard", [])
            ig_buttons = []
            for row in ikb:
                for btn in row:
                    cb_data = btn.get("callback_data", "")
                    title = btn.get("text", "")
                    if cb_data and title:
                        ig_buttons.append({"id": cb_data, "title": title[:20]})
            if ig_buttons:
                return _send_instagram_buttons_sync(target_igsid, text, ig_buttons[:3])
        return _send_instagram_message_sync(target_igsid, text)

    # 0. Si es explícitamente Instagram, enviar directo
    if channel and channel.lower() == "instagram":
        return _dispatch_ig_client_msg(uid_str, message)

    # 0.1 Si es explícitamente Messenger, enviar directo
    if channel and channel.lower() == "messenger":
        return _dispatch_msgr_client_msg(uid_str, message)

    # 1. Si es explícitamente WhatsApp, enviar directo sin resolver Telegram
    if channel and channel.lower() == "whatsapp":
        wa_text = _format_markdown_for_whatsapp(message)
        return _dispatch_wa_client_msg(clean_digits or uid_str, wa_text)

    # 2. Si no viene canal explícito, verificar si es formato o registro WhatsApp
    if not channel and _is_whatsapp_channel(uid_str, channel):
        wa_text = _format_markdown_for_whatsapp(message)
        return _dispatch_wa_client_msg(clean_digits or uid_str, wa_text)

    # 3. Resolución de Chat ID de Telegram mediante almacén persistente o repo
    tg_resolved = identity_store.get_telegram_chat_id(uid_str)
    if tg_resolved:
        uid_str = tg_resolved
        if not channel:
            channel = "telegram"
    elif hasattr(repo, "get_telegram_chat_id_for_phone"):
        tg_from_repo = repo.get_telegram_chat_id_for_phone(clean_digits)
        if tg_from_repo:
            uid_str = tg_from_repo
            if not channel:
                channel = "telegram"

    if _is_whatsapp_channel(uid_str, channel):
        wa_text = _format_markdown_for_whatsapp(message)
        return _dispatch_wa_client_msg(clean_digits or uid_str, wa_text)

    # Telegram
    settings = get_settings()
    token = settings.telegram_bot_token
    if not token:
        logger.warning("[notify_client] No telegram_bot_token configured.")
        return False

    payload: dict[str, Any] = {
        "chat_id": uid_str,
        "text": message,
        "parse_mode": "Markdown",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    resp = _send_telegram_api_call(token, "sendMessage", payload)
    if not resp or not resp.get("ok"):
        payload.pop("parse_mode", None)
        resp = _send_telegram_api_call(token, "sendMessage", payload)

    ok = bool(resp and resp.get("ok"))
    if ok:
        logger.info(f"📣 [notify_client] Notificación enviada exitosamente por Telegram al cliente (chat_id: {uid_str})")
        new_msg_id = resp.get("result", {}).get("message_id")
        if order_match:
            o_id = order_match.group(1)
            if is_terminal:
                cleanup_client_order_buttons(o_id, chat_id=uid_str, keep_message_id=None)
            elif reply_markup and new_msg_id:
                cleanup_client_order_buttons(o_id, chat_id=uid_str, keep_message_id=new_msg_id)
        return True

    # Fallback automático a WhatsApp si Telegram falla y tenemos teléfono de 10+ dígitos
    if len(clean_digits) >= 10:
        logger.info(f"📣 [notify_client] Telegram no pudo entregar a {uid_str}, intentando fallback a WhatsApp {clean_digits[-10:]}")
        wa_text = _format_markdown_for_whatsapp(message)
        return _dispatch_wa_client_msg(clean_digits, wa_text)

    return False


def notify_driver(
    telegram_user_id: str,
    message: str,
    reply_markup: dict[str, Any] | None = None,
    lat: float | None = None,
    lng: float | None = None,
) -> bool:
    """Send an interactive notification and optional location to a driver via Driver Bot."""
    if not telegram_user_id:
        return False

    tid_str = str(telegram_user_id).strip()
    if not tid_str.isdigit():
        logger.debug(f"[notify_driver] Skipping non-numeric telegram_user_id: {telegram_user_id}")
        return False

    settings = get_settings()
    token = settings.telegram_driver_bot_token or settings.telegram_bot_token
    if not token:
        return False

    # 1. Send location pin ONLY if coordinates are valid and NOT the generic city center fallback
    is_fallback = (abs(lat - 23.2014) < 0.0001 and abs(lng - (-106.4215)) < 0.0001) if (lat and lng) else True
    if lat is not None and lng is not None and lat != 0.0 and lng != 0.0 and not is_fallback:
        loc_payload = {
            "chat_id": telegram_user_id,
            "latitude": lat,
            "longitude": lng,
        }
        _send_telegram_api(token, "sendLocation", loc_payload)

    # 2. Send message with interactive action buttons
    payload = {
        "chat_id": telegram_user_id,
        "text": message,
        "parse_mode": "Markdown",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    resp = _send_telegram_api_call(token, "sendMessage", payload)
    if not resp or not resp.get("ok"):
        # Retry without markdown if formatting was rejected by Telegram
        payload.pop("parse_mode", None)
        resp = _send_telegram_api_call(token, "sendMessage", payload)

    if resp and resp.get("ok"):
        return resp.get("result", {}).get("message_id")
    return None


def cleanup_driver_order_messages(
    tenant_id: str,
    order_id: int,
    driver_telegram_user_id: str,
) -> None:
    """Delete or strip buttons from all messages sent to the driver for this order."""
    if not driver_telegram_user_id:
        return
    settings = get_settings()
    token = settings.telegram_driver_bot_token or settings.telegram_bot_token
    if not token:
        return

    from src.repositories import get_repository
    repo = get_repository()
    try:
        msg_ids = repo.get_order_driver_message_ids(tenant_id, order_id)
    except Exception as e:
        logger.warning(f"Error fetching driver message ids: {e}")
        msg_ids = []

    if not msg_ids:
        return

    for mid in set(msg_ids):
        # 1. Intentar borrar el mensaje completo del chat del chofer
        del_payload = {
            "chat_id": driver_telegram_user_id,
            "message_id": mid,
        }
        del_ok = _send_telegram_api(token, "deleteMessage", del_payload)
        if not del_ok:
            # 2. Si no se puede borrar (más de 48h o permiso), remover los botones interactivos
            markup_payload = {
                "chat_id": driver_telegram_user_id,
                "message_id": mid,
                "reply_markup": {"inline_keyboard": []},
            }
            _send_telegram_api(token, "editMessageReplyMarkup", markup_payload)

    try:
        repo.clear_order_driver_message_ids(tenant_id, order_id)
    except Exception:
        pass


def notify_driver_order_cancelled(
    tenant_id: str,
    order_id: int,
    driver_telegram_user_id: str,
    customer_name: str = "",
    delivery_address: str = "",
    cancelled_by: str = "el cliente",
) -> bool:
    """Clean up active trip buttons and notify driver about cancellation."""
    # 1. Eliminar o deshabilitar todos los botones previos del viaje
    try:
        cleanup_driver_order_messages(tenant_id, order_id, driver_telegram_user_id)
    except Exception as e:
        logger.warning(f"Error cleaning driver messages for order {order_id}: {e}")

    # 2. Enviar alerta limpia de cancelación sin botones
    msg_driver = (
        f"❌ **PEDIDO #{order_id} CANCELADO**\n\n"
        f"👤 Cliente: {customer_name}\n"
        f"📍 Dirección: {delivery_address}\n\n"
        f"El pedido ha sido cancelado por {cancelled_by}. Ya no es necesario acudir al domicilio. Has quedado disponible para otros viajes."
    )
    res = notify_driver(driver_telegram_user_id, msg_driver)
    return bool(res)



def notify_delivery_survey(order_id: Any, tenant_id: str = "petroil") -> bool:
    """Send delivery completion notification and interactive driver rating survey to the customer (Telegram or WhatsApp)."""
    # Limpiar inmediatamente los botones de cancelar anteriores del cliente
    cleanup_client_order_buttons(order_id, keep_message_id=None)

    from src.repositories import get_repository
    repo = get_repository()
    order = repo.get_order_by_id(tenant_id, order_id)
    if not order:
        logger.warning(f"[Delivery Survey] Order #{order_id} not found.")
        return False

    recipient_id = str(order.channel_user_id or order.customer_phone or "").strip()
    from src.repositories.identity_store import identity_store
    eff_channel = getattr(order, "channel", "").lower()
    chan_info = identity_store.get_order_channel_info(order_id)
    if chan_info:
        if not eff_channel or eff_channel == "telegram":
            eff_channel = str(chan_info.get("channel", "")).lower() or eff_channel
        if not recipient_id or recipient_id == order.customer_phone:
            recipient_id = str(chan_info.get("channel_user_id", "")).strip() or recipient_id

    if not recipient_id:
        logger.warning(f"[Delivery Survey] Order #{order_id} has no channel_user_id or customer_phone.")
        return False

    driver_desc = ""
    driver_name_str = "tu repartidor"
    if order.driver_id:
        driver = repo.get_driver(order.driver_id)
        if driver:
            driver_name_str = driver.name
            v_plate = driver.vehicle_plate or (driver.unit_identifier if getattr(driver, "unit_identifier", None) else "")
            plate_info = f" ({v_plate})" if v_plate else ""
            driver_desc = f"\n👨‍✈️ *Repartidor:* {driver.name}{plate_info}\n"

    # Si el cliente proviene de Instagram
    if eff_channel == "instagram":
        try:
            from src.channels.instagram.adapter import InstagramAdapter
            ig_adapter = InstagramAdapter()
            if ig_adapter.is_configured:
                msg_ig = (
                    f"📦 **¡Tu pedido #{order_id} ha sido entregado exitosamente!**\n\n"
                    f"💰 **Total pagado:** ${order.total_amount:.2f} {order.currency} ({order.payment_method})"
                    f"{driver_desc}\n"
                    "🌟 **¿Cómo calificarías el servicio y la atención de tu repartidor?**\n"
                    "Por favor selecciona tu calificación tocando el botón a continuación (1 a 5 estrellas):"
                )
                buttons = [
                    {"id": f"rate:{order_id}:5", "title": "⭐⭐⭐⭐⭐ Excelente"},
                    {"id": f"rate:{order_id}:4", "title": "⭐⭐⭐⭐ Muy Bueno"},
                    {"id": f"rate:{order_id}:3", "title": "⭐⭐⭐ Regular"},
                    {"id": f"rate:{order_id}:2", "title": "⭐⭐ Malo"},
                    {"id": f"rate:{order_id}:1", "title": "⭐ Muy Malo"},
                ]
                return _send_instagram_buttons_sync(recipient_id, msg_ig, buttons)
        except Exception as e:
            logger.error(f"[Instagram Survey] Exception: {e}")
            return False

    # Si el cliente proviene de Messenger
    if eff_channel == "messenger":
        try:
            from src.channels.messenger.adapter import MessengerAdapter
            msgr_adapter = MessengerAdapter()
            if msgr_adapter.is_configured:
                msg_msgr = (
                    f"📦 **¡Tu pedido #{order_id} ha sido entregado exitosamente!**\n\n"
                    f"💰 **Total pagado:** ${order.total_amount:.2f} {order.currency} ({order.payment_method})"
                    f"{driver_desc}\n"
                    "🌟 **¿Cómo calificarías el servicio y la atención de tu repartidor?**\n"
                    "Por favor selecciona tu calificación tocando el botón a continuación (1 a 5 estrellas):"
                )
                buttons = [
                    {"id": f"rate:{order_id}:5", "title": "⭐⭐⭐⭐⭐ Excelente"},
                    {"id": f"rate:{order_id}:4", "title": "⭐⭐⭐⭐ Muy Bueno"},
                    {"id": f"rate:{order_id}:3", "title": "⭐⭐⭐ Regular"},
                    {"id": f"rate:{order_id}:2", "title": "⭐⭐ Malo"},
                    {"id": f"rate:{order_id}:1", "title": "⭐ Muy Malo"},
                ]
                return _send_messenger_buttons_sync(recipient_id, msg_msgr, buttons)
        except Exception as e:
            logger.error(f"[Messenger Survey] Exception: {e}")
            return False

    # Si el cliente proviene de WhatsApp
    if getattr(order, "channel", "").lower() == "whatsapp" or _is_whatsapp_channel(recipient_id, getattr(order, "channel", None)):
        try:
            from src.channels.whatsapp.adapter import WhatsAppAdapter
            wa_adapter = WhatsAppAdapter()
            if wa_adapter.is_configured:
                msg_wa = (
                    f"📦 *¡Tu pedido #{order_id} ha sido entregado exitosamente!*\n\n"
                    f"💰 *Total pagado:* ${order.total_amount:.2f} {order.currency} ({order.payment_method})"
                    f"{driver_desc}\n"
                    "🌟 *¿Cómo calificarías el servicio y la atención de tu repartidor?*\n"
                    "Por favor selecciona tu calificación tocando el botón a continuación (1 a 5 estrellas):"
                )
                
                # Lista interactiva completa de 5 estrellas (como en Telegram)
                sections = [{
                    "title": "Calificación del Repartidor",
                    "rows": [
                        {"id": f"rate_driver:{order_id}:5", "title": "⭐⭐⭐⭐⭐ 5 Estrellas", "description": f"Excelente servicio de {driver_name_str}"},
                        {"id": f"rate_driver:{order_id}:4", "title": "⭐⭐⭐⭐ 4 Estrellas", "description": "Buen servicio"},
                        {"id": f"rate_driver:{order_id}:3", "title": "⭐⭐⭐ 3 Estrellas", "description": "Servicio regular"},
                        {"id": f"rate_driver:{order_id}:2", "title": "⭐⭐ 2 Estrellas", "description": "Malo / Inconforme"},
                        {"id": f"rate_driver:{order_id}:1", "title": "⭐ 1 Estrella", "description": "Muy mala experiencia"},
                    ]
                }]
                
                # 1. Intentar enviar con lista interactiva de 5 estrellas
                try:
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        loop = None
                    if loop and loop.is_running():
                        loop.create_task(wa_adapter.send_interactive_list(
                            recipient_wa_id=recipient_id,
                            body_text=msg_wa,
                            button_label="⭐ Calificar Repartidor",
                            sections=sections,
                        ))
                        return True
                    else:
                        ok_list = asyncio.run(wa_adapter.send_interactive_list(
                            recipient_wa_id=recipient_id,
                            body_text=msg_wa,
                            button_label="⭐ Calificar Repartidor",
                            sections=sections,
                        ))
                        if ok_list:
                            return True
                except Exception as ex:
                    logger.warning(f"[WhatsApp Survey] Interactive list failed, trying buttons: {ex}")

                # 2. Intentar con botones rápidos (3 opciones)
                buttons = [
                    {"id": f"rate_driver:{order_id}:5", "title": "⭐ 5 Excelente"},
                    {"id": f"rate_driver:{order_id}:4", "title": "⭐ 4 Bueno"},
                    {"id": f"rate_driver:{order_id}:3", "title": "⭐ 1-3 Regular"},
                ]
                try:
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        loop = None
                    if loop and loop.is_running():
                        loop.create_task(wa_adapter.send_interactive_buttons(recipient_id, msg_wa, buttons))
                        return True
                    else:
                        ok_btn = asyncio.run(wa_adapter.send_interactive_buttons(recipient_id, msg_wa, buttons))
                        if ok_btn:
                            return True
                except Exception as ex:
                    logger.warning(f"[WhatsApp Survey] Interactive buttons failed: {ex}")

                # 3. Fallback garantizado: enviar confirmación de entrega y encuesta en texto plano
                msg_wa_text = (
                    f"📦 *¡Tu pedido #{order_id} ha sido entregado exitosamente!*\n\n"
                    f"💰 *Total pagado:* ${order.total_amount:.2f} {order.currency} ({order.payment_method})"
                    f"{driver_desc}\n"
                    "🌟 *¿Cómo calificarías la atención de tu repartidor?*\n"
                    "Por favor responde a este mensaje con un número del 1 al 5:\n\n"
                    "5️⃣ ⭐⭐⭐⭐⭐ Excelente\n"
                    "4️⃣ ⭐⭐⭐⭐ Bueno\n"
                    "3️⃣ ⭐⭐⭐ Regular\n"
                    "2️⃣ ⭐⭐ Malo\n"
                    "1️⃣ ⭐ Muy malo"
                )
                return _send_whatsapp_message_sync(recipient_id, msg_wa_text)
        except Exception as e:
            logger.error(f"[WhatsApp Survey] Exception: {e}")
            return False

    # Interactive Inline Keyboard with 5 stars (Telegram)
    driver_desc_tg = driver_desc.replace("*", "**")
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "⭐ 1", "callback_data": f"rate_driver:{order_id}:1"},
                {"text": "⭐ 2", "callback_data": f"rate_driver:{order_id}:2"},
                {"text": "⭐ 3", "callback_data": f"rate_driver:{order_id}:3"},
                {"text": "⭐ 4", "callback_data": f"rate_driver:{order_id}:4"},
                {"text": "⭐ 5", "callback_data": f"rate_driver:{order_id}:5"},
            ]
        ]
    }

    msg_cliente = (
        f"📦 **¡Tu pedido #{order_id} ha sido entregado exitosamente!**\n\n"
        f"💰 **Total pagado:** ${order.total_amount:.2f} {order.currency} ({order.payment_method})"
        f"{driver_desc_tg}\n"
        "🌟 **¿Cómo calificarías el servicio y la atención de tu repartidor?**\n"
        "Por favor califícalo tocando una de las estrellas a continuación (1 a 5):"
    )

    return notify_client(recipient_id, msg_cliente, reply_markup=reply_markup, channel="telegram")

