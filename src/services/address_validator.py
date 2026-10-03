"""Address validation and verification service powered by heuristics and LLM semantic analysis."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from src.config.llm_provider import create_llm
from src.config.tenant_config import get_tenant
from src.services.geocoding import clean_address_for_geocoding, geocode_address
from src.services.telemetry import telemetry

logger = logging.getLogger(__name__)


@dataclass
class AddressValidationResult:
    is_valid: bool
    is_joke_or_fake: bool
    confidence: float
    normalized_address: str
    street: str
    number: str
    colonia: str
    references: str
    reason: str
    user_feedback: str


# Patrones obvios de bromas, insultos o textos sin sentido
OBVIOUS_JOKE_PATTERNS = [
    r"\b(?:tu\s+casa|mi\s+casa|la\s+luna|el\s+cielo|el\s+infierno|marte|jupiter|saturno)\b",
    r"\b(?:calle\s+falsa|calle\s+inventada|calle\s+de\s+la\s+alegr[ií]a|calle\s+sin\s+nombre|vecindad\s+del\s+chavo)\b",
    r"\b(?:no\s+s[eé]|no\s+tengo|qui[eé]n\s+sabe|d[oó]nde\s+sea|en\s+el\s+monte|en\s+la\s+esquina\s+de\s+la\s+nada)\b",
    r"\b(?:jajaja|jejeje|xd|lol|pito|culo|verga|chinga|puto|puta|mamadas?|pendejo)\b",
    r"^([a-zA-Z0-9])\1{4,}$",  # Repeticiones tipo aaaaa, 11111, zzzzz
    r"^[0-9\s\.\,\-]+$",         # Solo números o signos
]


def _fast_heuristic_check(text: str) -> tuple[bool, str] | None:
    """Evaluación rápida por heurísticas para descartar bromas obvias en 0ms."""
    t_clean = text.lower().strip()

    if len(t_clean) < 6:
        return False, "La dirección es demasiado corta para ser un domicilio real. Por favor escribe calle, número y colonia."

    for pat in OBVIOUS_JOKE_PATTERNS:
        if re.search(pat, t_clean, re.IGNORECASE):
            return False, "La dirección ingresada no parece ser un domicilio válido o existente. Por favor proporciona una dirección real (calle, número y colonia) o comparte tu ubicación GPS 📍."

    return None


async def validate_address_with_llm(
    address_text: str,
    tenant_id: str = "petroil",
    city_context: str = "México / zona de cobertura de la sucursal",
) -> AddressValidationResult:
    """Analiza semánticamente si una dirección es real, plausible y entregable en la localidad/sucursal objetivo."""
    raw = (address_text or "").strip()
    if not raw:
        return AddressValidationResult(
            is_valid=False,
            is_joke_or_fake=False,
            confidence=0.0,
            normalized_address="",
            street="",
            number="",
            colonia="",
            references="",
            reason="Texto vacío",
            user_feedback="Por favor escribe tu calle, número y colonia o presiona el botón para compartir tu ubicación GPS 📍.",
        )

    # 1. Filtro rápido heurístico
    fast_check = _fast_heuristic_check(raw)
    if fast_check is not None:
        is_val, fb = fast_check
        return AddressValidationResult(
            is_valid=is_val,
            is_joke_or_fake=not is_val,
            confidence=0.95 if not is_val else 0.5,
            normalized_address=raw,
            street="",
            number="",
            colonia="",
            references="",
            reason="Rechazado por heurística de broma/incompletitud",
            user_feedback=fb,
        )

    # 2. Análisis semántico con LLM estructurado
    system_prompt = (
        "Eres un auditor y validador de direcciones de entrega de Gas LP para las sucursales de la empresa en México (ej. Mazatlán, Culiacán, Los Mochis, Guasave, Escuinapa y demás zonas con cobertura).\n"
        "Tu misión es clasificar si el texto ingresado por un cliente representa un DOMICILIO REAL, PLAUSIBLE Y ENTREGABLE en su localidad, "
        "o si es una DIRECCIÓN FALSA, UNA BROMA, UN TEXTO ABSURDO O ESTÁ INCOMPLETA.\n\n"
        "CRITERIOS DE VALIDACIÓN:\n"
        "- VÁLIDA (is_valid=true): Contiene datos suficientes para que una unidad de reparto localice el lugar en la ciudad o municipio correspondiente "
        "(ej. Calle/Avenida + Número o entrecalles + Colonia/Fraccionamiento/Localidad, o referencias claras como 'Av. Insurgentes 1204 Col. Estadio', 'Blvd. Pedro Infante 2200 Culiacán', 'Misión San Javier 5246 Las Misiones', 'Calle Benito Juárez 45 entre 21 de Marzo y 5 de Mayo Centro').\n"
        "- FALSA / BROMA / ABSURDA (is_valid=false, is_joke_or_fake=true): Textos ficticios como 'calle falsa 123', 'en mi casa', 'la luna', 'calle de los sueños', 'al lado de la tienda de don pepe sin calle', insultos o bromas.\n"
        "- INCOMPLETA (is_valid=false, is_joke_or_fake=false): Solo pone una palabra suelta sin número ni colonia ni referencias (ej. 'Flores Magón', 'calle México').\n\n"
        "DEBES RESPONDER EXCLUSIVAMENTE CON UN OBJETO JSON VÁLIDO CON ESTE ESQUEMA EXACTO:\n"
        "{\n"
        '  "is_valid": true,\n'
        '  "is_joke_or_fake": false,\n'
        '  "confidence": 0.95,\n'
        '  "street": "Misión San Javier",\n'
        '  "number": "5246",\n'
        '  "colonia": "Las Misiones",\n'
        '  "references": "Portón blanco",\n'
        '  "normalized_address": "Misión San Javier 5246, Fracc. Las Misiones",\n'
        '  "reason": "Explicación breve de la validación",\n'
        '  "user_feedback": "Mensaje cordial para el cliente si falta algún dato o si fue rechazada"\n'
        "}"
    )

    user_prompt = f"Dirección recibida del cliente para entrega en {city_context}:\n\"{raw}\""

    try:
        tc = get_tenant(tenant_id)
        llm = create_llm(tc)

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        approx_in = len(system_prompt.split()) + len(user_prompt.split()) + 30
        telemetry.record_message(channel="address_validator", is_llm=True, is_fallback=True, tokens_in=approx_in)

        response = await llm.ainvoke(messages)
        resp_text = response.content if isinstance(response.content, str) else str(response.content)

        approx_out = len(resp_text.split()) + 20
        telemetry.record_message(channel="address_validator", is_llm=True, is_fallback=True, tokens_out=approx_out)

        # Extraer JSON de la respuesta
        m_json = re.search(r"\{[\s\S]*\}", resp_text)
        if m_json:
            data = json.loads(m_json.group(0))
            is_valid = bool(data.get("is_valid", False))
            is_joke = bool(data.get("is_joke_or_fake", False))
            conf = float(data.get("confidence", 0.8))
            norm = str(data.get("normalized_address") or raw).strip()
            street = str(data.get("street") or "").strip()
            number = str(data.get("number") or "").strip()
            colonia = str(data.get("colonia") or "").strip()
            refs = str(data.get("references") or "").strip()
            reason = str(data.get("reason") or "").strip()
            fb = str(data.get("user_feedback") or "").strip()

            if not fb:
                if not is_valid:
                    fb = "Por favor indícanos tu **calle, número exterior y colonia** (o referencias de tu domicilio) para poder realizar tu entrega correctamente 📍."
                else:
                    fb = "Dirección validada con éxito."

            return AddressValidationResult(
                is_valid=is_valid,
                is_joke_or_fake=is_joke,
                confidence=conf,
                normalized_address=norm if is_valid else raw,
                street=street,
                number=number,
                colonia=colonia,
                references=refs,
                reason=reason,
                user_feedback=fb,
            )
    except Exception as e:
        logger.warning(f"[AddressValidator] Error validando dirección con LLM: {e}")

    # Fallback si el LLM no respondió: validar si tiene al menos longitud razonable y números/calle
    has_digits = bool(re.search(r"\d+", raw))
    has_words = len(raw.split()) >= 3
    is_plausible = has_digits and has_words

    return AddressValidationResult(
        is_valid=is_plausible,
        is_joke_or_fake=False,
        confidence=0.6,
        normalized_address=raw,
        street="",
        number="",
        colonia="",
        references="",
        reason="Validación heurística de respaldo por fallback",
        user_feedback="Por favor proporciona calle, número y colonia completa." if not is_plausible else "",
    )
