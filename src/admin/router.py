"""Admin Backoffice REST API router and static file serving."""

import logging
import re
from pathlib import Path
from typing import Any
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from src.repositories import get_repository

logger = logging.getLogger(__name__)
router = APIRouter()

ADMIN_STATIC_DIR = Path(__file__).parent / "static"


# -----------------------------------------------------------------------------
# Pydantic Request Models
# -----------------------------------------------------------------------------

class ProductCreateRequest(BaseModel):
    id: str = Field(..., min_length=2, description="Unique product ID slug")
    name: str = Field(..., min_length=2, description="Product display name")
    description: str = Field("", description="Product description")
    price: float = Field(..., ge=0, description="Unit price in MXN")
    currency: str = "MXN"
    category: str = "Cilindros"
    in_stock: bool = True
    is_promoted: bool = False
    promotion_text: str = ""
    tags: list[str] = []
    image_url: str = ""


class ProductUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    price: float | None = None
    currency: str | None = None
    category: str | None = None
    in_stock: bool | None = None
    is_promoted: bool | None = None
    promotion_text: str | None = None
    tags: list[str] | None = None
    image_url: str | None = None


class DriverCreateRequest(BaseModel):
    name: str = Field(..., min_length=2)
    phone: str = Field(..., min_length=7)
    vehicle_type: str = "cilindros"
    vehicle_plate: str = ""
    zone: str = "General"
    telegram_user_id: str = ""
    vehicle_id: int | None = None


class DriverUpdateRequest(BaseModel):
    name: str | None = None
    phone: str | None = None
    vehicle_type: str | None = None
    vehicle_plate: str | None = None
    zone: str | None = None
    is_available: bool | None = None
    telegram_user_id: str | None = None
    vehicle_id: int | None = None


class VehicleCreateRequest(BaseModel):
    unit_identifier: str = Field(..., description="Identificador único ej. PIPA-01, CAM-04")
    plate: str = Field(..., description="Placas del vehículo")
    model: str = Field(..., description="Modelo ej. Ford F-350 2022")
    vehicle_type: str = Field("camioneta", description="pipa o camioneta")
    pipa_capacity_liters: float | None = Field(None, description="Capacidad en Litros en caso de ser pipa")
    cylinder_capacity_count: int | None = Field(None, description="Capacidad de cilindros en caso de camioneta")
    status: str = Field("active", description="active, maintenance, inactive")
    notes: str = ""


class VehicleUpdateRequest(BaseModel):
    unit_identifier: str | None = None
    plate: str | None = None
    model: str | None = None
    vehicle_type: str | None = None
    pipa_capacity_liters: float | None = None
    cylinder_capacity_count: int | None = None
    status: str | None = None
    notes: str | None = None


class OrderStatusUpdateRequest(BaseModel):
    status: str = Field(..., description="confirmed, assigned, in_route, delivered, cancelled")
    reason: str | None = Field(None, description="Motivo o explicación de la cancelación o actualización")


class OrderReassignRequest(BaseModel):
    driver_id: Any = Field(..., description="Target driver ID (int or UUID)")


class DriverOrderStatusUpdateRequest(BaseModel):
    status: str = Field(..., description="EN_RUTA, ENTREGADO, CANCELADO, ASIGNADO")
    signature: str | None = Field(None, description="Firma o comprobante en Base64")
    reason: str | None = Field(None, description="Motivo en caso de cancelación")
    notes: str | None = Field(None, description="Notas operativas adicionales")


class DriverLocationUpdateRequest(BaseModel):
    lat: float = Field(..., description="Latitud GPS")
    lng: float = Field(..., description="Longitud GPS")


class ShiftStartRequest(BaseModel):
    driverId: str | None = None
    vehicleId: str | None = None
    initialReading: float | str | None = 0
    initialTankPct: float | None = None
    initialOdometer: float | None = None
    photoUrl: str | None = None


class ShiftEndRequest(BaseModel):
    driverId: str | None = None
    shiftId: str | None = None
    finalReading: float | str | None = 100
    finalTankPct: float | None = None
    finalOdometer: float | None = None
    photoUrl: str | None = None


class DriverLoginRequest(BaseModel):
    phone: str = Field(..., min_length=7, description="Teléfono del chofer")
    password: str | None = Field("123456", description="Contraseña")


class OrderRescheduleRequest(BaseModel):
    delivery_schedule: str = Field(..., description="Nuevo texto de horario ej. Hoy 5:00 PM")
    scheduled_for: str | None = Field(None, description="ISO datetime de la deadline")


class OrderItemCreate(BaseModel):
    product_id: str = Field(..., description="ID del producto ej. cilindro-30kg o estacionario-litros")
    product_name: str | None = Field(None, description="Nombre descriptivo del producto")
    quantity: float = Field(1, gt=0, description="Cantidad de cilindros o litros")
    unit_price: float | None = Field(None, ge=0, description="Precio unitario (opcional)")


