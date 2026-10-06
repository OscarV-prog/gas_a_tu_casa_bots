"""Product data models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Product(BaseModel):
    """A single product in the catalog."""

    id: str
    name: str
    description: str
    price: float
    currency: str = "USD"
    category: str = ""
    image_url: str = ""
    tags: list[str] = Field(default_factory=list)
    in_stock: bool = True
    is_promoted: bool = False
    promotion_text: str = ""
    original_price: float | None = None
    promo_discount: float = 0.0

    def to_display(self) -> str:
        """Format product for LLM / user display."""
        parts = [
            f"**{self.name}**",
            f"Price: {self.price} {self.currency}",
            f"Description: {self.description}",
        ]
        if self.is_promoted and self.promotion_text:
            parts.append(f"🔥 SPECIAL: {self.promotion_text}")
        if self.image_url:
            parts.append(f"Image: {self.image_url}")
        return "\n".join(parts)
