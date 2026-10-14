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
from src.services.geocoding import clean_address_for_geocoding, geocode_address, verify_address_city_grounding
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
    r"\b(?:tu\s+casa|mi\s+casa|la\s+luna|el\s+cielo|el\s+infierno|marte|jupiter|saturno|narnia|hogwarts|el\s+pais\s+de\s+las\s+maravillas)\b",
    r"\b(?:calle\s+falsa|calle\s+inventada|calle\s+imaginaria|calle\s+fantasma|calle\s+inexistente|calle\s+de\s+la\s+alegr[ií]a|calle\s+sin\s+nombre|vecindad\s+del\s+chavo)\b",
    r"\b(?:no\s+s[eé]|no\s+tengo|qui[eé]n\s+sabe|d[oó]nde\s+sea|en\s+el\s+monte|en\s+el\s+cerro|en\s+la\s+esquina\s+de\s+la\s+nada|por\s+ah[ií]|donde\s+caiga|en\s+la\s+calle)\b",
    r"\b(?:jajaja|jejeje|xd|lol|pito|culo|verga|chinga|puto|puta|mamadas?|pendejo)\b",
    r"^([a-zA-Z0-9])\1{4,}$",  # Repeticiones tipo aaaaa, 11111, zzzzz
    r"^[0-9\s\.\,\-]+$",         # Solo números o signos
]

