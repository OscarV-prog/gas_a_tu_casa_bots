"""Tool: Cancel a customer order and notify the assigned driver if applicable."""

from __future__ import annotations

import logging
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from src.repositories import get_repository
from src.services.notifications import notify_driver

logger = logging.getLogger(__name__)


@tool
def cancel_order(
    order_id: int,
    reason: str = "Cancelado por el cliente",
    config: RunnableConfig = None,
) -> str:
    """Cancel an active or pending customer order in the system.

    Use this tool when the customer explicitly asks to cancel an existing order.

    Args:
        order_id: The ID / folio number of the order to cancel (e.g. 29).
        reason: Optional reason for cancellation provided by the customer.
    """
    configurable = config.get("configurable", {}) if config else {}
    tenant_id = configurable.get("tenant_id", "petroil")
    channel = configurable.get("channel", "telegram")
    channel_user_id = str(configurable.get("channel_user_id", ""))

    repo = get_repository()
    order = repo.get_order_by_id(tenant_id, order_id)

    if not order:
        return f"No se encontró ningún pedido con el folio #{order_id}."

    # Control de Autorización y Privacidad (BOLA/IDOR):
    # Verificar que el pedido pertenezca al usuario del canal en sesión activa
    if channel and channel_user_id and channel_user_id not in ("admin_manual", "dashboard", "cli_user"):
        import re
        bound_customer = repo.get_customer(tenant_id, channel, channel_user_id)
        clean_bound = re.sub(r"\D", "", bound_customer.phone) if (bound_customer and bound_customer.phone) else ""
        if not clean_bound and len(re.sub(r"\D", "", channel_user_id)) >= 10:
            clean_bound = re.sub(r"\D", "", channel_user_id)[-10:]

        clean_order_phone = re.sub(r"\D", "", order.customer_phone or "")
        if clean_order_phone and clean_bound and clean_order_phone[-10:] != clean_bound[-10:]:
            return (
                f"⛔ ACCESO DENEGADO: Por políticas de seguridad y privacidad, no puedes cancelar pedidos "
                f"que no pertenezcan a tu número telefónico registrado."
            )

    if order.status == "delivered":
        return f"El pedido #{order_id} ya fue entregado y no puede ser cancelado."

    if order.status == "cancelled":
        return f"El pedido #{order_id} ya se encuentra cancelado."

    # Cancel order in DB and release driver
    cancelled_order = repo.cancel_order(tenant_id, order_id, cancelled_by="el cliente", reason=reason)

    # Limpiar botones interactivos del cliente
    from src.services.notifications import cleanup_client_order_buttons
    cleanup_client_order_buttons(order_id, tenant_id=tenant_id, keep_message_id=None)

    # If driver was assigned and has telegram, notify them immediately
    if order.driver_id:
        driver = repo.get_driver(order.driver_id)
        if driver and driver.telegram_user_id:
            msg_driver = (
                f"❌ **PEDIDO #{order_id} CANCELADO**\n\n"
                f"👤 Cliente: {order.customer_name}\n"
                f"📍 Dirección: {order.delivery_address}\n"
                f"📝 Motivo: {reason}\n\n"
                "El cliente ha cancelado este pedido. Ya no es necesario acudir al domicilio. Has quedado disponible para otros viajes."
            )
            notify_driver(driver.telegram_user_id, msg_driver)

    return (
        f"✅ El pedido con folio #{order_id} ha sido CANCELADO exitosamente.\n"
        f"Confirma al cliente que su pedido #{order_id} quedó cancelado sin ningún cargo."
    )