class OrderCreateAdminRequest(BaseModel):
    customer_name: str = Field(..., min_length=2, description="Nombre del cliente")
    customer_phone: str = Field(..., min_length=7, description="Teléfono del cliente")
    delivery_address: str = Field(..., min_length=3, description="Dirección de entrega")
    items: list[OrderItemCreate] = Field(..., min_items=1, description="Lista de productos del pedido")
    delivery_schedule: str = Field("Lo antes posible", description="Horario de entrega")
    scheduled_for: str | None = Field(None, description="Fecha y hora ISO si es entrega programada")
    payment_method: str = Field("Efectivo", description="Método de pago (Efectivo, Tarjeta, Transferencia)")
    notes: str = Field("", description="Referencias o notas para la entrega")
    dispatch_mode: str = Field("none", description="auto, driver, o none")
    driver_id: Any = Field(None, description="ID del chofer si dispatch_mode es 'driver'")


# -----------------------------------------------------------------------------
# HTML UI Route
# -----------------------------------------------------------------------------

@router.get("/admin", response_class=HTMLResponse)
@router.get("/admin/", response_class=HTMLResponse)
async def admin_dashboard_ui():
    """Serve the main Backoffice HTML Single Page Application."""
    index_file = ADMIN_STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Admin index.html not found.")
    return HTMLResponse(content=index_file.read_text(encoding="utf-8"))


# -----------------------------------------------------------------------------
# REST API: Metrics
# -----------------------------------------------------------------------------

@router.get("/api/admin/metrics")
async def get_dashboard_metrics(tenant_id: str = "petroil"):
    """Get aggregated metrics for the dashboard KPI cards."""
    repo = get_repository()
    # Check and activate any scheduled orders whose 30m window has arrived
    repo.check_and_activate_scheduled_orders(tenant_id)
    return repo.get_admin_dashboard_metrics(tenant_id)


@router.get("/api/admin/llm-metrics")
async def get_llm_telemetry_metrics():
    """Get real-time token optimization and LLM efficiency telemetry metrics."""
    from src.services.telemetry import telemetry
    return telemetry.get_metrics()


# -----------------------------------------------------------------------------
# REST API: Orders & Agenda
# -----------------------------------------------------------------------------

@router.get("/api/admin/agenda")
async def get_scheduled_agenda(tenant_id: str = "petroil"):
    """Get all scheduled orders for the Agenda dashboard view."""
    repo = get_repository()
    return repo.get_scheduled_agenda(tenant_id)


@router.post("/api/admin/orders/{order_id}/activate-now")
async def activate_order_now(order_id: str, tenant_id: str = "petroil"):
    """Manually advance and activate a scheduled order into active orders immediately."""
    repo = get_repository()
    order = repo.activate_scheduled_order_now(tenant_id, order_id)
    if not order:
        raise HTTPException(status_code=404, detail=f"Order #{order_id} not found.")
    return {"message": f"Pedido #{order_id} activado y enviado a despacho activo.", "order": order}


@router.post("/api/admin/orders/{order_id}/reschedule")
async def reschedule_order(order_id: str, payload: OrderRescheduleRequest, tenant_id: str = "petroil"):
    """Update scheduled time or deadline for an order."""
    repo = get_repository()
    order = repo.reschedule_order(tenant_id, order_id, payload.delivery_schedule, payload.scheduled_for)
    if not order:
        raise HTTPException(status_code=404, detail=f"Order #{order_id} not found.")
    return {"message": f"Pedido #{order_id} reprogramado con éxito.", "order": order}


# -----------------------------------------------------------------------------
# REST API: Orders
# -----------------------------------------------------------------------------

