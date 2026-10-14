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
    "OPENAI_API_KEY": ["OPENAI_API_KEY"],
    "ANTHROPIC_API_KEY": ["ANTHROPIC_API_KEY"],
    "OPENROUTER_API_KEY": ["OPENROUTER_API_KEY"],
    "LANGCHAIN_API_KEY": ["LANGCHAIN_API_KEY"],
    "GOOGLE_MAPS_API_KEY": ["MAPS_API_KEY", "GOOGLE_MAPS_API_KEY"],
    "MESSENGER_PAGE_ACCESS_TOKEN": ["MESSENGER_PAGE_ACCESS_TOKEN", "FACEBOOK_PAGE_ACCESS_TOKEN"],
    "MESSENGER_APP_SECRET": ["MESSENGER_APP_SECRET", "FACEBOOK_APP_SECRET"],
    "MESSENGER_PAGE_ID": ["MESSENGER_PAGE_ID"],
    "MESSENGER_API_VERSION": ["MESSENGER_API_VERSION"],
    "WHATSAPP_TOKEN": ["WHATSAPP_TOKEN", "WHATSAPP_ACCESS_TOKEN"],
    "WHATSAPP_PHONE_NUMBER_ID": ["WHATSAPP_PHONE_NUMBER_ID"],
    "WHATSAPP_VERIFY_TOKEN": ["WHATSAPP_VERIFY_TOKEN"],
    "WHATSAPP_BUSINESS_ACCOUNT_ID": ["WHATSAPP_BUSINESS_ACCOUNT_ID", "WHATSAPP_WABA_ID"],
    "WHATSAPP_APP_SECRET": ["WHATSAPP_APP_SECRET"],
    "WHATSAPP_API_VERSION": ["WHATSAPP_API_VERSION"],
    "INSTAGRAM_ACCESS_TOKEN": ["INSTAGRAM_ACCESS_TOKEN"],
    "INSTAGRAM_VERIFY_TOKEN": ["INSTAGRAM_VERIFY_TOKEN"],
    "INSTAGRAM_ACCOUNT_ID": ["INSTAGRAM_ACCOUNT_ID"],
    "INSTAGRAM_APP_SECRET": ["INSTAGRAM_APP_SECRET"],
    "INSTAGRAM_API_VERSION": ["INSTAGRAM_API_VERSION"],
    "TELEGRAM_BOT_TOKEN": [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_MAZATLAN",
        "TELEGRAM_PETROIL",
        "TELEGRAM_TOKEN",
        "TELEGRAM_BOT_MAZATLAN_TOKEN",
    ],
    "TELEGRAM_MAZATLAN": [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_MAZATLAN",
        "TELEGRAM_PETROIL",
        "TELEGRAM_TOKEN",
        "TELEGRAM_BOT_MAZATLAN_TOKEN",
    ],
    "TELEGRAM_PETROIL": [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_MAZATLAN",
        "TELEGRAM_PETROIL",
        "TELEGRAM_TOKEN",
        "TELEGRAM_BOT_MAZATLAN_TOKEN",
    ],
    "TELEGRAM_BOT_GASCYTSA_TOKEN": [
        "TELEGRAM_BOT_GASCYTSA_TOKEN",
        "TELEGRAM_GASCYTSA",
        "TELEGRAM_GASCYTSA_TOKEN",
        "TELEGRAM_CULIACAN",
    ],
    "TELEGRAM_GASCYTSA": [
        "TELEGRAM_BOT_GASCYTSA_TOKEN",
        "TELEGRAM_GASCYTSA",
        "TELEGRAM_GASCYTSA_TOKEN",
        "TELEGRAM_CULIACAN",
    ],
    "TELEGRAM_GASCYTSA_TOKEN": [
        "TELEGRAM_BOT_GASCYTSA_TOKEN",
        "TELEGRAM_GASCYTSA",
        "TELEGRAM_GASCYTSA_TOKEN",
        "TELEGRAM_CULIACAN",
    ],
    "TELEGRAM_CULIACAN": [
        "TELEGRAM_BOT_GASCYTSA_TOKEN",
        "TELEGRAM_GASCYTSA",
        "TELEGRAM_GASCYTSA_TOKEN",
        "TELEGRAM_CULIACAN",
    ],
    "TELEGRAM_DRIVER_BOT_TOKEN": [
        "TELEGRAM_DRIVER_BOT_TOKEN",
        "DRIVER_BOT_TOKEN",
        "TELEGRAM_CHOFERES",
        "TELEGRAM_CHOFER",
    ],
    "DRIVER_BOT_TOKEN": [
        "TELEGRAM_DRIVER_BOT_TOKEN",
        "DRIVER_BOT_TOKEN",
        "TELEGRAM_CHOFERES",
        "TELEGRAM_CHOFER",
    ],
    "API_EMAIL": ["API_EMAIL", "OPERATOR_EMAIL", "API_USER"],
    "API_PASSWORD": ["API_PASSWORD", "OPERATOR_PASSWORD", "API_PASS"],
    "API_TOKEN": ["API_TOKEN", "AUTH_TOKEN", "API_KEY"],
    "DEFAULT_CITY": ["DEFAULT_CITY"],
    "CORS_ORIGINS": ["CORS_ORIGINS"],
    "PUBLIC_BASE_URL": ["PUBLIC_BASE_URL"],
}



