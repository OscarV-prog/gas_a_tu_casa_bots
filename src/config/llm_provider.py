"""LLM provider factory."""

from __future__ import annotations

import os

from langchain_core.language_models import BaseChatModel

from src.config.tenant_config import TenantConfig


def create_llm(tenant_config: TenantConfig) -> BaseChatModel:
    """Create an LLM instance based on tenant config."""

    cfg = tenant_config.llm
    provider = cfg.provider.lower()

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=cfg.model,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
        )

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=cfg.model,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
        )

    if provider == "openrouter":
        from langchain_openai import ChatOpenAI

        api_key = os.getenv("OPENROUTER_API_KEY")

        if not api_key:
            raise ValueError(
                "No se encontró OPENROUTER_API_KEY en el archivo .env"
            )

        # OpenRouter provider routing & price limits
        prov_cfg = cfg.provider_routing.get("provider") if cfg.provider_routing else None
        if not prov_cfg:
            prov_cfg = {"sort": "price"}
        extra_body = cfg.extra_body or {"provider": prov_cfg}

        model_name = os.getenv("LLM_MODEL", cfg.model)

        return ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens or 4096,
            extra_body=extra_body,
        )

    raise ValueError(
        f"Unknown LLM provider: '{provider}'. "
        f"Supported: openai, anthropic, openrouter"
    )