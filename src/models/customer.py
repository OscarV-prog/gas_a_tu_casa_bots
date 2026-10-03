"""Customer and CustomerAddress data models."""

from __future__ import annotations

import re
from pydantic import BaseModel, Field


class CustomerAddress(BaseModel):
    """Customer registered delivery address."""

    id: int | str | None = None
    customer_id: int | str | None = None
    address: str
    alias: str = "Principal"
    notes: str | None = ""
    is_default: bool = False
    created_at: str | None = None
    updated_at: str | None = None

    def to_display(self, index: int = 1) -> str:
        alias_clean = (self.alias or "").strip()
        es_generico = bool(re.match(r"^(?:principal|predeterminada|nueva\s*direcci[oó]n|direcci[oó]n(?:\s*\d+)?)$", alias_clean, re.I))
        tag = f" [{alias_clean}]" if (alias_clean and not es_generico) else ""
        ref = f" (Referencias: {self.notes})" if self.notes else ""
        return f"{index}. 📍{tag} {self.address}{ref}"


class Customer(BaseModel):
    """Customer profile information with multiple addresses."""

    id: int | str | None = None
    tenant_id: str
    channel: str
    channel_user_id: str
    name: str = ""
    phone: str = ""
    address: str = ""  # Default/primary address string
    notes: str = ""
    created_at: str | None = None
    updated_at: str | None = None
    addresses: list[CustomerAddress] = Field(default_factory=list)

    def to_display(self) -> str:
        """Format customer with all registered addresses for display."""
        parts = []
        if self.name:
            parts.append(f"👤 Cliente: {self.name}")
        if self.phone:
            parts.append(f"📞 Teléfono: {self.phone}")

        if self.addresses:
            parts.append("\n📍 Direcciones de entrega guardadas:")
            for i, addr in enumerate(self.addresses, 1):
                parts.append(addr.to_display(i))
        elif self.address:
            parts.append(f"\n📍 Dirección: {self.address}")

        return "\n".join(parts) if parts else "Sin información registrada."
