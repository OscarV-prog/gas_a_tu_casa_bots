"""Audio and voice note transcription service.

Transcribes incoming audio/voice messages from Telegram and WhatsApp into text
so they can flow seamlessly through the deterministic conversational router.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


async def transcribe_audio_file(
    file_path: str | Path,
    language: str = "es",
    api_key: str | None = None,
) -> str:
    """Transcribe an audio file (ogg, mp3, m4a, wav) to text.
    
    Uses Whisper transcription API via OpenAI or OpenRouter.
    """
    path = Path(file_path)
    if not path.exists():
        logger.error(f"Archivo de audio no encontrado: {path}")
        return ""

    token = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY")
    if not token:
        logger.warning("No hay API Key configurada para transcripción de audio.")
        return ""

    # Determine endpoint
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        endpoint = "https://api.openai.com/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {openai_key}"}
        model = "whisper-1"
    else:
        # Fallback to OpenRouter or compatible OpenAI endpoint
        endpoint = "https://openrouter.ai/api/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {token}"}
        model = "openai/whisper-large-v3"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            with open(path, "rb") as audio_f:
                files = {"file": (path.name, audio_f, "audio/ogg")}
                data = {"model": model, "language": language}
                response = await client.post(endpoint, headers=headers, files=files, data=data)

            if response.status_code == 200:
                result = response.json()
                transcription = result.get("text", "").strip()
                logger.info(f"Transcripción exitosa de audio ({path.name}): {transcription}")
                return transcription
            else:
                logger.warning(
                    f"Fallo en transcripción de audio ({response.status_code}): {response.text}"
                )
                return ""
    except Exception as e:
        logger.error(f"Error al transcribir audio: {e}")
        return ""