@router.post("/api/admin/orders", status_code=201)
async def create_order_admin(
    payload: OrderCreateAdminRequest,
    background_tasks: BackgroundTasks,
    tenant_id: str = "petroil",
):
    """Crea un pedido manualmente desde el Dashboard Administrativo."""
    repo = get_repository()

    # Formatear partidas de productos
    raw_items = []
    for it in payload.items:
        raw_items.append({
            "product_id": it.product_id,
            "product_name": it.product_name or it.product_id,
            "quantity": it.quantity,
            "unit_price": it.unit_price,
        })

    # Determinar si es programado a futuro
    from src.services.dispatch import is_future_order, dispatch_order
    from src.services.geocoding import geocode_address
    
    is_future = bool(payload.scheduled_for) or is_future_order(payload.delivery_schedule)
    initial_status = "scheduled" if is_future else "confirmed"

    # Resolver coordenadas GPS del domicilio para la BD
    delivery_lat = None
    delivery_lng = None
    clean_addr_str = payload.delivery_address.strip()
    try:
        lat, lng, formatted_addr = geocode_address(clean_addr_str)
        if lat and lng:
            delivery_lat = lat
            delivery_lng = lng
    except Exception:
        pass

    clean_phone = payload.customer_phone.strip()
    order = repo.create_order(
        tenant_id=tenant_id,
        customer_name=payload.customer_name.strip(),
        customer_phone=clean_phone,
        delivery_address=clean_addr_str,
        items=raw_items,
        delivery_schedule=payload.delivery_schedule.strip() or "Lo antes posible",
        payment_method=payload.payment_method.strip() or "Efectivo",
        notes=payload.notes.strip(),
        channel="dashboard",
        channel_user_id=f"dashboard_{clean_phone}",
        delivery_lat=delivery_lat,
        delivery_lng=delivery_lng,
        scheduled_for=payload.scheduled_for,
    )

    # Manejar asignación o despacho según el modo elegido
    if payload.dispatch_mode == "driver" and payload.driver_id:
        driver = repo.get_driver(payload.driver_id)
        if driver:
            repo.assign_order_to_driver(
                tenant_id=tenant_id,
                order_id=order.id,
                driver_id=driver.id,
                delivery_lat=delivery_lat,
                delivery_lng=delivery_lng,
            )
            repo.update_order_status(tenant_id, order.id, "assigned")
            if driver.telegram_user_id:
                from src.services.dispatch import send_driver_trip_alert
                background_tasks.add_task(
                    send_driver_trip_alert,
                    telegram_user_id=driver.telegram_user_id,
                    order=order,
                    title_header="🚨 **¡NUEVO PEDIDO ASIGNADO POR TORRE DE CONTROL!**",
                    lat=delivery_lat,
                    lng=delivery_lng,
                )
            recipient_id = str(order.channel_user_id or order.customer_phone or "").strip()
            if recipient_id:
                from src.services.notifications import notify_client
                v_label = driver.vehicle_plate or "Unidad de reparto"
                d_phone_str = f"📞 **Teléfono:** `{driver.phone}`\n" if driver.phone else ""
                msg_asignacion = (
                    f"🛻 **¡Tu pedido #{order.id} ha sido asignado!**\n\n"
                    f"👨‍✈️ **Chofer:** {driver.name}\n"
                    f"🚘 **Unidad:** {v_label}\n"
                    f"{d_phone_str}\n"
                    f"El operador está preparando tu unidad y te avisaremos en cuanto inicie su recorrido hacia tu domicilio. ⛽"
                )
                background_tasks.add_task(notify_client, recipient_id, msg_asignacion, None, order.channel)
    else:
        logger.info(f"[admin/router] Pedido #{order.id} creado sin chofer asignado. Queda en espera de asignación manual en Dashboard.")

    updated_order = repo.get_order_by_id(tenant_id, order.id) or order
    return {
        "ok": True,
        "message": f"Pedido #{order.id} creado con éxito",
        "order": {
            "id": updated_order.id,
            "customer_name": updated_order.customer_name,
            "customer_phone": updated_order.customer_phone,
            "delivery_address": updated_order.delivery_address,
            "delivery_schedule": updated_order.delivery_schedule,
            "total_amount": updated_order.total_amount,
            "payment_method": updated_order.payment_method,
            "status": updated_order.status,
            "driver_id": updated_order.driver_id,
            "driver_name": getattr(updated_order, "driver_name", None),
            "created_at": updated_order.created_at,
        },
    }


@router.get("/api/admin/orders")
async def list_orders(
    tenant_id: str = "petroil",
    status: str | None = Query(None, description="all, confirmed, assigned, in_route, delivered, cancelled, scheduled"),
    search: str | None = Query(None, description="Search by customer name, phone, address, or folio"),
    limit: int = 200,
):
    """List orders with items and driver information."""
    repo = get_repository()
    orders = repo.get_all_orders_admin(tenant_id, status=status, limit=limit)

    if search and search.strip():
        q = search.strip().lower()
        orders = [
            o for o in orders
            if q in str(o.get("id", ""))
            or q in (o.get("customer_name") or "").lower()
            or q in (o.get("customer_phone") or "").lower()
            or q in (o.get("delivery_address") or "").lower()
            or q in (o.get("driver_name") or "").lower()
        ]

    return orders


