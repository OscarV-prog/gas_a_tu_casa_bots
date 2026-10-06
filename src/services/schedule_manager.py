"""Service: Schedule Capacity & Driver Slot Manager.

Calculates driver capacity per 30-minute delivery slot and finds next available
delivery windows when a requested time slot is at maximum capacity.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

from src.repositories import get_repository
from src.repositories.sqlite_repo import parse_schedule_deadline

logger = logging.getLogger(__name__)

SLOT_INTERVAL_MINUTES = 30


def normalize_to_slot_dt(dt: datetime) -> datetime:
    """Normalize a datetime to the closest 30-minute delivery slot window.

    e.g. 17:05 -> 17:00, 17:20 -> 17:30, 17:45 -> 18:00
    """
    minute = dt.minute
    if minute < 15:
        normalized_minute = 0
        added_hours = 0
    elif minute < 45:
        normalized_minute = 30
        added_hours = 0
    else:
        normalized_minute = 0
        added_hours = 1

    base = dt.replace(minute=normalized_minute, second=0, microsecond=0)
    if added_hours > 0:
        base += timedelta(hours=added_hours)
    return base


def format_slot_display(dt: datetime, ref_time: datetime | None = None) -> str:
    """Format a slot datetime in friendly Spanish format.

    e.g. 'Hoy a las 5:00 PM', 'Mañana a las 11:30 AM', 'Lunes 28/09 a las 4:00 PM'
    """
    ref = ref_time or datetime.now()
    is_today = dt.date() == ref.date()
    is_tomorrow = dt.date() == (ref.date() + timedelta(days=1))

    if is_today:
        day_label = "Hoy"
    elif is_tomorrow:
        day_label = "Mañana"
    else:
        dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        day_label = f"{dias[dt.weekday()]} {dt.strftime('%d/%m')}"

    # Format 12-hour time without leading zero
    hour_12 = dt.hour % 12
    if hour_12 == 0:
        hour_12 = 12
    meridiem = "AM" if dt.hour < 12 else "PM"
    time_label = f"{hour_12}:{dt.minute:02d} {meridiem}"

    return f"{day_label} a las {time_label}"


def format_time_only(dt: datetime) -> str:
    """Format time only (e.g. '5:30 PM')."""
    hour_12 = dt.hour % 12
    if hour_12 == 0:
        hour_12 = 12
    meridiem = "AM" if dt.hour < 12 else "PM"
    return f"{hour_12}:{dt.minute:02d} {meridiem}"


_SCHEDULE_CACHE: dict[str, Any] = {}


def get_slot_capacity(tenant_id: str = "petroil") -> int:
    """Calculate slot order capacity based on the number of registered drivers.

    The capacity per 30-minute time slot equals the number of drivers available/registered.
    """
    now_ts = datetime.now().timestamp()
    cache_key = f"capacity:{tenant_id}"
    cached = _SCHEDULE_CACHE.get(cache_key)
    if cached and (now_ts - cached["ts"] < 15):
        return cached["val"]

    try:
        repo = get_repository()
        drivers = repo.get_all_drivers(tenant_id)
        if drivers:
            val = max(1, len(drivers))
            _SCHEDULE_CACHE[cache_key] = {"val": val, "ts": now_ts}
            return val
    except Exception as e:
        logger.warning(f"[ScheduleManager] Error getting drivers for capacity: {e}")
    return 3  # Fallback default capacity if unable to query


def _get_orders_for_slot_check(tenant_id: str = "petroil") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    now_ts = datetime.now().timestamp()
    cache_key = f"orders:{tenant_id}"
    cached = _SCHEDULE_CACHE.get(cache_key)
    if cached and (now_ts - cached["ts"] < 15):
        return cached["agenda"], cached["active"]

    repo = get_repository()
    agenda: list[dict[str, Any]] = []
    try:
        agenda = repo.get_scheduled_agenda(tenant_id)
    except Exception as e:
        logger.warning(f"[ScheduleManager] Error checking occupied orders in agenda: {e}")

    active: list[dict[str, Any]] = []
    try:
        active = repo.get_all_orders_admin(tenant_id, status="all")
    except Exception as e:
        logger.warning(f"[ScheduleManager] Error checking active orders: {e}")

    _SCHEDULE_CACHE[cache_key] = {"agenda": agenda, "active": active, "ts": now_ts}
    return agenda, active


def get_occupied_orders_in_slot(
    slot_dt: datetime,
    tenant_id: str = "petroil",
) -> list[dict[str, Any]]:
    """Fetch active and scheduled orders that fall within the given slot window.

    A slot window is defined as [slot_dt - 14 minutes, slot_dt + 15 minutes].
    """
    window_start = slot_dt - timedelta(minutes=14)
    window_end = slot_dt + timedelta(minutes=15)
    occupied_orders: list[dict[str, Any]] = []

    agenda, active_orders = _get_orders_for_slot_check(tenant_id)

    try:
        # Check scheduled agenda orders
        for ord_info in agenda:
            st = str(ord_info.get("status", "")).lower()
            if st in ("cancelled", "cancelado", "delivered", "entregado"):
                continue

            s_for = ord_info.get("scheduled_for")
            s_text = ord_info.get("delivery_schedule")

            ord_dt = None
            if s_for:
                try:
                    ord_dt = datetime.fromisoformat(s_for)
                except Exception:
                    pass
            if not ord_dt and s_text:
                ord_dt = parse_schedule_deadline(s_text, slot_dt)

            if ord_dt and window_start <= ord_dt <= window_end:
                occupied_orders.append(ord_info)
    except Exception as e:
        logger.warning(f"[ScheduleManager] Error checking occupied orders in agenda: {e}")

    # Also check active orders from admin list to ensure no overlaps
    try:
        existing_ids = {o.get("id") for o in occupied_orders}
        for o in active_orders:
            oid = o.get("id")
            if oid in existing_ids:
                continue
            st = str(o.get("status", "")).lower()
            if st in ("cancelled", "cancelado", "delivered", "entregado"):
                continue

            s_for = o.get("scheduled_for") or o.get("scheduledFor")
            s_text = o.get("delivery_schedule") or o.get("deliverySchedule")

            ord_dt = None
            if s_for:
                try:
                    ord_dt = datetime.fromisoformat(s_for)
                except Exception:
                    pass
            if not ord_dt and s_text and "antes posible" not in s_text.lower():
                ord_dt = parse_schedule_deadline(s_text, slot_dt)

            if ord_dt and window_start <= ord_dt <= window_end:
                occupied_orders.append(o)
                existing_ids.add(oid)
    except Exception as e:
        logger.warning(f"[ScheduleManager] Error checking active orders: {e}")

    return occupied_orders


def find_next_available_slot(
    start_dt: datetime,
    tenant_id: str = "petroil",
    max_slots_to_check: int = 16,
) -> tuple[datetime, int, int]:
    """Search sequentially for the earliest available 30-minute slot after start_dt.

    Returns:
        (available_slot_dt, current_occupied_count, capacity)
    """
    capacity = get_slot_capacity(tenant_id)
    curr_dt = normalize_to_slot_dt(start_dt) + timedelta(minutes=SLOT_INTERVAL_MINUTES)

    for _ in range(max_slots_to_check):
        # Operational business hours: 8:00 AM to 7:00 PM (19:00 hrs)
        # If at or past 7:00 PM (19:00), advance to 8:00 AM the next day
        if curr_dt.hour >= 19:
            curr_dt = (curr_dt + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
        elif curr_dt.hour < 8:
            curr_dt = curr_dt.replace(hour=8, minute=0, second=0, microsecond=0)

        occupied = len(get_occupied_orders_in_slot(curr_dt, tenant_id))
        if occupied < capacity:
            return curr_dt, occupied, capacity

        curr_dt += timedelta(minutes=SLOT_INTERVAL_MINUTES)

    # Fallback to curr_dt if all tested were filled
    return curr_dt, 0, capacity


def check_schedule_availability(
    schedule_text: str,
    tenant_id: str = "petroil",
    ref_time: datetime | None = None,
) -> dict[str, Any]:
    """Validate a requested schedule string, check slot capacity against driver count,
    and find the next available slot if full.

    Returns a comprehensive result dictionary.
    """
    ref = ref_time or datetime.now()
    text = (schedule_text or "").strip()
    text_lower = text.lower()

    # 1. Chequeo de inmediatez ("lo antes posible", "asap", etc.)
    from src.services.flow_router import parse_schedule_deterministic
    parsed_det = parse_schedule_deterministic(text)
    if parsed_det == "Lo antes posible" or any(k in text_lower for k in [
        "lo antes posible", "lo mas pronto", "lo más pronto", "ahorita", "ya mismo", "asap", "inmediato", "urgente", "cuanto antes"
    ]):
        return {
            "is_valid_schedule": True,
            "is_asap": True,
            "requested_dt": None,
            "requested_display": "Lo antes posible",
            "is_available": True,
            "occupied": 0,
            "capacity": get_slot_capacity(tenant_id),
            "next_available_dt": None,
            "next_available_display": "",
            "next_available_time_str": "",
            "message": "Horario inmediato (Lo antes posible). Disponible para despacho directo.",
        }


    # 2. Parsear fecha y hora
    parsed_dt = parse_schedule_deadline(text, ref)
    if not parsed_dt:
        return {
            "is_valid_schedule": False,
            "is_asap": False,
            "requested_dt": None,
            "requested_display": text,
            "is_available": False,
            "occupied": 0,
            "capacity": get_slot_capacity(tenant_id),
            "next_available_dt": None,
            "next_available_display": "",
            "next_available_time_str": "",
            "message": f"No se pudo identificar una fecha u hora válida a partir de '{text}'.",
        }

    # Normalizar a bloque de 30 minutos
    slot_dt = normalize_to_slot_dt(parsed_dt)
    capacity = get_slot_capacity(tenant_id)
    requested_display = format_slot_display(slot_dt, ref)
    time_only_str = format_time_only(slot_dt)

    # 3. Validar horario de operación (8:00 AM a 7:00 PM)
    # Si el pedido cae a las 7:00 PM o posterior, se va al día siguiente a partir de las 8:00 AM
    if slot_dt.hour >= 19:
        tomorrow_8am = (slot_dt + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
        next_dt, next_occ, _ = find_next_available_slot(tomorrow_8am - timedelta(minutes=SLOT_INTERVAL_MINUTES), tenant_id)
        next_disp = format_slot_display(next_dt, ref)
        next_time = format_time_only(next_dt)
        return {
            "is_valid_schedule": True,
            "is_asap": False,
            "requested_dt": slot_dt,
            "requested_display": requested_display,
            "time_only_str": time_only_str,
            "is_available": False,
            "capacity_reached": False,
            "outside_business_hours": True,
            "occupied": 0,
            "capacity": capacity,
            "next_available_dt": next_dt,
            "next_available_display": next_disp,
            "next_available_time_str": next_time,
            "message": (
                f"La gasera opera de 8:00 AM a 7:00 PM. A las {time_only_str} ya no hay reparto por cierre de turno. "
                f"Podemos programar tu entrega con gusto a partir de mañana a las {next_time} ({next_disp})."
            ),
        }
    elif slot_dt.hour < 8:
        today_8am = slot_dt.replace(hour=8, minute=0, second=0, microsecond=0)
        next_dt, next_occ, _ = find_next_available_slot(today_8am - timedelta(minutes=SLOT_INTERVAL_MINUTES), tenant_id)
        next_disp = format_slot_display(next_dt, ref)
        next_time = format_time_only(next_dt)
        return {
            "is_valid_schedule": True,
            "is_asap": False,
            "requested_dt": slot_dt,
            "requested_display": requested_display,
            "time_only_str": time_only_str,
            "is_available": False,
            "capacity_reached": False,
            "outside_business_hours": True,
            "occupied": 0,
            "capacity": capacity,
            "next_available_dt": next_dt,
            "next_available_display": next_disp,
            "next_available_time_str": next_time,
            "message": (
                f"Nuestro horario de reparto inicia a las 8:00 AM. "
                f"Podemos programar tu entrega a partir de las {next_time} ({next_disp})."
            ),
        }

    occupied_orders = get_occupied_orders_in_slot(slot_dt, tenant_id)
    occupied_count = len(occupied_orders)

    # 4. Evaluar disponibilidad de choferes dentro de horario laboral
    if occupied_count < capacity:
        return {
            "is_valid_schedule": True,
            "is_asap": False,
            "requested_dt": slot_dt,
            "requested_display": requested_display,
            "time_only_str": time_only_str,
            "is_available": True,
            "capacity_reached": False,
            "occupied": occupied_count,
            "capacity": capacity,
            "next_available_dt": None,
            "next_available_display": "",
            "next_available_time_str": "",
            "message": (
                f"El horario '{requested_display}' tiene cupo disponible "
                f"({occupied_count}/{capacity} pedidos reservados)."
            ),
        }

    # 5. Cupo lleno -> Buscar siguiente horario disponible (+30 min)
    next_dt, next_occ, _ = find_next_available_slot(slot_dt, tenant_id)
    next_display = format_slot_display(next_dt, ref)
    next_time_str = format_time_only(next_dt)

    return {
        "is_valid_schedule": True,
        "is_asap": False,
        "requested_dt": slot_dt,
        "requested_display": requested_display,
        "time_only_str": time_only_str,
        "is_available": False,
        "capacity_reached": True,
        "occupied": occupied_count,
        "capacity": capacity,
        "next_available_dt": next_dt,
        "next_available_display": next_display,
        "next_available_time_str": next_time_str,
        "message": (
            f"El cupo para '{requested_display}' está COMPLETO ({occupied_count}/{capacity} pedidos asignados a choferes). "
            f"El siguiente horario disponible más cercano es '{next_display}'."
        ),
    }
