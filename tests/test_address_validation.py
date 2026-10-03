"""Unit tests for address validation and anti-joke heuristic/semantic checks."""

import pytest
from src.services.address_validator import _fast_heuristic_check, validate_address_with_llm


def test_fast_heuristic_rejects_obvious_jokes():
    """Verify that obvious jokes and nonsensical strings are rejected immediately in 0ms."""
    joke_addresses = [
        "en tu casa",
        "mi casa",
        "en la luna",
        "calle falsa 123",
        "calle inventada 45",
        "no se",
        "jajaja xd",
        "12345",
        "aaaaaa",
        "dónde sea",
        "la vecindad del chavo",
    ]
    for joke in joke_addresses:
        res = _fast_heuristic_check(joke)
        assert res is not None, f"Expected heuristic rejection for '{joke}'"
        is_val, fb = res
        assert is_val is False
        assert len(fb) > 10


def test_fast_heuristic_passes_plausible_strings():
    """Verify that plausible address texts pass the initial fast heuristic filter."""
    plausible_addresses = [
        "Av. Insurgentes 1204, Col. Estadio",
        "Misión San Javier 5246, Fracc. Las Misiones",
        "Calle Benito Juárez #45, Centro",
        "Av. del Mar 500, Zona Dorada",
        "Calle 5 de Mayo 123 entre 21 de Marzo y Aquiles Serdán, Col. Centro",
    ]
    for addr in plausible_addresses:
        res = _fast_heuristic_check(addr)
        assert res is None, f"Expected plausible address '{addr}' to pass heuristic check"


@pytest.mark.asyncio
async def test_validate_address_with_llm_empty():
    """Verify handling of empty or whitespace address input."""
    res = await validate_address_with_llm("", tenant_id="petroil")
    assert res.is_valid is False
    assert "ubicación GPS" in res.user_feedback


@pytest.mark.asyncio
async def test_validate_address_with_llm_joke():
    """Verify that validate_address_with_llm rejects jokes and returns feedback."""
    res = await validate_address_with_llm("en la luna esquina con marte", tenant_id="petroil")
    assert res.is_valid is False
    assert res.is_joke_or_fake is True
    assert len(res.user_feedback) > 10


@pytest.mark.asyncio
async def test_validate_address_with_llm_valid_mazatlan():
    """Verify that a standard real Mazatlán address passes semantic validation."""
    res = await validate_address_with_llm(
        "Misión San Javier 5246, Fracc. Las Misiones, frente al parque",
        tenant_id="petroil"
    )
    assert res.is_valid is True
    assert "Misiones" in res.normalized_address or "Misión" in res.normalized_address