# Ciudades, municipios, estados y países fuera de cobertura para Mazatlán (Petroil)
OUT_LOCATIONS_MAZATLAN = [
    # Colonias, sectores, avenidas y zonas de Culiacán que deben rechazarse categóricamente en Mazatlán
    r"\b(?:colinas\s+de\s+san\s+miguel|tres\s+r[ií]os|desarrollo\s+urbano\s+tres\s+r[ií]os|las\s+quintas|quintas|infonavit\s+humaya|humaya|r[ií]o\s+humaya|sector\s+humaya|valle\s+alto|barrancos|infonavit\s+barrancos|pedro\s+infante|blvd\.?\s*pedro\s+infante|enrique\s+s[aá]nchez\s+alonso|lola\s+beltr[aá]n|rolando\s+arjona|la\s+conquista|stanza\s+toscana|stanza\s+florencia|stanza|bachigualato|nakayama|alturas\s+del\s+sur|isla\s+musala|aguaruto|costa\s+rica|eldorado|quil[aá]|limita\s+de\s+iturbe|prol\.?\s*[aá]lvaro\s+obreg[oó]n|avenida\s+[aá]lvaro\s+obreg[oó]n|av\.?\s+[aá]lvaro\s+obreg[oó]n|[aá]lvaro\s+obreg[oó]n\s+(?:norte|sur|\d+)|calzada\s+heroico\s+colegio\s+militar|montebello|santa\s+fe\s+culiac[aá]n|san\s+rafael\s+culiac[aá]n|villa\s+universidad|plaza\s+cuatro\s+r[ií]os|plaza\s+ceiba|forum\s+culiac[aá]n|parque\s+las\s+riberas|estadio\s+tomateros|jard[ií]n\s+bot[aá]nico\s+culiac[aá]n)\b",
    r"\b(?:cerro\s+de\s+la\s+campana|campana\s+culiac[aá]n|tierra\s+blanca|chapultepec|ciudades\s+hermanas|blvd\.?\s*ciudades\s+hermanas|el\s+palmito|palmito|palmito\s+viejo|culiacancito|portalegre|portalegre\s+elite|cedros|los\s+cedros|chula\s+vista|chulavista|emiliano\s+zapata|blvd\.?\s*emiliano\s+zapata|calzada\s+aeropuerto|blvd\.?\s*aeropuerto|aeropuerto\s+culiac[aá]n|plaza\s+fiesta|plaza\s+san\s+isidro|plaza\s+sendero\s+culiac[aá]n|loma\s+linda|guadalupe\s+victoria|10\s+de\s+mayo|diez\s+de\s+mayo|las\s+coloradas|la\s+campiña|campiña|interlomas|universitarios|blvd\.?\s*universitarios|malecon\s+nuevo|malec[oó]n\s+nuevo|malecon\s+viejo|malec[oó]n\s+viejo|diego\s+valad[eé]s|colinas\s+del\s+humaya|plutarco\s+el[ií]as\s+calles|jorge\s+almada|recursos\s+hidr[aá]ulicos|vallado|infonavit\s+el\s+vallado|campo\s+el\s+diez|el\s+diez|costita|la\s+costita|bellavista|los\s+pinos)\b",
    # Otros municipios de Sinaloa
    r"\b(?:culiac[aá]n|cln|navolato|los\s+mochis|mochis|guasave|escuinapa|concordia|el\s+rosario|el\s+fuerte|choix|guam[uú]chil|salvador\s+alvarado|elota|la\s+cruz\s+de\s+elota|san\s+ignacio|badiraguato|angostura|mocorito|sinaloa\s+de\s+leyva)\b",
    # Otras ciudades de México (precisión para no chocar con nombres de próceres en calles como Juárez o Hidalgo)
    r"\b(?:guadalajara|zapopan|tlaquepaque|tonal[aá]|monterrey|san\s+pedro|apodaca|guadalupe\s+nl|cdmx|ciudad\s+de\s+m[eé]xico|distrito\s+federal|df|edomex|estado\s+de\s+m[eé]xico|tijuana|mexicali|hermosillo|cd\.?\s*obreg[oó]n|ciudad\s+obreg[oó]n|nogales|cd\.?\s*durango|ciudad\s+durango|g[oó]mez\s+palacio|tepic|bah[ií]a\s+de\s+banderas|le[oó]n\s+gto|ciudad\s+le[oó]n|guanajuato\s+capital|puebla|quer[eé]taro|canc[uú]n|m[eé]rida|veracruz|xalapa|oaxaca|cd\.?\s*chihuahua|ciudad\s+chihuahua|cd\.?\s*ju[aá]rez|ciudad\s+ju[aá]rez|saltillo|torre[oó]n|aguascalientes|san\s+luis\s+potos[ií]|morelia|colima|manzanillo|cuernavaca|toluca|pachuca|villahermosa|campeche|chetumal|tuxtla|chilpancingo|acapulco)\b",
    # Otros estados cuando se especifican como ubicación/jurisdicción (no como 'Calle Jalisco')
    r"(?:,\s*(?:jalisco|nuevo\s+le[oó]n|nayarit|sonora|coahuila|zacatecas|michoac[aá]n|baja\s+california|durango|chihuahua)\b|\bestado\s+de\s+(?:jalisco|nuevo\s+le[oó]n|nayarit|sonora|coahuila|zacatecas|michoac[aá]n|baja\s+california|durango|chihuahua)\b|\ben\s+(?:jalisco|nuevo\s+le[oó]n|nayarit|sonora|coahuila|zacatecas|michoac[aá]n|baja\s+california|durango|chihuahua)\b|(?:jalisco|nuevo\s+le[oó]n|nayarit|sonora|coahuila|zacatecas|michoac[aá]n|baja\s+california|durango|chihuahua)$)",
    # Otros países
    r"\b(?:estados\s+unidos|eeuu|usa|united\s+states|texas|california|arizona|espa[ñn]a|colombia|argentina|venezuela|chile|per[uú])\b",
]

