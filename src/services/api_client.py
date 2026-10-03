"""HTTP REST API Client for centralized NestJS + PostgreSQL backend."""

from __future__ import annotations

import os
import logging
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Configurar sesión HTTP persistente con pool y reintentos automáticos
_session = requests.Session()
_retry_strategy = Retry(
    total=2,
    backoff_factor=0.5,
    status_forcelist=[502, 503, 504],
    allowed_methods=["HEAD", "GET", "OPTIONS"]
)
_adapter = HTTPAdapter(max_retries=_retry_strategy, pool_connections=10, pool_maxsize=20)
_session.mount("http://", _adapter)
_session.mount("https://", _adapter)


_cached_token: str | None = None
_token_timestamp: float = 0


def get_api_base_url() -> str:
    """Get configured API base URL without trailing slash."""
    return os.getenv("API_BASE_URL", "https://petrogas-api.petroil.dev/api").rstrip("/")


def _authenticate_and_get_token() -> str | None:
    """Authenticate with /auth/login using configured credentials and return JWT token."""
    global _cached_token, _token_timestamp
    
    # Check if manual token is provided in .env
    manual_token = os.getenv("API_TOKEN") or os.getenv("AUTH_TOKEN") or os.getenv("API_KEY")
    if manual_token and manual_token.strip():
        return manual_token.strip()

    # Reuse cached token if valid (cache for 1 hour)
    if _cached_token and (time.time() - _token_timestamp) < 3600:
        return _cached_token

    email = os.getenv("API_EMAIL") or os.getenv("OPERATOR_EMAIL") or os.getenv("API_USER")
    password = os.getenv("API_PASSWORD") or os.getenv("OPERATOR_PASSWORD") or os.getenv("API_PASS")

    if not email or not password:
        return None

    try:
        url = f"{get_api_base_url()}/auth/login"
        payload = {"email": email.strip(), "password": password.strip()}
        headers = {
            "Content-Type": "application/json",
            "x-tenant-id": os.getenv("TENANT_ID", "petroil"),
        }
        resp = _session.post(url, json=payload, headers=headers, timeout=5)
        if resp.status_code in (200, 201):
            data = resp.json()
            token = data.get("access_token") or data.get("token") or data.get("jwt") or data.get("accessToken")
            if token:
                _cached_token = str(token).strip()
                _token_timestamp = time.time()
                logger.info("[API_CLIENT] Authenticated successfully with remote PostgreSQL API.")
                return _cached_token
        logger.warning(f"[API_CLIENT] Auto-login failed ({resp.status_code}): {resp.text}")
    except Exception as e:
        logger.warning(f"[API_CLIENT] Error during auto-login to remote API: {e}")

    return None


def get_headers() -> dict[str, str]:
    """Get standard headers including multi-tenant header and authorization token."""
    headers = {
        "Content-Type": "application/json",
        "x-tenant-id": os.getenv("TENANT_ID", "petroil"),
        "Bypass-Tunnel-Reminder": "true",
    }
    token = _authenticate_and_get_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _sanitize_log_data(data: Any) -> Any:
    """Redacta campos sensibles de logs para protección de PII y credenciales."""
    if not isinstance(data, dict):
        return data
    sanitized = {}
    sensitive_keys = {"password", "token", "secret", "api_key", "key", "authorization"}
    for k, v in data.items():
        if any(s in k.lower() for s in sensitive_keys):
            sanitized[k] = "***REDACTED***"
        elif isinstance(v, dict):
            sanitized[k] = _sanitize_log_data(v)
        else:
            sanitized[k] = v
    return sanitized


def api_get(endpoint: str, params: dict | None = None, timeout: int = 8) -> dict | list | None:
    """Make a GET request to the centralized NestJS API and return parsed JSON."""
    url = f"{get_api_base_url()}{endpoint if endpoint.startswith('/') else '/' + endpoint}"
    headers = get_headers()
    try:
        response = _session.get(url, headers=headers, params=params, timeout=timeout)
        response.raise_for_status()
        if not response.text or not response.text.strip():
            return None
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.warning(f"[API_CLIENT] Error en GET {url}: {e}")
        raise


def api_post(endpoint: str, body: dict, timeout: int = 8) -> dict | list | None:
    """Make a POST request to the centralized NestJS API and return parsed JSON."""
    url = f"{get_api_base_url()}{endpoint if endpoint.startswith('/') else '/' + endpoint}"
    headers = get_headers()
    try:
        response = _session.post(url, headers=headers, json=body, timeout=timeout)
        response.raise_for_status()
        if not response.text or not response.text.strip():
            return None
        return response.json()
    except requests.exceptions.RequestException as e:
        safe_body = _sanitize_log_data(body)
        logger.warning(f"[API_CLIENT] Error en POST {url} con body {safe_body}: {e}")
        raise


def api_patch(endpoint: str, body: dict, timeout: int = 8) -> dict | list | None:
    """Make a PATCH request to the centralized NestJS API and return parsed JSON."""
    url = f"{get_api_base_url()}{endpoint if endpoint.startswith('/') else '/' + endpoint}"
    headers = get_headers()
    try:
        response = _session.patch(url, headers=headers, json=body, timeout=timeout)
        response.raise_for_status()
        if not response.text or not response.text.strip():
            return None
        return response.json()
    except requests.exceptions.RequestException as e:
        safe_body = _sanitize_log_data(body)
        logger.warning(f"[API_CLIENT] Error en PATCH {url} con body {safe_body}: {e}")
        raise


def api_put(endpoint: str, body: dict, timeout: int = 8) -> dict | list | None:
    """Make a PUT request to the centralized NestJS API and return parsed JSON."""
    url = f"{get_api_base_url()}{endpoint if endpoint.startswith('/') else '/' + endpoint}"
    headers = get_headers()
    try:
        response = _session.put(url, headers=headers, json=body, timeout=timeout)
        response.raise_for_status()
        if not response.text or not response.text.strip():
            return None
        return response.json()
    except requests.exceptions.RequestException as e:
        safe_body = _sanitize_log_data(body)
        logger.warning(f"[API_CLIENT] Error en PUT {url} con body {safe_body}: {e}")
        raise


def api_delete(endpoint: str, params: dict | None = None, timeout: int = 8) -> dict:
    """Make a DELETE request to the centralized NestJS API and return parsed JSON."""
    url = f"{get_api_base_url()}{endpoint if endpoint.startswith('/') else '/' + endpoint}"
    headers = get_headers()
    try:
        response = _session.delete(url, headers=headers, params=params, timeout=timeout)
        response.raise_for_status()
        if response.text and response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        return {"success": True}
    except requests.exceptions.RequestException as e:
        logger.warning(f"[API_CLIENT] Error en DELETE {url}: {e}")
        raise


def is_api_online(timeout: int = 4) -> bool:
    """Check if the centralized NestJS REST API is reachable."""
    try:
        url = f"{get_api_base_url()}/products"
        resp = _session.get(url, headers=get_headers(), timeout=timeout)
        return resp.status_code in (200, 201)
    except Exception:
        return False