@router.patch("/api/admin/orders/{order_id}/status")
@router.put("/api/admin/orders/{order_id}/status")
async def update_order_status(
    order_id: str,
    payload: OrderStatusUpdateRequest,
    background_tasks: BackgroundTasks,
    tenant_id: str = "petroil",
):
    """Change the status of an order and notify the customer if cancelled."""
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
        "confirmado": "confirmed",
        "confirmed": "confirmed",
        "programado": "scheduled",
        "scheduled": "scheduled",
    }
    raw_status = payload.status.lower().strip()
    new_status = status_map.get(raw_status, raw_status)
    valid_statuses = ["confirmed", "assigned", "in_route", "delivered", "cancelled", "scheduled"]
    if new_status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status: {payload.status}. Must be one of {valid_statuses}")

    repo = get_repository()
    order = repo.get_order_by_id(tenant_id, order_id)
    if not order:
        raise HTTPException(status_code=404, detail=f"Order #{order_id} not found.")

    reason = (payload.reason or "").strip()
    notes_append = f"[Cancelación]: {reason}" if (new_status == "cancelled" and reason) else ""
    updated = repo.update_order_status(tenant_id, order_id, new_status, notes_append=notes_append)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Order #{order_id} not found.")

    # Notificaciones automáticas omnicanal (WhatsApp, Telegram, Messenger, Instagram)
    from src.services.order_events import handle_order_transition
    background_tasks.add_task(
        handle_order_transition,
        tenant_id=tenant_id,
        order_id=order_id,
        new_status=new_status,
        driver_id=order.driver_id,
        reason=reason,
    )

    return {"success": True, "order_id": order_id, "status": updated.status}


@router.post("/api/admin/orders/{order_id}/reassign")
async def reassign_order_driver(
    order_id: str,
    payload: OrderReassignRequest,
    background_tasks: BackgroundTasks,
    tenant_id: str = "petroil",
):
    """Assign or reassign an order to a driver from the Control Tower and notify both driver and customer in Telegram."""
    repo = get_repository()
    driver = repo.get_driver(payload.driver_id)
    if not driver:
        logger.error(f"[Reassign] Driver '{payload.driver_id}' not found.")
        raise HTTPException(status_code=404, detail=f"Driver #{payload.driver_id} not found.")

    order = repo.get_order_by_id(tenant_id, order_id)
    if not order:
        logger.error(f"[Reassign] Order '{order_id}' not found.")
        raise HTTPException(status_code=404, detail=f"Order #{order_id} not found.")

    if order.status == "cancelled":
        raise HTTPException(
            status_code=400,
            detail="El pedido está cancelado. No se le puede asignar chofer."
        )

    # Identificar si es una reasignación (cambio de chofer o tras un rechazo/incidencia)
    is_reassignment = bool(
        (order.driver_id and str(order.driver_id) != str(driver.id))
        or (order.status in ("rejected_by_driver", "assigned", "in_route"))
    )

    prev_driver_id = order.driver_id

    updated = repo.reassign_order(tenant_id, order_id, driver.id)
    if not updated:
        updated = repo.assign_order_to_driver(tenant_id, order_id, driver.id)
    if not updated:
        raise HTTPException(status_code=400, detail="Could not reassign order.")

    target_order = updated or order

    # Si había un chofer anterior y era diferente, lo liberamos y le notificamos
    if prev_driver_id and str(prev_driver_id) != str(driver.id):
        try:
            repo.set_driver_availability(prev_driver_id, True)
            repo.clear_order_live_location(tenant_id, order_id)
            prev_driver = repo.get_driver(prev_driver_id)
            if prev_driver and prev_driver.telegram_user_id and str(prev_driver.telegram_user_id).strip().isdigit():
                from src.services.notifications import notify_driver
                background_tasks.add_task(
                    notify_driver,
                    telegram_user_id=str(prev_driver.telegram_user_id).strip(),
                    message=(
                        f"ℹ️ **Actualización de Pedido #{target_order.id}**\n\n"
                        f"Torre de Control ha reasignado este servicio a otra unidad ({driver.name}).\n"
                        f"Tu estatus ha sido actualizado a **🟢 DISPONIBLE** para nuevos servicios."
                    ),
                )
        except Exception as e:
            logger.warning(f"[Reassign] Error gestionando chofer previo {prev_driver_id}: {e}")

    # 1. Disparar notificación interactiva al nuevo chofer por Telegram solo si ya está activo
    # Si es un pedido programado a futuro (antes de su ventana de 30 min), se pre-asigna el chofer sin alertar todavía
    from datetime import datetime, timedelta
    from src.repositories.sqlite_repo import normalize_schedule_datetime

    now_dt = datetime.now()
    deadline_dt = normalize_schedule_datetime(target_order.scheduled_for, now_dt)
    if not deadline_dt and target_order.delivery_schedule:
        deadline_dt = normalize_schedule_datetime(target_order.delivery_schedule, now_dt)
    is_waiting_in_agenda = bool(deadline_dt and now_dt < (deadline_dt - timedelta(minutes=30)))

    if not is_waiting_in_agenda:
        if driver.telegram_user_id and str(driver.telegram_user_id).strip().isdigit():
            from src.services.dispatch import send_driver_trip_alert
            header = "🚨 **¡PEDIDO REASIGNADO POR TORRE DE CONTROL!**" if is_reassignment else "🚨 **¡NUEVO PEDIDO ASIGNADO POR TORRE DE CONTROL!**"
            logger.info(f"[Reassign] Queueing trip alert to driver {driver.name} (Telegram: {driver.telegram_user_id}) for order #{target_order.id}")
            background_tasks.add_task(
                send_driver_trip_alert,
                telegram_user_id=str(driver.telegram_user_id).strip(),
                order=target_order,
                title_header=header,
                lat=target_order.delivery_lat,
                lng=target_order.delivery_lng,
            )
        else:
            logger.warning(f"[Reassign] Driver {driver.name} does not have a valid telegram_user_id ({driver.telegram_user_id}).")
    else:
        act_label = (deadline_dt - timedelta(minutes=30)).strftime("%I:%M %p").lstrip("0")
        logger.info(f"[Reassign] Order #{target_order.id} is scheduled for {deadline_dt.strftime('%I:%M %p')}. Driver pre-assigned; trip alert will be sent 30 min before deadline at {act_label}.")

    # 2. Disparar notificación al cliente (con disculpas por molestias si es reasignación)
    recipient_id = str(target_order.channel_user_id or target_order.customer_phone or "").strip()
    if recipient_id:
        from src.services.notifications import notify_client

        d_phone_str = f"📞 **Teléfono:** `{driver.phone}`\n" if driver.phone else ""
        if is_waiting_in_agenda:
            client_msg = (
                f"🗓️ **Pedido #{target_order.id} programado**\n\n"
                f"Hemos pre-asignado la unidad de **{driver.name}** para tu entrega ({target_order.delivery_schedule}).\n"
                f"🚘 **Unidad:** {driver.vehicle_plate or 'Unidad de reparto'}\n"
                f"{d_phone_str}\n"
                f"Te avisaremos en cuanto la unidad se active y vaya en camino a tu domicilio. ⛽✨"
            )
        elif is_reassignment:
            client_msg = (
                f"🛻 **Pedido #{target_order.id} reasignado**\n\n"
                f"Tu pedido fue reasignado a una nueva unidad para entregarte más rápido:\n\n"
                f"👨‍✈️ **Nuevo Chofer:** {driver.name}\n"
                f"🚘 **Unidad:** {driver.vehicle_plate or 'Unidad de reparto'}\n"
                f"{d_phone_str}\n"
                f"Te avisaremos en cuanto inicie su recorrido hacia tu domicilio. ⛽"
            )
        else:
            client_msg = (
                f"🛻 **¡Tu pedido #{target_order.id} ha sido asignado!**\n\n"
                f"👨‍✈️ **Chofer:** {driver.name}\n"
                f"🚘 **Unidad:** {driver.vehicle_plate or 'Unidad de reparto'}\n"
                f"{d_phone_str}\n"
                f"Te avisaremos en cuanto vaya en camino a tu domicilio. ⛽"
            )

        background_tasks.add_task(notify_client, recipient_id, client_msg, None, target_order.channel)

    return {"success": True, "order_id": order_id, "driver_id": driver.id, "driver_name": driver.name, "reassigned": is_reassignment}