# Ciudades, municipios, estados y países fuera de cobertura para Culiacán (Gascytsa)
OUT_LOCATIONS_CULIACAN = [
    # Colonias, fraccionamientos y avenidas de Mazatlán que deben rechazarse categóricamente en Culiacán
    r"\b(?:zona\s+dorada|marina\s+mazatl[aá]n|s[aá]balo\s+country|las\s+misiones|misi[oó]n\s+san\s+javier|misi[oó]n\s+santo\s+tom[aá]s|misi[oó]n\s+loreto|real\s+del\s+valle|pradera\s+dorada|el\s+conchi|flores\s+mag[oó]n|palos\s+prietos|ferrocarrilera|lomas\s+del\s+mar|playa\s+sur|jacarandas|villa\s+verde|valles\s+del\s+ejido|urbi\s+villa\s+del\s+real|santa\s+teresa|alarc[oó]n|infonavit\s+playas|cerro\s+del\s+vig[ií]a|montuosa|jaripillo|francisco\s+villa|l[oó]pez\s+mateos|sirena|urias|cerritos|el\s+venadillo|av\.?\s+del\s+mar|av\.?\s+camar[oó]n\s+s[aá]balo|camar[oó]n\s+s[aá]balo|av\.?\s+rafael\s+buelna|rafael\s+buelna|ej[eé]rcito\s+mexicano|paseo\s+claussen|olas\s+altas)\b",
    # Otros municipios de Sinaloa (incluyendo Mazatlán)
    r"\b(?:mazatl[aá]n|maza|navolato|los\s+mochis|mochis|guasave|escuinapa|concordia|el\s+rosario|el\s+fuerte|choix|guam[uú]chil|salvador\s+alvarado|elota|la\s+cruz\s+de\s+elota|san\s+ignacio|badiraguato|angostura|mocorito|sinaloa\s+de\s+leyva)\b",
    # Otras ciudades de México
    r"\b(?:guadalajara|zapopan|tlaquepaque|tonal[aá]|monterrey|san\s+pedro|apodaca|guadalupe\s+nl|cdmx|ciudad\s+de\s+m[eé]xico|distrito\s+federal|df|edomex|estado\s+de\s+m[eé]xico|tijuana|mexicali|hermosillo|cd\.?\s*obreg[oó]n|ciudad\s+obreg[oó]n|nogales|cd\.?\s*durango|ciudad\s+durango|g[oó]mez\s+palacio|tepic|bah[ií]a\s+de\s+banderas|le[oó]n\s+gto|ciudad\s+le[oó]n|guanajuato\s+capital|puebla|quer[eé]taro|canc[uú]n|m[eé]rida|veracruz|xalapa|oaxaca|cd\.?\s*chihuahua|ciudad\s+chihuahua|cd\.?\s*ju[aá]rez|ciudad\s+ju[aá]rez|saltillo|torre[oó]n|aguascalientes|san\s+luis\s+potos[ií]|morelia|colima|manzanillo|cuernavaca|toluca|pachuca|villahermosa|campeche|chetumal|tuxtla|chilpancingo|acapulco)\b",
    # Otros estados cuando se especifican como ubicación/jurisdicción
    r"(?:,\s*(?:jalisco|nuevo\s+le[oó]n|nayarit|sonora|coahuila|zacatecas|michoac[aá]n|baja\s+california|durango|chihuahua)\b|\bestado\s+de\s+(?:jalisco|nuevo\s+le[oó]n|nayarit|sonora|coahuila|zacatecas|michoac[aá]n|baja\s+california|durango|chihuahua)\b|\ben\s+(?:jalisco|nuevo\s+le[oó]n|nayarit|sonora|coahuila|zacatecas|michoac[aá]n|baja\s+california|durango|chihuahua)\b|(?:jalisco|nuevo\s+le[oó]n|nayarit|sonora|coahuila|zacatecas|michoac[aá]n|baja\s+california|durango|chihuahua)$)",
    # Otros países
    r"\b(?:estados\s+unidos|eeuu|usa|united\s+states|texas|california|arizona|espa[ñn]a|colombia|argentina|venezuela|chile|per[uú])\b",
]


