"""Security Guard & Prompt Injection Defense Module.

Protects the chatbot against:
1. Prompt Injection & Jailbreaks (e.g., 'ignore previous instructions', 'act as DAN', 'developer mode')
2. System Prompt & Credential Extraction (e.g., 'show system prompt', 'database password', 'API keys')
3. Arbitrary Code / SQL Injections / Malicious payloads
4. Completely out-of-scope non-business inquiries (e.g., recipes, poems, jokes, homework, unrelated trivia)
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Patrones de Prompt Injection / Jailbreaks / Extracción del Sistema
PROMPT_INJECTION_PATTERNS = [
    # 1. Ignorar instrucciones previas / Bypass de reglas
    r"(?i)\b(?:ignore|ignora|olvida|desactiva|anula|saltate|salta)\s+(?:all|todas|tus|las|every|previous|anteriores|previas)?\s*(?:instructions|instrucciones|reglas|rules|directrices|comandos|filtros|prompts|limits)\b",
    r"(?i)\b(?:forget|disregard|override|bypass)\s+(?:all|previous|system|safety|security)\s+(?:instructions|rules|prompts|guidelines)\b",
    
    # 2. Extracción de System Prompt / Instrucciones secretas
    r"(?i)\b(?:dime|mu[eé]strame|ense[ñn]ame|revela|escribe|cu[aá]l\s+es|show|tell|reveal|repeat|print|output)\s+(?:tu|el|your)?\s*(?:system\s*prompt|prompt\s*del\s*sistema|instrucciones\s*(?:iniciales|secretas|internas|del\s*sistema)|hidden\s*prompt|initial\s*instructions)\b",
    r"(?i)\b(?:system\s*prompt|prompt\s*inicial|instrucciones\s*del\s*sistema|developer\s*prompt)\b",
    r"(?i)\b(?:repeat\s+the\s+words\s+above|repite\s+el\s+texto\s+anterior|repite\s+las\s+instrucciones)\b",
    
    # 3. Credenciales, Llaves, Base de Datos, Variables de Entorno
    r"(?i)\b(?:api[ _-]?key|apikey|token|secret[ _-]?key|database\s*password|contrase[ñn]a\s*de\s*(?:la\s*bd|base\s*de\s*datos)|postgres_password|db_pass|openrouter_api_key|telegram_bot_token)\b",
    r"(?i)\b(?:os\.environ|process\.env|dotenv|cat\s+\.env|\.env\s*file|dump\s*database|information_schema|pg_shadow|pg_user)\b",
    
    # 4. Jailbreak Personas & Modos
    r"(?i)\b(?:dan\s*mode|do\s*anything\s*now|jailbreak|developer\s*mode|modo\s*desarrollador|modo\s*dios|god\s*mode|unfiltered\s*mode|evil\s*bot|anti-gpt)\b",
    r"(?i)\b(?:eres\s+dan|eres\s+un\s+hacker|eres\s+libre|act[uú]a\s+como|pretend\s+(?:to\s+be|you\s+are)|simula\s+ser|comportate\s+como)\b",
    r"(?i)\b(?:sin\s+restricciones|sin\s+l[ií]mites|unrestricted\s+mode|sin\s+censura|hacer\s+cualquier\s+cosa)\b",
    
    # 5. Inyección SQL o Comandos de Sistema
    r"(?i)\b(?:drop\s+table|truncate\s+table|delete\s+from\s+users|union\s+select|select\s+\*\s+from\s+users|--\s*exec|xp_cmdshell|bash\s+-c|curl\s+http|wget\s+http)\b",
]

# Patrones de consultas totalmente ajenas al negocio de gas LP (recetas, poemas, chistes, etc.)
OUT_OF_SCOPE_PATTERNS = [
    # Tareas escolares / programación / código
    r"(?i)\b(?:hazme\s+un\s+c[oó]digo|escribe\s+un\s+script|programa\s+en\s+python|resuelve\s+esta\s+ecuaci[oó]n|hazme\s+la\s+tarea|escribe\s+un\s+ensayo\s+sobre)\b",
    # Poemas, chistes, canciones, cuentos
    r"(?i)\b(?:cu[eé]ntame\s+un\s+chiste|escribe\s+un\s+poema|canta\s+una\s+canci[oó]n|cu[eé]ntame\s+un\s+cuento|dime\s+un\s+refr[aá]n|adivinanza)\b",
    # Recetas de cocina ajenas
    r"(?i)\b(?:receta\s+de\s+(?:pastel|pizza|tacos|comida|galletas|cocina)|c[oó]mo\s+se\s+prepara\s+el\s+pastel)\b",
    # Filosofía / Preguntas existenciales
    r"(?i)\b(?:cu[aá]l\s+es\s+el\s+sentido\s+de\s+la\s+vida|crees\s+en\s+dios|qui[eé]n\s+ganar[aá]\s+el\s+mundial|pol[ií]tica\s+de\s+m[eé]xico)\b",
]

# Palabras clave relacionadas con el negocio legítimo de gas para evitar falsos positivos
GAS_BUSINESS_KEYWORDS = [
    "gas", "cilindro", "cilindros", "tanque", "tanques", "estacionario", "litro", "litros",
    "kilo", "kilos", "kg", "pedido", "pedidos", "repartidor", "entrega", "camion", "camión",
    "precio", "precios", "cuanto", "cuánto", "cuesta", "costo", "costos", "pago", "efectivo",
    "tarjeta", "terminal", "transferencia", "dirección", "direccion", "calle", "colonia",
    "horario", "horarios", "abren", "cierran", "cobertura", "zona", "fuga", "fugas",
    "olor", "urgente", "petroil", "gas a tu puerta", "mazatlán", "mazatlan", "estatus",
    "cancelar", "cancela", "donde viene", "dónde viene", "mi pedido", "mi orden", "folio"
]


@dataclass
class SecurityCheckResult:
    is_safe: bool
    reason: str  # "safe" | "prompt_injection" | "out_of_scope"
    response_text: str | None = None


class SecurityGuard:
    """Validador de seguridad de peticiones entrantes."""

    @staticmethod
    def inspect(text: str) -> SecurityCheckResult:
        """Analiza un texto para detectar ataques o preguntas fuera de lugar."""
        if not text:
            return SecurityCheckResult(is_safe=True, reason="safe")

        t = text.strip()
        t_lower = t.lower()

        # 1. Chequeo de Prompt Injection / Jailbreaks / Extracción
        for pattern in PROMPT_INJECTION_PATTERNS:
            if re.search(pattern, t):
                logger.warning(f"[SecurityGuard] 🚨 Prompt injection / extracción detectada: {t[:80]}")
                return SecurityCheckResult(
                    is_safe=False,
                    reason="prompt_injection",
                    response_text=SecurityGuard.get_confidential_refusal_message(),
                )

        # 2. Chequeo de temas flagrantemente fuera de alcance (poemas, recetas, código ajeno)
        # Solo si no contiene términos legítimos de compra de gas
        is_gas_related = any(re.search(r"\b" + re.escape(k) + r"\b", t_lower) for k in GAS_BUSINESS_KEYWORDS)
        if not is_gas_related:
            for pattern in OUT_OF_SCOPE_PATTERNS:
                if re.search(pattern, t):
                    logger.info(f"[SecurityGuard] ℹ️ Consulta fuera de alcance detectada: {t[:80]}")
                    return SecurityCheckResult(
                        is_safe=False,
                        reason="out_of_scope",
                        response_text=SecurityGuard.get_out_of_scope_message(),
                    )

        return SecurityCheckResult(is_safe=True, reason="safe")


    @staticmethod
    def get_confidential_refusal_message() -> str:
        """Mensaje estándar de rechazo por seguridad y confidencialidad."""
        return (
            "🔒 **Aviso del Sistema:**\n"
            "Lo siento, esa información es confidencial del sistema y no tengo autorización para compartirla ni ejecutar comandos de ese tipo.\n\n"
            "Mi función como asistente de **Gas a Tu Puerta - Petroil** es exclusivamente de atención al cliente:\n"
            "• 🟢 **Tomar tu pedido de Gas LP** (cilindro o estacionario)\n"
            "• 🔵 **Consultar el estatus** de tu entrega\n"
            "• ❌ **Cancelar** un pedido previo"
        )

    @staticmethod
    def get_out_of_scope_message() -> str:
        """Mensaje estándar para preguntas fuera del alcance del servicio."""
        return (
            "🤖 **Atención al Cliente Petroil:**\n"
            "Disculpa, no puedo responder a esa solicitud ya que soy un asistente virtual diseñado **exclusivamente** para la venta y atención de pedidos de Gas LP en **Gas a Tu Puerta - Petroil**."
        )