# -----------------------------------------------------------------------------
# REST API: Rejections & Incidents
# -----------------------------------------------------------------------------

@router.get("/api/admin/rejections")
async def list_order_rejections(
    tenant_id: str = "petroil",
    unresolved_only: bool = False,
):
    """List order rejections and driver incident reports for the Control Tower."""
    repo = get_repository()
    return repo.get_order_rejections(tenant_id, unresolved_only=unresolved_only)


# -----------------------------------------------------------------------------
# REST API: Products (CRUD)
# -----------------------------------------------------------------------------

@router.get("/api/admin/products")
async def list_products(tenant_id: str = "petroil"):
    """Get complete catalog of products."""
    repo = get_repository()
    products = repo.get_all_products(tenant_id)
    return [p.model_dump() for p in products]


@router.post("/api/admin/products")
async def create_product(payload: ProductCreateRequest, tenant_id: str = "petroil"):
    """Create a new product in the catalog."""
    repo = get_repository()
    existing = repo.get_by_id(tenant_id, payload.id)
    if existing:
        raise HTTPException(status_code=400, detail=f"Product with ID '{payload.id}' already exists.")

    product = repo.create_product(
        tenant_id=tenant_id,
        id=payload.id,
        name=payload.name,
        description=payload.description,
        price=payload.price,
        currency=payload.currency,
        category=payload.category,
        in_stock=payload.in_stock,
        is_promoted=payload.is_promoted,
        promotion_text=payload.promotion_text,
        tags=payload.tags,
        image_url=payload.image_url,
    )
    return product.model_dump()


@router.put("/api/admin/products/{product_id}")
async def update_product(
    product_id: str, payload: ProductUpdateRequest, tenant_id: str = "petroil"
):
    """Update an existing product."""
    repo = get_repository()
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    product = repo.update_product(tenant_id, product_id, updates)
    if not product:
        raise HTTPException(status_code=404, detail=f"Product '{product_id}' not found.")
    return product.model_dump()


