import re
from typing import Any
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from src.models.order import Order
from src.repositories import get_repository


def _to_safe_order_display(order: Order, repo: Any = None) -> str:
    """Format order summary securely without exposing full physical address or sensitive PII."""
    status_map = {
        "pending": "⏳ Pendiente",
        "confirmed": "✅ Confirmado (Coordinando con Torre de Control)",
        "scheduled": "🗓️ Programado para fecha/horario posterior",
        "assigned": "🛻 Asignado a Chofer",
        "in_route": "🚚 En ruta / camino a tu domicilio",
        "delivered": "📦 Entregado",
        "cancelled": "❌ Cancelado",
        "rejected_by_driver": "⚠️ Reasignando unidad de reparto",
    }
    status_str = status_map.get(order.status, order.status)
    lines = [
        f"📋 **Pedido #{order.id}**",
        f"• **Estado:** {status_str}",
        f"• **Horario programado:** {order.delivery_schedule}",
    ]

    if repo is None:
        from src.repositories import get_repository
        repo = get_repository()

    driver = repo.get_driver(order.driver_id) if getattr(order, "driver_id", None) else None
    driver_name = (driver.name if driver else None) or getattr(order, "driver_name", None)

    if driver_name and order.status in ("assigned", "in_route", "delivered"):
        lines.append(f"• 👨‍✈️ **Chofer asignado:** {driver_name}")
        if driver:
            if driver.vehicle_plate:
                lines.append(f"• 🚘 **Unidad:** {driver.vehicle_plate}")
            if driver.phone:
                lines.append(f"• 📞 **Teléfono del chofer:** `{driver.phone}`")

    # Si el pedido está activo (en ruta o asignado), incluir mapa o estado de ubicación
    if order.status in ("in_route", "assigned"):
        d_lat = getattr(driver, "current_lat", None) if driver else None
        d_lng = getattr(driver, "current_lng", None) if driver else None
        if d_lat and d_lng:
            maps_url = f"https://www.google.com/maps?q={d_lat:.6f},{d_lng:.6f}"
            lines.append(f"• 🗺️ **Ubicación en tiempo real del chofer:**\n  {maps_url}")
        elif order.status == "in_route":
            lines.append("• 📍 **Ubicación:** Tu chofer va en trayecto hacia tu dirección.")

    if order.items:
        lines.append("• **Productos:**")
        for it in order.items:
            lines.append(f"  - {it.quantity}x {it.product_name} (${it.unit_price:.2f} c/u)")

    lines.append(f"• **Total:** ${order.total_amount:.2f} {order.currency}")
    return "\n".join(lines)


@tool
def get_order_status(
    order_id: int | str | None = None,
    phone: str = "",
    config: RunnableConfig = None,
) -> str:
    """Check the status and details of an existing customer order.

    Use this tool when a customer asks about their order status (e.g. "¿Cómo va mi pedido?",
    "Quiero rastrear mi folio 5", "Revisar pedido con mi teléfono").

    Args:
        order_id: Order ID or Folio (e.g. 1, 2, "ORD-PETR-0062").
        phone: Customer phone number to search for recent orders.
    """
    configurable = config.get("configurable", {}) if config else {}
    tenant_id = configurable.get("tenant_id", "petroil")
    channel = configurable.get("channel", "telegram")
    channel_user_id = str(configurable.get("channel_user_id", ""))
    repo = get_repository()

    # 1. Detectar si el usuario intenta consultar múltiples números a la vez
    if phone and (len(re.findall(r"\b\d{7,12}\b", phone)) > 1 or any(sep in phone for sep in [",", ";", " y ", " and "])):
        return (
            "⛔ ACCESO DENEGADO: Por políticas de privacidad y seguridad, no puedes consultar información de múltiples números de teléfono. "
            "Informa cordialmente al usuario que no puedes procesar consultas de números ajenos ni acceder arbitrariamente a datos, "
            "y recuérdale tus funciones de atención al cliente (Realizar pedido, Consultar su propio pedido o Cancelar)."
        )

    # 2. Control de Acceso: Verificar si el usuario ya está vinculado a un teléfono en su canal
    if channel and channel_user_id and channel_user_id not in ("admin_manual", "dashboard", "cli_user"):
        bound_customer = repo.get_customer(tenant_id, channel, channel_user_id)
        if bound_customer and bound_customer.phone:
            clean_bound = re.sub(r"\D", "", bound_customer.phone)
            if phone:
                clean_query = re.sub(r"\D", "", phone)
                clean_q_10 = clean_query[-10:] if len(clean_query) >= 10 else clean_query
                clean_b_10 = clean_bound[-10:] if len(clean_bound) >= 10 else clean_bound
                if clean_query and len(clean_query) >= 7 and clean_q_10 != clean_b_10:
                    return (
                        "⛔ ACCESO DENEGADO: Por políticas de privacidad y seguridad, no tienes autorización para consultar pedidos de otros números telefónicos. "
                        "Informa cordialmente al usuario que solo puedes consultar pedidos de su propia cuenta vinculada."
                    )

    search_phone = phone
    if not order_id and not search_phone and channel and channel_user_id:
        bound_customer = repo.get_customer(tenant_id, channel, channel_user_id)
        if bound_customer and bound_customer.phone:
            search_phone = bound_customer.phone
        elif len(re.sub(r"\D", "", channel_user_id)) >= 10:
            search_phone = re.sub(r"\D", "", channel_user_id)[-10:]

    if order_id:
        try:
            order = repo.get_order_by_id(tenant_id, order_id)
            if not order:
                return f"No se encontró ningún pedido con el folio #{order_id}."

            # Verificar si el pedido pertenece al usuario en sesión
            if channel and channel_user_id and channel_user_id not in ("admin_manual", "dashboard", "cli_user"):
                bound_customer = repo.get_customer(tenant_id, channel, channel_user_id)
                clean_bound = re.sub(r"\D", "", bound_customer.phone) if (bound_customer and bound_customer.phone) else ""
                if not clean_bound and len(re.sub(r"\D", "", channel_user_id)) >= 10:
                    clean_bound = re.sub(r"\D", "", channel_user_id)[-10:]

                clean_order_phone = re.sub(r"\D", "", order.customer_phone or "")
                if clean_order_phone and clean_bound and clean_order_phone[-10:] != clean_bound[-10:]:
                    return f"No se encontró ningún pedido con el folio #{order_id} asociado a tu cuenta."

            return f"Información de tu pedido #{order.id}:\n\n{_to_safe_order_display(order, repo)}"
        except Exception as e:
            return f"Error al buscar el pedido #{order_id}: {e}"

    if search_phone:
        orders = repo.get_orders_by_customer_phone(tenant_id, search_phone)
        if not orders:
            return f"No se encontraron pedidos registrados con el teléfono proporcionado ({search_phone})."

        # Priorizar pedidos activos (assigned, in_route, confirmed, pending, scheduled)
        active_orders = [o for o in orders if o.status in ("in_route", "assigned", "confirmed", "pending", "scheduled")]
        if active_orders:
            latest = active_orders[0]
            header = f"🚚 **¡Tienes un pedido activo en curso (#{latest.id})!**\n\n"
            detail = _to_safe_order_display(latest, repo)
            if len(active_orders) > 1:
                detail += f"\n\n*(Tienes {len(active_orders)} pedidos activos registrados)*"
            return header + detail
        else:
            latest = orders[0]
            header = "ℹ️ **No tienes pedidos activos en curso.** Tu último pedido registrado fue:\n\n"
            return header + _to_safe_order_display(latest, repo)

    return "Por favor proporciona el número de folio de tu pedido para consultar su estatus."


