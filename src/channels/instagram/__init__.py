"""Instagram Direct channel exports."""

from src.channels.instagram.adapter import InstagramAdapter
from src.channels.instagram.router import router

__all__ = ["InstagramAdapter", "router"]