def _fast_heuristic_check(
    text: str,
    is_culiacan_only: bool = False,
    target_city: str | None = None,
) -> tuple[bool, str] | None:
    """Evaluación rápida por heurísticas para descartar bromas obvias y ciudades fuera de cobertura en 0ms."""
    t_clean = text.lower().strip()

    if len(t_clean) < 6:
        return False, "La dirección es demasiado corta para ser un domicilio real. Por favor escribe calle, número y colonia."

    for pat in OBVIOUS_JOKE_PATTERNS:
        if re.search(pat, t_clean, re.IGNORECASE):
            return False, "La dirección ingresada no parece ser un domicilio válido o existente. Por favor proporciona una dirección real (calle, número y colonia) o comparte tu ubicación GPS 📍."

    is_culiacan = is_culiacan_only or (target_city and "culiac" in target_city.lower())

    if is_culiacan:
        for pat in OUT_LOCATIONS_CULIACAN:
            if re.search(pat, t_clean, re.IGNORECASE):
                return False, "⚠️ Por el momento nuestro servicio de Gas a tu Puerta Gascytsa tiene cobertura exclusivamente en la ciudad de Culiacán, Sinaloa. Por favor proporciona una dirección o ubicación dentro de Culiacán 📍."
    else:
        # Modo Mazatlán (Petroil / bots originales de Gas a tu Puerta)
        for pat in OUT_LOCATIONS_MAZATLAN:
            if re.search(pat, t_clean, re.IGNORECASE):
                return False, "⚠️ Por el momento nuestro servicio de Gas a tu Puerta tiene cobertura exclusivamente en la ciudad de Mazatlán, Sinaloa. Por favor proporciona una dirección o ubicación dentro de Mazatlán 📍."

    return None