def fetch_remote_settings(tenant_id: str | None = None, force_refresh: bool = False, timeout: int = 4) -> dict[str, str]:
    """Fetch settings from central NestJS endpoint /settings with multi-tenant header."""
    global _cached_settings, _last_fetch_time

    now = time.time()
    with _lock:
        if not force_refresh and _cached_settings and (now - _last_fetch_time) < _CACHE_TTL_SECONDS:
            return dict(_cached_settings)

    try:
        from src.services.api_client import api_get
        new_settings: dict[str, str] = {}

        # 1. Consultar tenant base de plataforma (petroil) para credenciales comunes (LLM, mapas, etc.)
        try:
            petroil_items = api_get("/settings", tenant_id="petroil", timeout=timeout)
            if isinstance(petroil_items, list):
                for it in petroil_items:
                    if not isinstance(it, dict):
                        continue
                    k = it.get("key")
                    v = str(it.get("value", "")).strip()
                    if k and v:
                        new_settings[k] = v
                        os.environ[k] = v
                        for alias in _KEY_MAPPINGS.get(k, []):
                            os.environ[alias] = v
                            new_settings[alias] = v
        except Exception as e_petroil:
            logger.debug(f"[DynamicSettings] Error fetching petroil settings: {e_petroil}")

        # 2. Consultar tenant gascytsa para credenciales específicas (TELEGRAM_GASCYTSA)
        try:
            gas_items = api_get("/settings", tenant_id="gascytsa", timeout=timeout)
            if isinstance(gas_items, list):
                for it in gas_items:
                    if not isinstance(it, dict):
                        continue
                    k = it.get("key")
                    v = str(it.get("value", "")).strip()
                    if k and v:
                        new_settings[k] = v
                        os.environ[k] = v
                        for alias in _KEY_MAPPINGS.get(k, []):
                            os.environ[alias] = v
                            new_settings[alias] = v
        except Exception as e_gas:
            logger.debug(f"[DynamicSettings] Error fetching gascytsa settings: {e_gas}")

        # 3. Si se solicitó un tenant_id diferente a petroil y gascytsa, consultarlo también
        if tenant_id and tenant_id not in ("petroil", "gascytsa"):
            try:
                custom_items = api_get("/settings", tenant_id=tenant_id, timeout=timeout)
                if isinstance(custom_items, list):
                    for it in custom_items:
                        if not isinstance(it, dict):
                            continue
                        k = it.get("key")
                        v = str(it.get("value", "")).strip()
                        if k and v:
                            new_settings[k] = v
                            os.environ[k] = v
                            for alias in _KEY_MAPPINGS.get(k, []):
                                os.environ[alias] = v
                                new_settings[alias] = v
            except Exception as e_custom:
                logger.debug(f"[DynamicSettings] Error fetching custom tenant '{tenant_id}' settings: {e_custom}")

        with _lock:
            _cached_settings = new_settings
            _last_fetch_time = time.time()
        logger.info(f"[DynamicSettings] Synchronized {len(new_settings)} settings from remote backend.")
        return dict(new_settings)
    except Exception as e:
        logger.warning(f"[DynamicSettings] Failed to fetch remote settings from /settings: {e}. Falling back to cached/env.")

    with _lock:
        return dict(_cached_settings)


def export_env_file(filepath: str = "/tmp/dynamic_env.sh") -> None:
    """Fetch remote settings and write shell export statements to a file so Bash entrypoint can source them."""
    settings = fetch_remote_settings(force_refresh=True)
    try:
        lines = ["#!/bin/bash\n"]
        for k, v in sorted(settings.items()):
            if not k or not v:
                continue
            safe_v = v.replace("'", "'\\''")
            lines.append(f"export {k}='{safe_v}'\n")

        dirname = os.path.dirname(filepath)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.writelines(lines)
        logger.info(f"[DynamicSettings] Exported {len(settings)} variables to {filepath}")
    except Exception as e:
        logger.warning(f"[DynamicSettings] Could not export dynamic env file to {filepath}: {e}")


def get_dynamic_setting(key: str, default: str = "", tenant_id: str | None = None, force_refresh: bool = False) -> str:
    """Retrieve setting, prioritizing local environment (.env) first, then remote backend settings."""
    # 1. Primero buscar en variables de entorno locales (.env / os.environ)
    env_val = os.getenv(key)
    if env_val and env_val.strip():
        return env_val.strip()

    # Buscar en aliases de variables de entorno locales
    for primary_key, aliases in _KEY_MAPPINGS.items():
        if key == primary_key or key in aliases:
            for alias in [primary_key] + aliases:
                val = os.getenv(alias)
                if val and val.strip():
                    return val.strip()

    # 2. Si no está en el .env local, buscar en el endpoint remoto del backend central
    settings = fetch_remote_settings(tenant_id=tenant_id, force_refresh=force_refresh)
    if key in settings and settings[key]:
        return settings[key]

    # Buscar aliases en configuraciones remotas
    for primary_key, aliases in _KEY_MAPPINGS.items():
        if key == primary_key or key in aliases:
            for alias in [primary_key] + aliases:
                if alias in settings and settings[alias]:
                    return settings[alias]

    return default


def invalidate_dynamic_settings_cache(clear_cache: bool = True) -> None:
    """Invalidate settings cache so the next call forces a remote re-fetch."""
    global _last_fetch_time, _cached_settings
    with _lock:
        _last_fetch_time = 0.0
        if clear_cache:
            _cached_settings.clear()
    logger.info("[DynamicSettings] Cache invalidated. Next access will re-query remote /settings.")
