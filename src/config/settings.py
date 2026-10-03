"""Global application settings loaded from environment variables and centralized remote backend."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any
import os

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv(override=True)

from src.services.dynamic_settings import (
    fetch_remote_settings,
    get_dynamic_setting,
    invalidate_dynamic_settings_cache,
)


def load_dynamic_settings() -> None:
    """Carga configuraciones dinámicas desde el endpoint central GET /settings (NestJS)."""
    try:
        fetch_remote_settings(force_refresh=True, timeout=4)
    except Exception:
        pass


# Carga inicial al importar módulo
load_dynamic_settings()


# Mapeo de atributos de Settings a claves dinámicas del backend central
_DYNAMIC_ATTR_MAP: dict[str, tuple[str, list[str]]] = {
    "whatsapp_token": ("WHATSAPP_TOKEN", ["WHATSAPP_ACCESS_TOKEN"]),
    "whatsapp_phone_number_id": ("WHATSAPP_PHONE_NUMBER_ID", []),
    "whatsapp_verify_token": ("WHATSAPP_VERIFY_TOKEN", []),
    "whatsapp_business_account_id": ("WHATSAPP_BUSINESS_ACCOUNT_ID", ["WHATSAPP_WABA_ID"]),
    "messenger_page_access_token": ("MESSENGER_PAGE_ACCESS_TOKEN", ["FACEBOOK_PAGE_ACCESS_TOKEN"]),
    "messenger_verify_token": ("MESSENGER_VERIFY_TOKEN", ["WHATSAPP_VERIFY_TOKEN"]),
    "messenger_page_id": ("MESSENGER_PAGE_ID", []),
    "instagram_access_token": ("INSTAGRAM_ACCESS_TOKEN", ["MESSENGER_PAGE_ACCESS_TOKEN", "WHATSAPP_TOKEN"]),
    "instagram_verify_token": ("INSTAGRAM_VERIFY_TOKEN", ["MESSENGER_VERIFY_TOKEN"]),
    "instagram_account_id": ("INSTAGRAM_ACCOUNT_ID", []),
    "telegram_bot_token": ("TELEGRAM_BOT_TOKEN", []),
    "telegram_driver_bot_token": ("TELEGRAM_DRIVER_BOT_TOKEN", []),
    "maps_api_key": ("GOOGLE_MAPS_API_KEY", ["MAPS_API_KEY"]),
}


class Settings(BaseModel):
    """Application-level settings (not tenant-specific) with live dynamic synchronization."""

    anthropic_api_key: str = Field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", "")
    )
    langchain_api_key: str = Field(
        default_factory=lambda: os.getenv("LANGCHAIN_API_KEY", "")
    )
    tenants_dir: str = Field(
        default_factory=lambda: os.getenv("TENANTS_DIR", "./tenants")
    )
    database_path: str = Field(
        default_factory=lambda: os.getenv("DATABASE_PATH", "./data/sales_agent.db")
    )
    telegram_bot_token: str = Field(
        default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", "")
    )
    telegram_driver_bot_token: str = Field(
        default_factory=lambda: os.getenv("TELEGRAM_DRIVER_BOT_TOKEN", "")
    )
    default_city: str = Field(
        default_factory=lambda: os.getenv("DEFAULT_CITY", "Mazatlán, Sinaloa, México")
    )
    maps_api_key: str = Field(
        default_factory=lambda: os.getenv("MAPS_API_KEY", os.getenv("GOOGLE_MAPS_API_KEY", ""))
    )
    whatsapp_token: str = Field(
        default_factory=lambda: os.getenv("WHATSAPP_TOKEN", os.getenv("WHATSAPP_ACCESS_TOKEN", ""))
    )
    whatsapp_phone_number_id: str = Field(
        default_factory=lambda: os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    )
    whatsapp_verify_token: str = Field(
        default_factory=lambda: os.getenv("WHATSAPP_VERIFY_TOKEN", "")
    )
    whatsapp_business_account_id: str = Field(
        default_factory=lambda: os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID", os.getenv("WHATSAPP_WABA_ID", ""))
    )
    whatsapp_api_version: str = Field(
        default_factory=lambda: os.getenv("WHATSAPP_API_VERSION", "v21.0")
    )
    whatsapp_app_secret: str = Field(
        default_factory=lambda: os.getenv("WHATSAPP_APP_SECRET", "")
    )
    # Facebook Messenger Configuration
    messenger_page_access_token: str = Field(
        default_factory=lambda: os.getenv("MESSENGER_PAGE_ACCESS_TOKEN", os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", ""))
    )
    messenger_verify_token: str = Field(
        default_factory=lambda: os.getenv("MESSENGER_VERIFY_TOKEN", os.getenv("WHATSAPP_VERIFY_TOKEN", "petroil_gas_webhook_secret"))
    )
    messenger_page_id: str = Field(
        default_factory=lambda: os.getenv("MESSENGER_PAGE_ID", "")
    )
    messenger_app_secret: str = Field(
        default_factory=lambda: os.getenv("MESSENGER_APP_SECRET", os.getenv("FACEBOOK_APP_SECRET", ""))
    )
    messenger_api_version: str = Field(
        default_factory=lambda: os.getenv("MESSENGER_API_VERSION", "v21.0")
    )
    # Instagram Direct Messaging Configuration (Meta Graph API)
    instagram_access_token: str = Field(
        default_factory=lambda: os.getenv("INSTAGRAM_ACCESS_TOKEN", os.getenv("MESSENGER_PAGE_ACCESS_TOKEN", ""))
    )
    instagram_verify_token: str = Field(
        default_factory=lambda: os.getenv("INSTAGRAM_VERIFY_TOKEN", os.getenv("MESSENGER_VERIFY_TOKEN", "petroil_gas_webhook_secret"))
    )
    instagram_account_id: str = Field(
        default_factory=lambda: os.getenv("INSTAGRAM_ACCOUNT_ID", "")
    )
    instagram_app_secret: str = Field(
        default_factory=lambda: os.getenv("INSTAGRAM_APP_SECRET", os.getenv("MESSENGER_APP_SECRET", ""))
    )
    instagram_api_version: str = Field(
        default_factory=lambda: os.getenv("INSTAGRAM_API_VERSION", "v21.0")
    )
    cors_origins: str = Field(
        default_factory=lambda: os.getenv("CORS_ORIGINS", "*")
    )
    public_base_url: str = Field(
        default_factory=lambda: os.getenv("PUBLIC_BASE_URL", "https://und-mpg-observation-pennsylvania.trycloudflare.com")
    )

    def __init__(self, **data: Any):
        super().__init__(**data)
        object.__setattr__(self, "_overrides", {})
        for k, v in data.items():
            if v:
                self._overrides[k] = v

    def __getattribute__(self, name: str) -> Any:
        if name in ("_overrides", "__dict__", "model_dump", "model_dump_json", "__fields__"):
            return super().__getattribute__(name)

        try:
            overrides = object.__getattribute__(self, "_overrides")
            if name in overrides:
                return overrides[name]
        except AttributeError:
            pass

        # Si el atributo es de configuración dinámica, buscar primero en remote settings
        if name in _DYNAMIC_ATTR_MAP:
            primary_key, fallbacks = _DYNAMIC_ATTR_MAP[name]
            val = get_dynamic_setting(primary_key)
            if val:
                return val
            for fb in fallbacks:
                val = get_dynamic_setting(fb)
                if val:
                    return val

        return super().__getattribute__(name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name != "_overrides":
            try:
                self._overrides[name] = value
            except Exception:
                pass
        super().__setattr__(name, value)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return application settings instance."""
    return Settings()