async def validate_address_with_llm(
    address_text: str,
    tenant_id: str = "petroil",
    city_context: str | None = None,
) -> AddressValidationResult:
    """Analiza semánticamente si una dirección es real, plausible y entregable en la ciudad objetivo."""
    raw = (address_text or "").strip()
    is_culiacan_mode = (tenant_id == "gascytsa") or ("culiac" in (city_context or "").lower())
    target_city_name = "Culiacán" if is_culiacan_mode else "Mazatlán"
    service_name = "Gas a tu Puerta Gascytsa" if is_culiacan_mode else "Gas a tu Puerta"

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

    # 1. Filtro rápido heurístico (0ms)
    fast_check = _fast_heuristic_check(raw, is_culiacan_only=is_culiacan_mode, target_city=target_city_name)
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
            reason="Rechazado por heurística de cobertura o broma/incompletitud",
            user_feedback=fb,
        )

    # 2. Obtención de evidencia física y satelital (Grounding en Cartografía)
    ground_ok, ground_fb, ground_data = verify_address_city_grounding(raw, target_city=target_city_name)

    # Si la cartografía determinó categóricamente que está físicamente fuera de cobertura (otra ciudad o > 35km):
    if ground_ok is False:
        clean_norm = ground_data.get("match_addr") or raw
        return AddressValidationResult(
            is_valid=False,
            is_joke_or_fake=False,
            confidence=0.95,
            normalized_address=clean_norm,
            street="",
            number="",
            colonia="",
            references="",
            reason="Dirección físicamente fuera de cobertura de la ciudad objetivo",
            user_feedback=ground_fb,
        )

    # 3. Análisis semántico y delimitación estricta con IA (LLM)
    if is_culiacan_mode:
        system_prompt = (
            "Eres un auditor y validador de inteligencia artificial estricto para Gas a tu Puerta Gascytsa con cobertura EXCLUSIVA en CULIACÁN, SINALOA.\n"
            "Tu misión crítica es validar si la dirección o ubicación que se te comparte PERTENECE A CULIACÁN, SINALOA, "
            "o si pertenece a OTRA CIUDAD (Mazatlán, Navolato, Los Mochis, Guasave, etc.), a otro estado o país, o si es una dirección inventada o falsa.\n\n"
            "ZONAS Y COLONIAS REALES DE CULIACÁN (VÁLIDAS PARA ESTE BOT):\n"
            "- Las Quintas, Desarrollo Urbano Tres Ríos, Infonavit Humaya, Valle Alto, Centro, Bugambilias, Los Ángeles, Barrancos, Gabriel Leyva, Guadalupe, Montebello, Villa Universidad, Stanza Toscana, Nakayama, Bachigualato, San Rafael, Santa Fe, Chula Vista, La Conquista, Cedros, Alturas del Sur, etc.\n"
            "- Avenidas y Vialidades: Blvd. Pedro Infante, Av. Álvaro Obregón, Blvd. Enrique Sánchez Alonso, Blvd. Emiliano Zapata, Blvd. Francisco I. Madero, Calzada Heroico Colegio Militar, Blvd. Lola Beltrán, Blvd. Rolando Arjona, etc.\n\n"
            "ZONAS DE OTRAS CIUDADES COMO MAZATLÁN (DEBES RECHAZAR CATEGÓRICAMENTE EN ESTE BOT DE CULIACÁN):\n"
            "- Fracc. Las Misiones (ej. Misión San Javier, Misión Santo Tomás, Misión Loreto), Marina Mazatlán, Sábalo Country, Zona Dorada, Gaviotas, Real del Valle, Pradera Dorada, El Conchi, Flores Magón, Palos Prietos, Cerro del Vigía, Playa Sur, Jacarandas, Villa Verde, Santa Teresa, Alarcón, Infonavit Playas, El Venadillo, Cerritos, Av. Camarón Sábalo, Av. del Mar, Paseo Claussen, etc.\n"
            "- REGLA: Si la dirección o ubicación compartida pertenece a Mazatlán o a cualquier otra ciudad, debes clasificarla con is_valid=false.\n"
            "- REGLA VITAL DE MENSAJE: En user_feedback NUNCA intentes adivinar ni menciones en qué otra ciudad o lugar se encuentra esa dirección. Solo indica amablemente que el servicio tiene cobertura exclusivamente en Culiacán, Sinaloa, y solicita una dirección o ubicación dentro de Culiacán 📍.\n\n"
            "CRITERIOS DE VALIDACIÓN:\n"
            "- VÁLIDA (is_valid=true, is_joke_or_fake=false): Pertenece a Culiacán y contiene datos para ubicar el lugar (calle, número o entrecalles, colonia/sector de Culiacán).\n"
            "- OTRA CIUDAD / FUERA DE COBERTURA (is_valid=false, is_joke_or_fake=false): Pertenece a Mazatlán, Navolato, Mochis, u otro municipio/estado/país. user_feedback='⚠️ Por el momento nuestro servicio de Gas a tu Puerta Gascytsa tiene cobertura exclusivamente en la ciudad de Culiacán, Sinaloa. Por favor proporciona una dirección o ubicación dentro de Culiacán 📍.'\n"
            "- FALSA / INVENTADA / BROMA (is_valid=false, is_joke_or_fake=true): Calles o colonias inexistentes o absurdas (ej. 'calle dragón', 'narnia', 'en mi casa'). user_feedback='⚠️ La dirección ingresada no parece ser un domicilio válido o existente en Culiacán. Por favor escribe tu calle, número y colonia real, o comparte tu ubicación GPS 📍.'\n"
            "- INCOMPLETA (is_valid=false, is_joke_or_fake=false): Solo una palabra suelta sin datos suficientes.\n\n"
            "DEBES RESPONDER EXCLUSIVAMENTE CON UN OBJETO JSON VÁLIDO CON ESTE ESQUEMA EXACTO:\n"
            "{\n"
            '  "is_valid": true,\n'
            '  "is_joke_or_fake": false,\n'
            '  "confidence": 0.95,\n'
            '  "street": "Blvd. Pedro Infante",\n'
            '  "number": "2200",\n'
            '  "colonia": "Desarrollo Urbano Tres Ríos",\n'
            '  "references": "Cerca de la plaza",\n'
            '  "normalized_address": "Blvd. Pedro Infante 2200, Desarrollo Urbano Tres Ríos, Culiacán",\n'
            '  "reason": "Explicación breve de la validación",\n'
            '  "user_feedback": "Mensaje cordial para el cliente si fue rechazada o validada"\n'
            "}"
        )
    else:
        system_prompt = (
            "Eres un auditor y validador de inteligencia artificial estricto para Gas a tu Puerta con cobertura EXCLUSIVA en MAZATLÁN, SINALOA.\n"
            "Tu misión crítica es validar si la dirección o ubicación que se te comparte PERTENECE A MAZATLÁN, SINALOA, "
            "o si pertenece a OTRA CIUDAD (Culiacán, Los Mochis, Navolato, Escuinapa, El Rosario, Concordia, etc.), a otro estado o país, o si es una dirección inventada o falsa.\n\n"
            "ZONAS Y COLONIAS REALES DE MAZATLÁN (VÁLIDAS PARA ESTE BOT):\n"
            "- Centro, Zona Dorada, Sábalo Country, Marina Mazatlán, Fracc. Las Misiones, Real del Valle, Pradera Dorada, Benito Juárez, El Conchi, Flores Magón, Palos Prietos, Ferrocarrilera, Lomas del Mar, Playa Sur, Jacarandas, Villa Verde, Valles del Ejido, Urbi Villa del Real, Santa Teresa, Alarcón, Infonavit Playas, Cerro del Vigía, Montuosa, Jaripillo, Francisco Villa, López Mateos, Sirena, Urias, Cerritos, El Venadillo, Lomas de Mazatlán, etc.\n"
            "- Avenidas y Calles Principales: Av. del Mar, Av. Camarón Sábalo, Av. Rafael Buelna, Av. Ejército Mexicano, Av. Gabriel Leyva (Mazatlán), Av. Insurgentes, Blvd. Niños Héroes, Av. Manuel J. Clouthier, Av. Bicentenario Juárez, Av. Cruz Lizárraga, Paseo Claussen, etc.\n\n"
            "ZONAS DE OTRAS CIUDADES COMO CULIACÁN (DEBES RECHAZAR CATEGÓRICAMENTE EN ESTE BOT DE MAZATLÁN):\n"
            "- Desarrollo Urbano Tres Ríos, Las Quintas, Quintas, Infonavit Humaya, Humaya, Valle Alto, Barrancos, Bugambilias, Los Ángeles, Gabriel Leyva (Culiacán), Guadalupe (Culiacán), Montebello, Villa Universidad, Stanza Toscana, Stanza Florencia, Stanza, Nakayama, Bachigualato, San Rafael, Santa Fe, Chula Vista (Culiacán), La Conquista, Cedros, Alturas del Sur, Blvd. Pedro Infante, Av. Álvaro Obregón (Culiacán), Blvd. Enrique Sánchez Alonso, Blvd. Emiliano Zapata, Blvd. Francisco I. Madero, Calzada Aeropuerto, El Palmito, Palmito, Culiacancito, Portalegre, Tierra Blanca, Chapultepec (Culiacán), Ciudades Hermanas, Los Pinos (Culiacán), etc.\n"
            "- REGLA: Si la dirección o ubicación compartida pertenece a Culiacán o a cualquier otra ciudad, debes clasificarla con is_valid=false.\n"
            "- REGLA VITAL DE MENSAJE: En user_feedback NUNCA intentes adivinar ni menciones en qué otra ciudad o lugar se encuentra esa dirección. Solo indica amablemente que el servicio tiene cobertura exclusivamente en Mazatlán, Sinaloa, y solicita una dirección o ubicación dentro de Mazatlán 📍.\n\n"
            "CRITERIOS DE VALIDACIÓN:\n"
            "- VÁLIDA (is_valid=true, is_joke_or_fake=false): Pertenece a Mazatlán y contiene datos para ubicar el lugar (calle, número o entrecalles, colonia/sector de Mazatlán).\n"
            "- OTRA CIUDAD / FUERA DE COBERTURA (is_valid=false, is_joke_or_fake=false): Pertenece a Culiacán, Mochis, Escuinapa, u otro municipio/estado/país. user_feedback='⚠️ Por el momento nuestro servicio de Gas a tu Puerta tiene cobertura exclusivamente en la ciudad de Mazatlán, Sinaloa. Por favor proporciona una dirección o ubicación dentro de Mazatlán 📍.'\n"
            "- FALSA / INVENTADA / BROMA (is_valid=false, is_joke_or_fake=true): Calles o colonias inexistentes o absurdas (ej. 'calle dragón', 'narnia', 'en mi casa'). user_feedback='⚠️ La dirección ingresada no parece ser un domicilio válido o existente en Mazatlán. Por favor escribe tu calle, número exterior y colonia real, o comparte tu ubicación GPS 📍.'\n"
            "- INCOMPLETA (is_valid=false, is_joke_or_fake=false): Solo una palabra suelta sin datos suficientes.\n\n"
            "DEBES RESPONDER EXCLUSIVAMENTE CON UN OBJETO JSON VÁLIDO CON ESTE ESQUEMA EXACTO:\n"
            "{\n"
            '  "is_valid": true,\n'
            '  "is_joke_or_fake": false,\n'
            '  "confidence": 0.95,\n'
            '  "street": "Misión San Javier",\n'
            '  "number": "5246",\n'
            '  "colonia": "Las Misiones",\n'
            '  "references": "Portón blanco",\n'
            '  "normalized_address": "Misión San Javier 5246, Fracc. Las Misiones, Mazatlán",\n'
            '  "reason": "Explicación breve de la validación",\n'
            '  "user_feedback": "Mensaje cordial para el cliente si fue rechazada o validada"\n'
            "}"
        )

    # Construir prompt para la IA con evidencia cartográfica
    alt_name = "Mazatlán" if is_culiacan_mode else "Culiacán"
    if ground_ok is True:
        match_str = ground_data.get("match_addr") or raw
        user_prompt = (
            f"Dirección o ubicación recibida del usuario para entrega en {target_city_name}, Sinaloa:\n\"{raw}\"\n\n"
            f"[INFORMACIÓN CARTOGRÁFICA PREVIA]: Se detectó una coincidencia tentativa en mapas: '{match_str}'.\n\n"
            f"Tu tarea como IA validadora:\n"
            f"Evalúa con tu conocimiento si el texto original del usuario (\"{raw}\") pertenece legítimamente a {target_city_name}, Sinaloa.\n"
            f"Si la dirección o zona pertenece en realidad a {alt_name} (o a otra ciudad) y fue confundida por similitud de nombres, DEBES CLASIFICARLA CON is_valid=false.\n"
            f"Solo si estás seguro de que es una dirección dentro de {target_city_name}, clasifícala con is_valid=true.\n"
            f"Si es rechazada por ser de otra ciudad, en user_feedback pon exclusivamente: '⚠️ Por el momento nuestro servicio de {service_name} tiene cobertura exclusivamente en la ciudad de {target_city_name}, Sinaloa. Por favor proporciona una dirección o ubicación dentro de {target_city_name} 📍.'"
        )
    else:
        user_prompt = (
            f"Dirección o ubicación recibida del usuario para entrega en {target_city_name}, Sinaloa:\n\"{raw}\"\n\n"
            f"[AUDITORÍA SEMÁNTICA CON IA]: Analiza si esta calle, colonia o zona pertenece a {target_city_name}, Sinaloa.\n"
            f"Si pertenece a {alt_name} o a otra ciudad/estado/país, o si es una dirección inventada o falsa, clasifícala con is_valid=false.\n"
            f"En user_feedback si no pertenece a {target_city_name}, solo indica que el servicio tiene cobertura exclusivamente en {target_city_name}, Sinaloa, sin mencionar en qué otra ciudad está."
        )

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

            if ground_ok is True and is_valid:
                conf = max(conf, 0.98)
                if not norm or norm == raw:
                    norm = ground_data.get("match_addr") or raw

            combined_text = (norm + " " + raw).lower()

            # Post-validación estricta de ciudades / estados fuera de cobertura
            if is_culiacan_mode and is_valid:
                for pat in OUT_LOCATIONS_CULIACAN:
                    if re.search(pat, combined_text, re.IGNORECASE):
                        is_valid = False
                        is_joke = False
                        reason = "Fuera de cobertura (solo Culiacán)"
                        fb = "⚠️ Por el momento nuestro servicio de Gas a tu Puerta Gascytsa tiene cobertura exclusivamente en la ciudad de Culiacán, Sinaloa. Por favor proporciona una dirección o ubicación dentro de Culiacán 📍."
                        break
            elif not is_culiacan_mode and is_valid:
                for pat in OUT_LOCATIONS_MAZATLAN:
                    if re.search(pat, combined_text, re.IGNORECASE):
                        is_valid = False
                        is_joke = False
                        reason = "Fuera de cobertura (solo Mazatlán)"
                        fb = "⚠️ Por el momento nuestro servicio de Gas a tu Puerta tiene cobertura exclusivamente en la ciudad de Mazatlán, Sinaloa. Por favor proporciona una dirección o ubicación dentro de Mazatlán 📍."
                        break

            # Asegurar que el mensaje al usuario NUNCA mencione o intente adivinar otra ciudad
            if not is_valid:
                alt_city = "Mazatlán" if is_culiacan_mode else "Culiacán"
                service_title = "Gas a tu Puerta Gascytsa" if is_culiacan_mode else "Gas a tu Puerta"
                if alt_city.lower() in fb.lower() or "otra ciudad" in fb.lower() or "corresponde a" in fb.lower() or "parece pertenecer" in fb.lower() or "ubicada en" in fb.lower():
                    fb = f"⚠️ Por el momento nuestro servicio de {service_title} tiene cobertura exclusivamente en la ciudad de {target_city_name}, Sinaloa. Por favor proporciona una dirección o ubicación dentro de {target_city_name} 📍."

            if not fb:
                if not is_valid:
                    fb = f"Por favor indícanos tu **calle, número exterior y colonia** de {target_city_name} (o referencias de tu domicilio) para poder realizar tu entrega correctamente 📍."
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

    # Fallback si el LLM no respondió:
    if ground_ok is True:
        return AddressValidationResult(
            is_valid=True,
            is_joke_or_fake=False,
            confidence=0.98,
            normalized_address=ground_data.get("match_addr") or raw,
            street="",
            number="",
            colonia="",
            references="",
            reason=f"Dirección confirmada físicamente en {target_city_name}",
            user_feedback="Dirección verificada con éxito.",
        )

    has_digits = bool(re.search(r"\d+", raw))
    has_words = len(raw.split()) >= 3
    is_plausible = has_digits and has_words

    city_for_msg = "Culiacán" if is_culiacan_mode else "Mazatlán"
    service_for_msg = "Gas a tu Puerta Gascytsa" if is_culiacan_mode else "Gas a tu Puerta"
    fb_fallback = "Dirección aceptada." if is_plausible else f"Por favor escribe tu calle, número y colonia completa en {city_for_msg}."

    if is_plausible:
        check_list = OUT_LOCATIONS_CULIACAN if is_culiacan_mode else OUT_LOCATIONS_MAZATLAN
        for pat in check_list:
            if re.search(pat, raw.lower(), re.IGNORECASE):
                is_plausible = False
                fb_fallback = f"⚠️ Por el momento nuestro servicio de {service_for_msg} tiene cobertura exclusivamente en la ciudad de {city_for_msg}, Sinaloa. Por favor proporciona una dirección dentro de {city_for_msg} o comparte tu ubicación GPS 📍."
                break

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
        user_feedback=fb_fallback if not is_plausible else "",
    )
