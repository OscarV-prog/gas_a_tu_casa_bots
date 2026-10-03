"""Dynamic settings service synchronizing with centralized NestJS backend (/api/settings).

Provides cached, thread-safe, and auto-refreshing settings retrieval.
Whenever keys (tokens, maps keys) are changed in the web dashboard ("Configuración de Plataforma"),
they are fetched automatically without requiring manual .env edits or process restarts.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cached_settings: dict[str, str] = {}
_last_fetch_time: float = 0.0
_CACHE_TTL_SECONDS: float = 120.0  # 2 minutes default cache TTL

# Mapping of remote API keys to local environment variables and aliases
_KEY_MAPPINGS: dict[str, list[str]] = {
    "GOOGLE_MAPS_API_KEY": ["MAPS_API_KEY", "GOOGLE_MAPS_API_KEY"],
    "MESSENGER_PAGE_ACCESS_TOKEN": ["MESSENGER_PAGE_ACCESS_TOKEN", "FACEBOOK_PAGE_ACCESS_TOKEN"],
    "WHATSAPP_TOKEN": ["WHATSAPP_TOKEN", "WHATSAPP_ACCESS_TOKEN"],
    "INSTAGRAM_ACCESS_TOKEN": ["INSTAGRAM_ACCESS_TOKEN"],
    "TELEGRAM_BOT_TOKEN": ["TELEGRAM_BOT_TOKEN"],
    "TELEGRAM_DRIVER_BOT_TOKEN": ["TELEGRAM_DRIVER_BOT_TOKEN"],
    "WHATSAPP_PHONE_NUMBER_ID": ["WHATSAPP_PHONE_NUMBER_ID"],
    "WHATSAPP_VERIFY_TOKEN": ["WHATSAPP_VERIFY_TOKEN"],
    "MESSENGER_VERIFY_TOKEN": ["MESSENGER_VERIFY_TOKEN"],
    "INSTAGRAM_VERIFY_TOKEN": ["INSTAGRAM_VERIFY_TOKEN"],
}


def fetch_remote_settings(force_refresh: bool = False, timeout: int = 4) -> dict[str, str]:
    """Fetch settings from central NestJS endpoint /settings with multi-tenant header."""
    global _cached_settings, _last_fetch_time

    now = time.time()
    with _lock:
        if not force_refresh and _cached_settings and (now - _last_fetch_time) < _CACHE_TTL_SECONDS:
            return dict(_cached_settings)

    try:
        from src.services.api_client import api_get
        items = api_get("/settings", timeout=timeout)
        if isinstance(items, list):
            new_settings: dict[str, str] = {}
            for it in items:
                if not isinstance(it, dict):
                    continue
                k = it.get("key")
                v = str(it.get("value", "")).strip()
                if k and v:
                    new_settings[k] = v
                    # Synchronize into os.environ for transparent compatibility
                    os.environ[k] = v
                    for alias in _KEY_MAPPINGS.get(k, []):
                        os.environ[alias] = v

            with _lock:
                _cached_settings = new_settings
                _last_fetch_time = time.time()
            logger.info(f"[DynamicSettings] Synchronized {len(new_settings)} settings from remote backend.")
            return dict(new_settings)
    except Exception as e:
        logger.warning(f"[DynamicSettings] Failed to fetch remote settings from /settings: {e}. Falling back to cached/env.")

    with _lock:
        return dict(_cached_settings)


def get_dynamic_setting(key: str, default: str = "", force_refresh: bool = False) -> str:
    """Retrieve setting dynamically, prioritizing remote settings then environment fallback."""
    settings = fetch_remote_settings(force_refresh=force_refresh)
    if key in settings and settings[key]:
        return settings[key]

    # Check aliases
    for primary_key, aliases in _KEY_MAPPINGS.items():
        if key in aliases and primary_key in settings and settings[primary_key]:
            return settings[primary_key]

    # Fallback to os.getenv or provided default
    return os.getenv(key, default)


def invalidate_dynamic_settings_cache(clear_cache: bool = True) -> None:
    """Invalidate settings cache so the next call forces a remote re-fetch."""
    global _last_fetch_time, _cached_settings
    with _lock:
        _last_fetch_time = 0.0
        if clear_cache:
            _cached_settings.clear()
    logger.info("[DynamicSettings] Cache invalidated. Next access will re-query remote /settings.")
