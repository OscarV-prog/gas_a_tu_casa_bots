"""Tool: check delivery schedule slot availability and driver capacity."""

from __future__ import annotations

import logging
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from src.services.schedule_manager import check_schedule_availability as check_slot

logger = logging.getLogger(__name__)


@tool
def check_schedule_availability(
    requested_schedule: str,
    config: RunnableConfig = None,
) -> str:
    """Verifica si un horario de entrega solicitado tiene cupo disponible según la flota de choferes.

    Llama a esta herramienta cuando el cliente pida programar su entrega en un día y hora específicos
    (ej. 'Hoy a las 5:00 PM', 'Mañana a las 10:30 AM', 'a las 4', etc.).

    Si el horario solicitado está lleno (cupo completo de choferes), la herramienta buscará y propondrá
    automáticamente el siguiente horario libre (intervalos de 30 minutos, ej. 5:30 PM).

    Args:
        requested_schedule: Horario o momento indicado por el cliente (ej. 'Hoy a las 5:00 PM', 'Lo antes posible').
    """
    configurable = config.get("configurable", {}) if config else {}
    tenant_id = configurable.get("tenant_id", "petroil")

    res = check_slot(requested_schedule, tenant_id=tenant_id)

    if res.get("is_asap"):
        return "El cliente solicita entrega 'Lo antes posible'. Este horario es inmediato y no requiere reserva de cupo por horario."

    if not res.get("is_valid_schedule"):
        return (
            f"No se pudo determinar una fecha u hora válida a partir de '{requested_schedule}'. "
            "Por favor pide al cliente que especifique la hora y el día deseado (ej. 'Hoy a las 5:00 PM')."
        )

    if res.get("is_available"):
        req_disp = res.get("requested_display")
        occ = res.get("occupied", 0)
        cap = res.get("capacity", 1)
        return (
            f"DISPONIBLE: El horario '{req_disp}' tiene cupo libre para entrega "
            f"({occ}/{cap} pedidos reservados). "
            f"Puedes confirmar al cliente que se programará para '{req_disp}' y continuar con el siguiente paso (método de pago)."
        )

    # Cupo lleno
    req_disp = res.get("requested_display")
    occ = res.get("occupied", 0)
    cap = res.get("capacity", 1)
    next_disp = res.get("next_available_display")

    return (
        f"CUPO LLENO: Para '{req_disp}' ya no hay choferes disponibles "
        f"({occ}/{cap} pedidos asignados al límite de choferes). "
        f"El siguiente horario más cercano con cupo disponible es '{next_disp}'. "
        f"Instrucción para el asistente: Explica cordialmente al cliente que para '{req_disp}' el cupo de choferes ya está completo, "
        f"ofrécele programarlo para '{next_disp}' y pregúntale si está de acuerdo o si prefiere indicar otro horario."
    )