def format_clean_driver_status(order: Any, repo: Any = None) -> str:
    """Genera un reporte conciso y no redundante del estatus del chofer y del viaje."""
    if not order:
        return "⚠️ Pedido no encontrado."

    if repo is None:
        from src.repositories import get_repository
        repo = get_repository()

    status_raw = str(getattr(order, "status", "")).lower()

    if status_raw == "delivered":
        return (
            f"✅ **Pedido #{order.id} — Entregado**\n\n"
            "Tu pedido ya ha sido entregado exitosamente. ¡Muchas gracias por tu compra con Petroil Gas! ⛽✨"
        )
    elif status_raw in ("cancelled", "cancelado"):
        return (
            f"❌ **Pedido #{order.id} — Cancelado**\n\n"
            "Este pedido se encuentra cancelado. Puedes solicitar un nuevo servicio cuando lo requieras. ⛽"
        )

    # Buscar chofer asignado
    driver = None
    driver_id = getattr(order, "driver_id", None)
    if driver_id:
        driver = repo.get_driver(driver_id)

    driver_name = (driver.name if driver else None) or getattr(order, "driver_name", None)
    driver_phone = (driver.phone if driver else None) or getattr(order, "driver_phone", None)
    unit_label = getattr(driver, "vehicle_plate", None) or getattr(order, "truck_plate", None) or "Unidad de Reparto"

    # Caso A: Chofer asignado o en ruta
    if status_raw in ("in_route", "assigned") and driver_name:
        status_label = "🚚 **En camino a tu domicilio**" if status_raw == "in_route" else "🛻 **Unidad asignada (Preparando salida)**"
        lines = [
            f"📍 **Estatus de tu Pedido #{order.id}**",
            "",
            f"• **Estado:** {status_label}",
            f"• 👨‍✈️ **Chofer:** {driver_name}",
            f"• 🚘 **Unidad:** {unit_label}",
        ]
        if driver_phone:
            lines.append(f"• 📞 **Teléfono de contacto:** `{driver_phone}`")

        # Coordenadas / GPS
        d_lat = getattr(driver, "current_lat", None) if driver else None
        d_lng = getattr(driver, "current_lng", None) if driver else None
        if d_lat and d_lng:
            maps_url = f"https://www.google.com/maps?q={d_lat:.6f},{d_lng:.6f}"
            lines.append(f"• 🗺️ **Rastreo GPS en vivo:** {maps_url}")
        elif status_raw == "in_route":
            lines.append("• 📍 Tu chofer va en trayecto. Te avisaremos en cuanto esté en tu puerta.")

        lines.append("\n*(Te notificaremos cualquier actualización de tu reparto)* ⛽✨")
        return "\n".join(lines)

    # Caso B: Pedido programado para horario futuro
    if status_raw in ("scheduled", "programado"):
        sched = getattr(order, "delivery_schedule", "") or "Fecha programada"
        return (
            f"🗓️ **Estatus de tu Pedido #{order.id}**\n\n"
            "• **Estado:** 🕒 Programado en agenda\n"
            f"• **Horario asignado:** {sched}\n\n"
            "La Torre de Control asignará tu unidad cercana antes del horario pactado. Te enviaremos los datos de tu chofer en cuanto inicie su ruta. ⛽✨"
        )

    # Caso C: Confirmado / En coordinación con Torre de Control
    sched = getattr(order, "delivery_schedule", "") or "Lo antes posible"
    return (
        f"📍 **Estatus de tu Pedido #{order.id}**\n\n"
        "• **Estado:** ✅ **Confirmado**\n"
        f"• **Horario:** {sched}\n"
        "• 🚨 **Estatus de unidad:** Estamos coordinando con la unidad de reparto más cercana a tu colonia. En breve recibirás los datos de tu chofer y unidad. ⛽✨"
    )

