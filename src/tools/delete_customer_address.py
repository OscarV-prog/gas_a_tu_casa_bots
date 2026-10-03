"""Tool: Delete a saved delivery address from customer profile in SQLite."""

from __future__ import annotations

import logging
import re
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from src.repositories import get_repository

logger = logging.getLogger(__name__)


@tool
def delete_customer_address(
    address_identifier: str,
    phone: str = "",
    confirm: bool = False,
    config: RunnableConfig = None,
) -> str:
    """Delete a saved delivery address from the customer's account in SQLite.

    Use this tool when the customer asks to delete, remove or borrar a saved delivery address
    (e.g., "elimina la dirección 2", "borra mi dirección de Misión San Javier", "eliminar dirección").
    Always require explicit confirmation before deleting. If the customer has not explicitly
    said "sí, elimínala", "confirmo", or similar, do not set confirm=True.

    Args:
        address_identifier: The address number/index (e.g. "1", "2", "7") or text matching the address/alias to delete.
        phone: Optional customer phone number. If omitted, it will use the conversation channel context.
        confirm: Set to True only when the customer has explicitly confirmed they want to delete this specific address.
    """
    configurable = config.get("configurable", {}) if config else {}
    tenant_id = configurable.get("tenant_id", "petroil")
    channel = configurable.get("channel", "telegram")
    channel_user_id = str(configurable.get("channel_user_id", ""))

    repo = get_repository()
    cust = None

    if phone:
        clean_phone = re.sub(r"\D", "", phone)
        if len(clean_phone) >= 7:
            cust = repo.get_customer_by_phone(tenant_id, clean_phone)

    if not cust and channel and channel_user_id:
        cust = repo.get_customer(tenant_id, channel, channel_user_id)
        if not cust:
            clean_uid = re.sub(r"\D", "", channel_user_id)
            if len(clean_uid) >= 10:
                cust = repo.get_customer_by_phone(tenant_id, clean_uid[-10:])

    if not cust:
        return "⚠️ No se pudo localizar tu cuenta de cliente para eliminar la dirección. Por favor indícame tu número de celular registrado."

    addresses = cust.addresses or []
    if not addresses:
        return "ℹ️ No tienes ninguna dirección guardada en tu cuenta actualmente."

    target_addr = None
    clean_id = str(address_identifier).strip()

    # 1. Si es un número (ej. "1", "2", "7"), buscar por posición en la lista (1-indexed)
    if clean_id.isdigit():
        idx = int(clean_id)
        if 1 <= idx <= len(addresses):
            target_addr = addresses[idx - 1]
        else:
            # Intentar también por ID de base de datos
            target_addr = next((a for a in addresses if a.id == idx), None)

    # 2. Si es texto o no se encontró por índice, buscar por coincidencia de texto o alias
    if not target_addr:
        target_lower = clean_id.lower()
        # Quitar palabras comunes
        target_lower = re.sub(r"^(?:la|el|mi|dirección|direccion|número|numero|#)\s*", "", target_lower).strip()
        for a in addresses:
            if target_lower in a.address.lower() or (a.alias and target_lower in a.alias.lower()):
                target_addr = a
                break

    if not target_addr:
        return (
            f"⚠️ No se encontró la dirección '{address_identifier}' en tus direcciones guardadas. "
            f"Cuentas con {len(addresses)} dirección(es) guardada(s)."
        )

    # Validar confirmación explícita antes de borrar
    if not confirm:
        return (
            f"⚠️ ¿Estás seguro de que deseas eliminar la dirección '{target_addr.address}' de tu cuenta?\n\n"
            "Esta acción no se puede deshacer. Por favor confírmame respondiendo 'Sí, confirmar' para proceder a borrarla o indícame si deseas conservar tu dirección."
        )

    # Proceder a eliminar la dirección tras confirmación
    success = repo.delete_customer_address(cust.id, target_addr.id)
    if not success:
        return f"⚠️ Ocurrió un error al intentar eliminar la dirección '{target_addr.address}'."

    remaining = repo.get_customer_addresses(cust.id)
    num_rem = len(remaining)

    return (
        f"✅ La dirección '{target_addr.address}' ha sido eliminada exitosamente de tu cuenta. "
        f"Ahora tienes {num_rem} dirección(es) guardada(s) en tu perfil."
    )