@router.delete("/api/admin/products/{product_id}")
async def delete_product(product_id: str, tenant_id: str = "petroil"):
    """Delete a product from the catalog."""
    repo = get_repository()
    ok = repo.delete_product(tenant_id, product_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Product '{product_id}' not found.")
    return {"success": True, "deleted_id": product_id}


# -----------------------------------------------------------------------------
# REST API: Vehicles (Unidades Vehiculares CRUD)
# -----------------------------------------------------------------------------

@router.get("/api/admin/vehicles")
async def list_vehicles(tenant_id: str = "petroil"):
    """Get all fleet vehicles (pipas y camionetas de cilindros) and their assigned driver."""
    repo = get_repository()
    return repo.get_all_vehicles(tenant_id)


@router.post("/api/admin/vehicles")
async def create_vehicle(payload: VehicleCreateRequest, tenant_id: str = "petroil"):
    """Register a new vehicle in the fleet."""
    repo = get_repository()
    veh = repo.create_vehicle(
        tenant_id=tenant_id,
        unit_identifier=payload.unit_identifier,
        plate=payload.plate,
        model=payload.model,
        vehicle_type=payload.vehicle_type,
        pipa_capacity_liters=payload.pipa_capacity_liters,
        cylinder_capacity_count=payload.cylinder_capacity_count,
        status=payload.status,
        notes=payload.notes,
    )
    return veh.model_dump()


@router.put("/api/admin/vehicles/{vehicle_id}")
async def update_vehicle(
    vehicle_id: str, payload: VehicleUpdateRequest, tenant_id: str = "petroil"
):
    """Update an existing fleet vehicle."""
    repo = get_repository()
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    veh = repo.update_vehicle(tenant_id, vehicle_id, updates)
    if not veh:
        raise HTTPException(status_code=404, detail=f"Vehicle #{vehicle_id} not found.")
    return veh.model_dump()


@router.delete("/api/admin/vehicles/{vehicle_id}")
async def delete_vehicle(vehicle_id: str, tenant_id: str = "petroil"):
    """Delete a vehicle from the fleet."""
    repo = get_repository()
    ok = repo.delete_vehicle(tenant_id, vehicle_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Vehicle #{vehicle_id} not found.")
    return {"success": True, "deleted_id": vehicle_id}


# -----------------------------------------------------------------------------
# REST API: Drivers (CRUD)
# -----------------------------------------------------------------------------

@router.get("/api/admin/drivers")
async def list_drivers(tenant_id: str = "petroil"):
    """Get all registered drivers with their real-time operational status (disponible, en_entrega, fuera_servicio)."""
    repo = get_repository()
    return repo.get_all_drivers_operational_status(tenant_id)


@router.post("/api/admin/drivers")
async def create_driver(payload: DriverCreateRequest, tenant_id: str = "petroil"):
    """Create a new driver/vehicle unit."""
    repo = get_repository()
    driver = repo.create_driver(
        tenant_id=tenant_id,
        name=payload.name,
        phone=payload.phone,
        vehicle_type=payload.vehicle_type,
        vehicle_plate=payload.vehicle_plate,
        zone=payload.zone,
        telegram_user_id=payload.telegram_user_id,
        vehicle_id=payload.vehicle_id,
    )
    return driver.model_dump()


@router.put("/api/admin/drivers/{driver_id}")
async def update_driver(driver_id: str, payload: DriverUpdateRequest):
    """Update driver profile or availability."""
    repo = get_repository()
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    driver = repo.update_driver(driver_id, updates)
    if not driver:
        raise HTTPException(status_code=404, detail=f"Driver #{driver_id} not found.")
    return driver.model_dump()


@router.delete("/api/admin/drivers/{driver_id}")
async def delete_driver(driver_id: str):
    """Delete a driver from the system."""
    repo = get_repository()
    ok = repo.delete_driver(driver_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Driver #{driver_id} not found.")
    return {"success": True, "deleted_id": driver_id}


# -----------------------------------------------------------------------------
# REST API: Driver PWA Integration (Status, GPS Tracking, Shifts & Login)
# -----------------------------------------------------------------------------

@router.put("/api/admin/drivers/{driver_id}/orders/{order_id}/status")
@router.patch("/api/admin/drivers/{driver_id}/orders/{order_id}/status")
async def update_driver_order_status(
    driver_id: str,
    order_id: str,
    payload: DriverOrderStatusUpdateRequest,
    background_tasks: BackgroundTasks,
    tenant_id: str = "petroil",
):
    """Driver PWA endpoint: update order status (EN_RUTA, ENTREGADO, CANCELADO, etc.)."""
    raw_status = payload.status.strip()
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
    canonical_status = status_map.get(raw_status.lower(), raw_status.lower())

    repo = get_repository()
    reason = payload.reason or payload.notes or ""
    notes_append = f"[{canonical_status.upper()}]: {reason}" if reason else ""

    repo.update_order_status(
        tenant_id=tenant_id,
        order_id=order_id,
        status=canonical_status,
        driver_id=driver_id,
        notes_append=notes_append,
        signature=payload.signature,
        reason=reason,
    )

    from src.services.order_events import handle_order_transition
    background_tasks.add_task(
        handle_order_transition,
        tenant_id=tenant_id,
        order_id=order_id,
        new_status=canonical_status,
        driver_id=driver_id,
        reason=reason,
        signature=payload.signature,
    )

    return {
        "success": True,
        "order_id": order_id,
        "driver_id": driver_id,
        "status": canonical_status.upper(),
    }


@router.post("/api/admin/drivers/{driver_id}/location")
async def update_driver_location(
    driver_id: str,
    payload: DriverLocationUpdateRequest,
    background_tasks: BackgroundTasks,
    tenant_id: str = "petroil",
):
    """Driver PWA endpoint: update real-time driver GPS coordinates."""
    repo = get_repository()
    lat = float(payload.lat)
    lng = float(payload.lng)

    repo.update_driver_location(driver_id, lat, lng)

    from src.services.order_events import notify_driver_location_update
    background_tasks.add_task(
        notify_driver_location_update,
        tenant_id=tenant_id,
        driver_id=driver_id,
        lat=lat,
        lng=lng,
    )

    return {"success": True, "driver_id": driver_id, "lat": lat, "lng": lng}


@router.get("/api/admin/drivers/{driver_id}/orders")
async def get_driver_orders(
    driver_id: str,
    tenant_id: str = "petroil",
    active_only: bool = True,
):
    """Driver PWA endpoint: get active orders assigned to the driver."""
    repo = get_repository()
    orders = repo.get_orders_by_driver(tenant_id, driver_id, active_only=active_only)
    return [
        {
            "id": o.id,
            "orderNumber": o.id,
            "customerName": o.customer_name,
            "customerPhone": o.customer_phone,
            "deliveryAddress": o.delivery_address,
            "deliverySchedule": o.delivery_schedule,
            "totalAmount": o.total_amount,
            "paymentMethod": o.payment_method,
            "status": o.status.upper(),
            "notes": o.notes,
            "deliveryLat": o.delivery_lat,
            "deliveryLng": o.delivery_lng,
            "items": [
                {
                    "productName": getattr(it, "product_name", getattr(it, "name", "Producto")),
                    "quantity": getattr(it, "quantity", 1),
                    "unitPrice": getattr(it, "unit_price", 0.0),
                }
                for it in (o.items or [])
            ],
        }
        for o in orders
    ]


@router.post("/api/admin/drivers/login")
async def driver_login_pwa(payload: DriverLoginRequest, tenant_id: str = "petroil"):
    """Driver PWA login endpoint."""
    repo = get_repository()
    if hasattr(repo, "driver_login"):
        res = repo.driver_login(payload.phone, payload.password or "")
        if res:
            return res
    clean_p = re.sub(r"\D", "", payload.phone)[-10:]
    for d in repo.get_all_drivers(tenant_id):
        if d.phone and re.sub(r"\D", "", d.phone)[-10:] == clean_p:
            return {
                "id": d.id,
                "name": d.name,
                "phone": d.phone,
                "vehiclePlate": d.vehicle_plate,
                "vehicleType": d.vehicle_type,
            }
    raise HTTPException(status_code=401, detail="Credenciales de chofer inválidas")


@router.post("/api/admin/shifts/start")
async def start_shift_pwa(payload: ShiftStartRequest, tenant_id: str = "petroil"):
    """Driver PWA shift start endpoint."""
    repo = get_repository()
    if hasattr(repo, "start_driver_shift"):
        return repo.start_driver_shift(
            tenant_id=tenant_id,
            driver_id=payload.driverId,
            vehicle_id=payload.vehicleId,
            initial_reading=str(payload.initialReading) if payload.initialReading is not None else None,
            initial_tank_pct=payload.initialTankPct,
            initial_odometer=payload.initialOdometer,
            photo_url=payload.photoUrl or "",
        )
    return {"status": "ACTIVE", "message": "Turno iniciado"}


@router.put("/api/admin/shifts/end")
async def end_shift_pwa(payload: ShiftEndRequest, tenant_id: str = "petroil"):
    """Driver PWA shift end endpoint."""
    repo = get_repository()
    if hasattr(repo, "end_driver_shift"):
        return repo.end_driver_shift(
            tenant_id=tenant_id,
            shift_id=payload.shiftId,
            driver_id=payload.driverId,
            final_reading=str(payload.finalReading) if payload.finalReading is not None else None,
            final_tank_pct=payload.finalTankPct,
            final_odometer=payload.finalOdometer,
            photo_url=payload.photoUrl or "",
        )
    return {"status": "CLOSED", "message": "Turno finalizado"}


# -----------------------------------------------------------------------------
# REST API: Driver Tank Load Readings
# -----------------------------------------------------------------------------

@router.get("/api/admin/drivers/{driver_id}/tank-readings")
async def get_driver_tank_readings(driver_id: str, tenant_id: str = "petroil"):
    """Get tank load readings (initial/final/refill) for a specific driver."""
    repo = get_repository()
    readings = repo.get_tank_readings_by_driver(tenant_id, driver_id)
    return readings


@router.get("/api/admin/tank-readings")
async def list_all_tank_readings(tenant_id: str = "petroil", limit: int = 150):
    """Get all recent tank load readings from all drivers for the Control Tower."""
    repo = get_repository()
    return repo.get_all_tank_readings(tenant_id, limit=limit)


# -----------------------------------------------------------------------------
# REST API: Driver Shifts & Attendance (Hora de Entrada y Salida)
# -----------------------------------------------------------------------------

@router.get("/api/admin/drivers/{driver_id}/shifts")
async def get_driver_shifts(driver_id: str, tenant_id: str = "petroil", limit: int = 50):
    """Get shift and attendance records (hora de entrada, salida, duración) for a driver."""
    repo = get_repository()
    return repo.get_driver_shifts(tenant_id, driver_id=driver_id, limit=limit)


@router.get("/api/admin/shifts")
async def list_all_shifts(tenant_id: str = "petroil", limit: int = 100):
    """Get all driver shifts and attendance records for the Control Tower."""
    repo = get_repository()
    return repo.get_driver_shifts(tenant_id, limit=limit)


# -----------------------------------------------------------------------------
# REST API: Driver Ratings & Surveys (Calificaciones y Encuestas)
# -----------------------------------------------------------------------------

@router.get("/api/admin/ratings")
async def list_all_ratings(tenant_id: str = "petroil", limit: int = 100):
    """Get all ratings and satisfaction survey comments for the Control Tower."""
    repo = get_repository()
    return repo.get_all_ratings_admin(tenant_id, limit=limit)


@router.get("/api/admin/drivers/{driver_id}/ratings")
async def get_driver_ratings(driver_id: str, tenant_id: str = "petroil", limit: int = 50):
    """Get rating details and summary statistics for a driver."""
    repo = get_repository()
    driver = repo.get_driver(driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail=f"Driver #{driver_id} not found.")
    stats = repo.get_driver_rating_stats(tenant_id, driver_id)
    ratings = repo.get_driver_ratings(tenant_id, driver_id, limit=limit)
    return {
        "driver_id": driver_id,
        "driver_name": driver.name,
        "stats": stats,
        "ratings": ratings,
    }


# -----------------------------------------------------------------------------
# REST API: Customers
# -----------------------------------------------------------------------------


@router.get("/api/admin/customers")
async def list_customers(tenant_id: str = "petroil"):
    """Get all registered customers with address book."""
    repo = get_repository()
    return repo.get_all_customers_admin(tenant_id)


# -----------------------------------------------------------------------------
# REST API: Excel Reports & Exports
# -----------------------------------------------------------------------------

@router.get("/api/admin/reports/excel/master")
async def export_master_report(tenant_id: str = "petroil"):
    """Export complete dashboard master workbook with multiple sheets."""
    from datetime import datetime
    from src.services.reports import generate_master_excel

    stream = generate_master_excel(tenant_id)
    filename = f"Petroil_TorreControl_Reporte_Maestro_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/api/admin/reports/excel/orders")
async def export_orders_report(status: str | None = None, tenant_id: str = "petroil"):
    """Export orders report as an Excel spreadsheet."""
    from datetime import datetime
    from src.services.reports import generate_orders_excel

    stream = generate_orders_excel(tenant_id, status=status)
    filename = f"Reporte_Pedidos_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/api/admin/reports/excel/rejections")
async def export_rejections_report(tenant_id: str = "petroil"):
    """Export incidents and driver rejections report as an Excel spreadsheet."""
    from datetime import datetime
    from src.services.reports import generate_rejections_excel

    stream = generate_rejections_excel(tenant_id)
    filename = f"Reporte_Incidencias_Rechazos_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/api/admin/reports/excel/drivers")
async def export_drivers_report(tenant_id: str = "petroil"):
    """Export driver fleet and delivery performance as an Excel spreadsheet."""
    from datetime import datetime
    from src.services.reports import generate_drivers_excel

    stream = generate_drivers_excel(tenant_id)
    filename = f"Reporte_Flota_Choferes_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/api/admin/reports/excel/customers")
async def export_customers_report(tenant_id: str = "petroil"):
    """Export customer directory as an Excel spreadsheet."""
    from datetime import datetime
    from src.services.reports import generate_customers_excel

    stream = generate_customers_excel(tenant_id)
    filename = f"Reporte_Clientes_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
