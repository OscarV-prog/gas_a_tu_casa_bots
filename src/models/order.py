"""Order and OrderItem data models."""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class OrderItem(BaseModel):
    """A line item within an order."""

    id: int | str | None = None
    order_id: int | str | None = None
    product_id: str
    product_name: str
    quantity: int = 1
    unit_price: float
    subtotal: float

    def to_display(self) -> str:
        return f"- {self.quantity}x {self.product_name} (${self.unit_price:.2f} c/u) = ${self.subtotal:.2f}"


class Order(BaseModel):
    """Customer order."""

    id: int | str | None = None
    tenant_id: str = "petroil"
    customer_id: int | str | None = None
    customer_name: str
    customer_phone: str
    delivery_address: str
    delivery_schedule: str = "Lo antes posible"
    total_amount: float
    currency: str = "MXN"
    status: Literal["pending", "confirmed", "scheduled", "assigned", "in_route", "delivered", "cancelled", "rejected_by_driver"] = "confirmed"
    payment_method: str = "Efectivo"
    notes: str = ""
    channel: str = ""
    channel_user_id: str = ""
    driver_id: int | str | None = None
    driver_name: str | None = None
    delivery_lat: float | None = None
    delivery_lng: float | None = None
    live_location_message_id: int | None = None
    live_location_chat_id: str | None = None
    driver_message_ids: str | None = None
    assigned_at: str | None = None
    delivered_at: str | None = None
    scheduled_for: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    cancelled_by: str | None = None
    cancellation_reason: str | None = None
    items: list[OrderItem] = Field(default_factory=list)

    def to_display(self) -> str:
        """Format order summary for display."""
        status_map = {
            "pending": "⏳ Pendiente",
            "confirmed": "✅ Confirmado",
            "scheduled": "🗓️ Programado para fecha posterior",
            "assigned": "📋 Asignado a Chofer",
            "in_route": "🚚 En ruta / camino",
            "delivered": "📦 Entregado",
            "cancelled": "❌ Cancelado",
        }
        status_str = status_map.get(self.status, self.status)

        pay_str = "💵 Efectivo" if "efectivo" in self.payment_method.lower() else f"💳 {self.payment_method}"
        
        lines = [
            f"📋 **Pedido #{self.id}**",
            f"Estado: {status_str}",
            f"Cliente: {self.customer_name}",
            f"Teléfono: {self.customer_phone}",
            f"Dirección de entrega: {self.delivery_address}",
            f"📅 Horario de entrega: {self.delivery_schedule}",
            f"💳 Método de pago: {pay_str}",
        ]
        if self.driver_name:
            lines.append(f"🚗 Chofer asignado: {self.driver_name}")
        if self.notes:
            lines.append(f"Notas/Referencias: {self.notes}")

        lines.append("\n**Productos:**")
        for item in self.items:
            lines.append(item.to_display())

        lines.append(f"\n💰 **Total:** ${self.total_amount:.2f} {self.currency}")
        return "\n".join(lines)
