"""Tenant configuration loader.

Loads tenant-specific settings from YAML files. Each tenant folder
contains a config.yaml and products.json that define the agent's
personality, rules, LLM settings, and product catalog.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from src.config.settings import get_settings


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class AgentConfig(BaseModel):
    """Agent personality and behaviour rules."""

    name: str = "Sales Agent"
    role: str = "Sales Consultant"
    personality: str = "You are a helpful sales consultant."
    rules: list[str] = Field(default_factory=list)


class LLMConfig(BaseModel):
    """LLM provider settings (can differ per tenant)."""

    provider: str = "openai"  # "openai", "anthropic", or "openrouter"
    model: str = "gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: int = 4096
    provider_routing: dict[str, Any] = Field(default_factory=dict)
    extra_body: dict[str, Any] = Field(default_factory=dict)


class FeaturesConfig(BaseModel):
    """Feature flags – toggle capabilities per tenant."""

    image_search: bool = True
    promotions: bool = True
    upsell: bool = True


class TenantConfig(BaseModel):
    """Complete configuration for one tenant / business."""

    tenant_id: str
    business_name: str
    language: str = "en"
    agent: AgentConfig = Field(default_factory=AgentConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _load_yaml(path: Path) -> dict[str, Any]:
    """Read and parse a YAML file."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=32)
def get_tenant(tenant_id: str) -> TenantConfig:
    """Load a tenant config by ID. Results are cached."""
    tenants_dir = Path(get_settings().tenants_dir)
    config_path = tenants_dir / tenant_id / "config.yaml"

    if not config_path.exists():
        raise FileNotFoundError(
            f"Tenant config not found: {config_path}. "
            f"Available tenants: {list_tenants()}"
        )

    data = _load_yaml(config_path)
    data.setdefault("tenant_id", tenant_id)
    return TenantConfig(**data)


def list_tenants() -> list[str]:
    """Return all available tenant IDs."""
    tenants_dir = Path(get_settings().tenants_dir)
    if not tenants_dir.exists():
        return []
    return sorted(
        d.name
        for d in tenants_dir.iterdir()
        if d.is_dir() and (d / "config.yaml").exists()
    )
