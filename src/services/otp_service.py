"""OTP and 2FA Account Linking Service for Cross-Platform Identity.

Allows users on Facebook Messenger and Instagram Direct to securely bind their
social profiles to an existing or new phone number by verifying ownership through
the WhatsApp bot.

Supports:
- Generating 6-digit secure PIN codes with 10-minute TTL.
- Sending WhatsApp verification alerts with interactive buttons:
    [❌ No soy esta persona] / [✅ Confirmar vinculación].
- Immediate invalidation if the WhatsApp owner rejects the request.
- Automatic identity binding in IdentityStore and Customer repository upon verification.
- Persistent cache in data/otp_linking_cache.json.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
import uuid
from pathlib import Path
from typing import Any

from src.repositories.identity_store import identity_store

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
CACHE_FILE = DATA_DIR / "otp_linking_cache.json"


class OTPService:
    """Manages 2FA verification and cross-channel account linking."""

    _instance: OTPService | None = None

    def __init__(self) -> None:
        self._requests: dict[str, dict[str, Any]] = {}
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._load()

    @classmethod
    def get_instance(cls) -> OTPService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load(self) -> None:
        if not CACHE_FILE.exists():
            return
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    self._requests = data.get("requests", {})
        except Exception as e:
            logger.debug(f"[OTPService] Error loading OTP cache: {e}")

    def _save(self) -> None:
        try:
            temp_file = CACHE_FILE.with_suffix(".tmp")
            payload = {"requests": self._requests}
            try:
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                temp_file.replace(CACHE_FILE)
            except (PermissionError, OSError):
                with open(CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug(f"[OTPService] Error saving OTP cache: {e}")

    def _cleanup_expired(self) -> None:
        now = time.time()
        to_del = [
            k for k, v in self._requests.items()
            if now - v.get("created_at", 0) > 86400
        ]
        if to_del:
            for k in to_del:
                self._requests.pop(k, None)
            self._save()

    def create_linking_request(
        self,
        channel: str,
        channel_user_id: str,
        phone: str,
        profile_name: str = "",
        tenant_id: str = "petroil",
        ttl_seconds: int = 600,
    ) -> dict[str, Any]:
        """
        Create a new OTP verification request for linking a social channel account to a phone.
        Cancels any existing pending requests for this channel_user_id.
        """
        self._load()
        self._cleanup_expired()

        clean_uid = str(channel_user_id).strip()
        clean_channel = str(channel).strip().lower()
        clean_phone = re.sub(r"\D", "", str(phone))
        if len(clean_phone) >= 10:
            clean_phone = clean_phone[-10:]

        req_id = uuid.uuid4().hex[:8]
        code = f"{random.randint(100000, 999999)}"
        now = time.time()

        for existing in self._requests.values():
            if (
                existing.get("channel") == clean_channel
                and existing.get("channel_user_id") == clean_uid
                and existing.get("status") == "pending"
            ):
                existing["status"] = "superseded"

        req_data: dict[str, Any] = {
            "id": req_id,
            "channel": clean_channel,
            "channel_user_id": clean_uid,
            "phone": clean_phone,
            "profile_name": str(profile_name or "Cliente").strip(),
            "tenant_id": str(tenant_id or "petroil").lower(),
            "code": code,
            "created_at": now,
            "expires_at": now + ttl_seconds,
            "status": "pending",
            "attempts": 0,
            "rejection_reason": "",
        }

        self._requests[req_id] = req_data
        self._save()
        logger.info(
            f"🔑 [OTPService] Created linking request #{req_id} for {clean_channel}:{clean_uid} "
            f"to phone {clean_phone} (Code: {code}, expires in {ttl_seconds}s)"
        )
        return req_data

    def get_pending_request(self, channel: str, channel_user_id: str) -> dict[str, Any] | None:
        """Get current active pending linking request for a channel user."""
        self._load()
        clean_uid = str(channel_user_id).strip()
        clean_channel = str(channel).strip().lower()
        now = time.time()

        for req in reversed(list(self._requests.values())):
            if (
                req.get("channel") == clean_channel
                and req.get("channel_user_id") == clean_uid
            ):
                if req.get("status") in ("pending", "rejected") and now <= req.get("expires_at", 0):
                    return req
        return None

    def get_pending_request_by_phone(self, phone: str) -> dict[str, Any] | None:
        """Find the latest pending linking request for a given phone number."""
        self._load()
        clean_phone = re.sub(r"\D", "", str(phone))
        if len(clean_phone) >= 10:
            clean_phone = clean_phone[-10:]
        now = time.time()

        for req in reversed(list(self._requests.values())):
            if req.get("phone") == clean_phone and req.get("status") == "pending":
                if now <= req.get("expires_at", 0):
                    return req
                else:
                    req["status"] = "expired"
                    self._save()
        return None

    def get_request_by_id(self, req_id: str) -> dict[str, Any] | None:
        """Lookup linking request by ID."""
        self._load()
        return self._requests.get(str(req_id).strip())

    def verify_code(
        self,
        channel: str,
        channel_user_id: str,
        input_code: str,
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """
        Verify the 6-digit OTP code submitted by the user on Messenger/Instagram.
        
        Returns:
            (success: bool, reason_code: str, req_data: dict | None)
            reason_code: "ok" | "not_found" | "rejected" | "expired" | "max_attempts" | "invalid_code"
        """
        self._load()
        clean_uid = str(channel_user_id).strip()
        clean_channel = str(channel).strip().lower()
        clean_code = re.sub(r"\D", "", str(input_code)).strip()
        now = time.time()

        req = None
        for r in reversed(list(self._requests.values())):
            if r.get("channel") == clean_channel and r.get("channel_user_id") == clean_uid:
                req = r
                break

        if not req:
            return False, "not_found", None

        if req.get("status") == "rejected":
            return False, "rejected", req

        if req.get("status") != "pending":
            return False, "expired", req

        if now > req.get("expires_at", 0):
            req["status"] = "expired"
            self._save()
            return False, "expired", req

        if req.get("attempts", 0) >= 3:
            req["status"] = "max_attempts"
            self._save()
            return False, "max_attempts", req

        if clean_code != req.get("code"):
            req["attempts"] = req.get("attempts", 0) + 1
            self._save()
            if req["attempts"] >= 3:
                return False, "max_attempts", req
            return False, "invalid_code", req

        req["status"] = "verified"
        req["verified_at"] = now
        self._save()

        self._apply_binding(req)

        logger.info(
            f"✅ [OTPService] Successfully verified request #{req['id']} for {clean_channel}:{clean_uid} -> {req['phone']}"
        )
        return True, "ok", req

    def reject_linking_request(
        self,
        phone: str,
        req_id: str | None = None,
        reason: str = "not_me",
    ) -> dict[str, Any] | None:
        """
        Called when the WhatsApp user clicks "No soy esta persona" / "No fui yo".
        Permanently invalidates the pending linking request and prevents unauthorized access.
        """
        self._load()
        clean_phone = re.sub(r"\D", "", str(phone))
        if len(clean_phone) >= 10:
            clean_phone = clean_phone[-10:]

        target_req = None
        if req_id and req_id in self._requests:
            target_req = self._requests[req_id]
        else:
            for r in reversed(list(self._requests.values())):
                if r.get("phone") == clean_phone and r.get("status") == "pending":
                    target_req = r
                    break

        if not target_req:
            return None

        target_req["status"] = "rejected"
        target_req["rejected_at"] = time.time()
        target_req["rejection_reason"] = reason
        target_req["code"] = ""  # Borrar el código para que quede destruido inmediatamente
        self._save()

        logger.warning(
            f"⛔ [OTPService] Linking request #{target_req['id']} was REJECTED by WhatsApp user {clean_phone} (Reason: {reason})"
        )
        return target_req

    def confirm_by_whatsapp(
        self,
        phone: str,
        req_id: str | None = None,
        code: str | None = None,
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """
        Called when the user confirms linking directly from WhatsApp.
        """
        self._load()
        clean_phone = re.sub(r"\D", "", str(phone))
        if len(clean_phone) >= 10:
            clean_phone = clean_phone[-10:]
        now = time.time()

        target_req = None
        if req_id and req_id in self._requests:
            target_req = self._requests[req_id]
        else:
            for r in reversed(list(self._requests.values())):
                if r.get("phone") == clean_phone and r.get("status") == "pending":
                    if code:
                        clean_c = re.sub(r"\D", "", str(code))
                        if r.get("code") == clean_c:
                            target_req = r
                            break
                    else:
                        target_req = r
                        break

        if not target_req:
            return False, "not_found", None

        if target_req.get("status") != "pending" or now > target_req.get("expires_at", 0):
            return False, "expired", target_req

        target_req["status"] = "verified"
        target_req["verified_at"] = now
        target_req["verified_via"] = "whatsapp_direct"
        self._save()

        self._apply_binding(target_req)
        return True, "ok", target_req

    def cancel_request(self, channel: str, channel_user_id: str) -> bool:
        """Cancel an active linking request if the user wants to re-enter a different number."""
        self._load()
        clean_uid = str(channel_user_id).strip()
        clean_channel = str(channel).strip().lower()
        cancelled = False

        for r in self._requests.values():
            if (
                r.get("channel") == clean_channel
                and r.get("channel_user_id") == clean_uid
                and r.get("status") in ("pending", "rejected")
            ):
                r["status"] = "cancelled"
                cancelled = True

        if cancelled:
            self._save()
        return cancelled

    def _apply_binding(self, req: dict[str, Any]) -> None:
        """Binds the social channel user ID to the verified phone in IdentityStore and Repository."""
        channel = req.get("channel", "")
        uid = req.get("channel_user_id", "")
        phone = req.get("phone", "")
        profile_name = req.get("profile_name", "")
        tenant_id = req.get("tenant_id", "petroil")

        if not channel or not uid or not phone:
            return

        identity_store.bind_channel_user_phone(channel, uid, phone, force=True)

        try:
            from src.repositories import get_repository
            repo = get_repository()
            existing_cust = repo.get_customer_by_phone(tenant_id, phone)
            if existing_cust:
                if existing_cust.name in ("Cliente", "Usuario", "", None) and profile_name:
                    repo.update_customer_name(tenant_id, phone, profile_name)
                logger.info(
                    f"🔗 [OTPService] Linked existing customer '{existing_cust.name}' ({phone}) to {channel}:{uid}"
                )
            else:
                repo.save_or_update_customer(
                    tenant_id=tenant_id,
                    channel=channel,
                    channel_user_id=uid,
                    name=profile_name or "Cliente",
                    phone=phone,
                )
                logger.info(
                    f"🆕 [OTPService] Created new unified customer '{profile_name}' ({phone}) for {channel}:{uid}"
                )
        except Exception as e:
            logger.error(f"[OTPService] Error applying customer binding in repo: {e}")


otp_service = OTPService.get_instance()


async def send_whatsapp_otp_challenge(
    phone: str,
    code: str,
    channel: str,
    profile_name: str,
    req_id: str,
    tenant_id: str = "petroil",
) -> bool:
    """
    Sends the 2FA verification message to the user's WhatsApp with an interactive button:
    [❌ No soy esta persona] so they can cancel immediately if it's the wrong number.
    """
    try:
        from src.channels.whatsapp.adapter import WhatsAppAdapter
        adapter = WhatsAppAdapter()
        if not adapter.is_configured:
            logger.warning("[OTPService] WhatsApp adapter is not configured, cannot send challenge.")
            return False

        chan_name = "Facebook Messenger" if channel.lower() == "messenger" else (
            "Instagram Direct" if channel.lower() == "instagram" else channel.title()
        )

        body_text = (
            f"🔐 *Gas a Tu Puerta - Vinculación de Cuenta*\n\n"
            f"Detectamos una solicitud para vincular este número de WhatsApp con tu perfil de *{chan_name}*:\n"
            f"👤 *{profile_name or 'Cliente'}*\n\n"
            f"Tu código de verificación es: *{code}*\n"
            f"_(Válido por 10 minutos)_\n\n"
            f"⚠️ *¿No eres tú o se equivocaron de número?*\n"
            f"Si tú no solicitaste este código o se equivocaron de número, presiona el botón *No soy esta persona* abajo para cancelar y borrar la solicitud de inmediato (ya no procederá nada)."
        )

        buttons = [
            {"id": f"otp_reject:{req_id}", "title": "❌ No soy esta persona"},
        ]

        # Intentar enviar con botón interactivo oficial
        ok = await adapter.send_interactive_buttons(
            recipient_wa_id=phone,
            body_text=body_text,
            buttons=buttons,
            header_text="🔐 Seguridad Gas a Tu Puerta",
            footer_text="Gas a Tu Puerta",
        )
        if not ok:
            # Respaldo como mensaje de texto plano con instrucciones
            plain_text = (
                f"{body_text}\n\n"
                f"_(Si no eres tú o se equivocaron de número, responde a este mensaje con: 'No soy yo' para borrar y cancelar la solicitud de inmediato)_"
            )
            ok = await adapter.send_text_message(recipient_wa_id=phone, text=plain_text)

        logger.info(f"📲 [OTPService] WhatsApp challenge sent to {phone} (Success: {ok})")
        return ok
    except Exception as e:
        logger.error(f"[OTPService] Error sending WhatsApp OTP challenge to {phone}: {e}", exc_info=True)
        return False

