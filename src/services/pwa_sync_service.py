"""Background synchronization service that watches Central NestJS API / PostgreSQL
for order state changes initiated by the Driver PWA or external Dispatcher.

Detects:
1. Driver assigned to an order -> triggers notify_order_assigned()
2. Order transitioned to EN_RUTA / in_route -> triggers notify_order_in_route()
3. Order transitioned to ENTREGADO / delivered -> triggers notify_order_delivered()
4. Driver GPS position movement -> triggers notify_driver_location_update()
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.repositories import get_repository
import src.services.order_events as order_events

logger = logging.getLogger(__name__)

# Known order state: order_id -> {"status": str, "driver_id": Any}
_KNOWN_ORDER_STATES: dict[str, dict[str, Any]] = {}
_INITIALIZED: bool = False
_SYNC_TASK: asyncio.Task | None = None
_RUNNING: bool = False


def _normalize_status(raw: str | None) -> str:
    """Normalize Spanish/English status strings to standard canonical codes."""
    if not raw:
        return "pending"
    s = str(raw).lower().strip()
    mapping = {
        "en_ruta": "in_route",
        "en_camino": "in_route",
        "en_reparto": "in_route",
        "in_route": "in_route",
        "entregado": "delivered",
        "delivered": "delivered",
        "cancelado": "cancelled",
        "cancelled": "cancelled",
        "asignado": "assigned",
        "assigned": "assigned",
        "confirmado": "confirmed",
        "confirmed": "confirmed",
        "pendiente": "pending",
        "pending": "pending",
        "programado": "scheduled",
        "scheduled": "scheduled",
    }
    return mapping.get(s, s)


async def poll_order_updates_once(tenant_id: str = "petroil") -> int:
    """Execute a single scan of orders and dispatch events for any observed transitions."""
    global _INITIALIZED, _KNOWN_ORDER_STATES

    repo = get_repository()
    try:
        orders = await asyncio.to_thread(repo.get_all_orders_admin, tenant_id, "all")
    except Exception as e:
        logger.debug(f"[PwaSyncService] Error fetching orders from repo: {e}")
        return 0

    if not isinstance(orders, list):
        return 0

    events_fired = 0

    # On first boot, snapshot the existing database state so historical completed orders
    # don't trigger a surge of false notifications to old customers
    if not _INITIALIZED:
        for o in orders:
            oid = str(o.get("id") or o.get("orderNumber") or "").strip()
            if not oid:
                continue
            st = _normalize_status(o.get("status"))
            drv_id = o.get("driver_id")
            _KNOWN_ORDER_STATES[oid] = {"status": st, "driver_id": drv_id}
        _INITIALIZED = True
        logger.info(f"[PwaSyncService] Initialized state with {len(_KNOWN_ORDER_STATES)} existing orders.")
        return 0

    for o in orders:
        oid = str(o.get("id") or o.get("orderNumber") or "").strip()
        if not oid:
            continue

        curr_st = _normalize_status(o.get("status"))
        curr_drv = o.get("driver_id")

        prev_state = _KNOWN_ORDER_STATES.get(oid)

        if prev_state is not None:
            prev_st = prev_state.get("status")
            prev_drv = prev_state.get("driver_id")

            # 1. Driver assigned transition
            if (not prev_drv and curr_drv) or (prev_st not in ("assigned", "in_route", "delivered") and curr_st in ("assigned", "in_route")):
                if curr_drv and curr_st not in ("cancelled", "delivered"):
                    logger.info(f"[PwaSyncService] Detected Driver Assignment for #{oid}: {prev_drv} -> {curr_drv}")
                    await asyncio.to_thread(order_events.notify_order_assigned, tenant_id, oid, curr_drv)
                    events_fired += 1

            # 2. In Route transition (PWA driver pressed "Voy en Camino")
            if prev_st != "in_route" and curr_st == "in_route":
                logger.info(f"[PwaSyncService] Detected In-Route transition for #{oid} (driver: {curr_drv})")
                await asyncio.to_thread(order_events.notify_order_in_route, tenant_id, oid, curr_drv)
                events_fired += 1

            # 3. Delivered transition (PWA driver pressed "Entregado")
            if prev_st != "delivered" and curr_st == "delivered":
                logger.info(f"[PwaSyncService] Detected Delivery transition for #{oid}")
                await asyncio.to_thread(order_events.notify_order_delivered, tenant_id, oid)
                events_fired += 1

            # 4. Cancelled transition
            if prev_st != "cancelled" and curr_st == "cancelled":
                logger.info(f"[PwaSyncService] Detected Cancellation for #{oid}")
                canc_by = o.get("cancelled_by") or o.get("cancelledBy")
                if not canc_by:
                    from src.repositories.identity_store import identity_store
                    canc_info = identity_store.get_order_cancellation(oid)
                    if canc_info and canc_info.get("cancelled_by"):
                        canc_by = canc_info["cancelled_by"]
                if not canc_by:
                    actor = str(o.get("actor") or "").lower()
                    if "chofer" in actor or "driver" in actor or curr_drv:
                        canc_by = "el chofer"
                    elif "cliente" in actor or "customer" in actor:
                        canc_by = "el cliente"
                    else:
                        canc_by = "Torre de Control"
                await asyncio.to_thread(
                    order_events.notify_order_cancelled,
                    tenant_id,
                    oid,
                    reason=o.get("notes") or o.get("rejectionReason") or "",
                    cancelled_by=canc_by,
                )
                events_fired += 1
        else:
            # Newly created order appearing after service boot
            if curr_drv and curr_st == "assigned":
                await asyncio.to_thread(order_events.notify_order_assigned, tenant_id, oid, curr_drv)
                events_fired += 1
            elif curr_st == "in_route":
                await asyncio.to_thread(order_events.notify_order_in_route, tenant_id, oid, curr_drv)
                events_fired += 1

        # Update cache
        _KNOWN_ORDER_STATES[oid] = {"status": curr_st, "driver_id": curr_drv}

    # 5. Check active in-route drivers for real-time GPS coordinate movement
    try:
        active_in_route_drivers = {
            s["driver_id"] for s in _KNOWN_ORDER_STATES.values() if s.get("status") == "in_route" and s.get("driver_id")
        }
        if active_in_route_drivers:
            drivers = await asyncio.to_thread(repo.get_all_drivers, tenant_id)
            for d in drivers:
                if d.id in active_in_route_drivers or str(d.id) in active_in_route_drivers:
                    c_lat = getattr(d, "current_lat", None)
                    c_lng = getattr(d, "current_lng", None)
                    if c_lat is not None and c_lng is not None and c_lat != 0.0 and c_lng != 0.0:
                        await asyncio.to_thread(order_events.notify_driver_location_update, tenant_id, d.id, float(c_lat), float(c_lng))
    except Exception as ex:
        logger.debug(f"[PwaSyncService] GPS active check note: {ex}")

    return events_fired


async def _run_sync_loop(interval_seconds: float = 4.0, tenant_id: str = "petroil") -> None:
    """Continuous polling loop."""
    global _RUNNING
    logger.info(f"🔄 [PwaSyncService] Started background monitoring of Central NestJS orders (every {interval_seconds}s).")
    _RUNNING = True
    while _RUNNING:
        try:
            await poll_order_updates_once(tenant_id)
        except asyncio.CancelledError:
            logger.info("[PwaSyncService] Background sync task cancelled.")
            break
        except Exception as e:
            logger.error(f"[PwaSyncService] Unexpected error in polling loop: {e}", exc_info=True)

        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            break
    _RUNNING = False


def start_pwa_sync_service(interval_seconds: float = 4.0, tenant_id: str = "petroil") -> None:
    """Start the PWA state synchronization background worker."""
    global _SYNC_TASK, _RUNNING
    if _SYNC_TASK is not None and not _SYNC_TASK.done():
        logger.debug("[PwaSyncService] Worker is already running.")
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        _SYNC_TASK = loop.create_task(_run_sync_loop(interval_seconds, tenant_id))
    else:
        logger.warning("[PwaSyncService] No active asyncio event loop found to attach sync worker.")


def stop_pwa_sync_service() -> None:
    """Stop the PWA state synchronization background worker."""
    global _SYNC_TASK, _RUNNING
    _RUNNING = False
    if _SYNC_TASK and not _SYNC_TASK.done():
        _SYNC_TASK.cancel()
        _SYNC_TASK = None
    logger.info("[PwaSyncService] Stopped background monitoring worker.")
