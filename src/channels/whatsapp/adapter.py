"""WhatsApp Cloud API Adapter (Meta Graph API).

Handles outbound and inbound message translations between Meta WhatsApp Cloud API
and the internal LangGraph sales agent ecosystem.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from src.config.settings import get_settings
from src.models.customer import CustomerAddress
from src.models.message import InboundMessage, OutboundMessage
from src.repositories import get_repository
from src.services.geocoding import resolve_gps_address_to_name

logger = logging.getLogger(__name__)


class WhatsAppAdapter:
    """Enterprise Adapter for WhatsApp Cloud API (Meta)."""

    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def api_version(self) -> str:
        return self.settings.whatsapp_api_version or "v21.0"

    @property
    def phone_number_id(self) -> str:
        return self.settings.whatsapp_phone_number_id

    @property
    def access_token(self) -> str:
        return self.settings.whatsapp_token

    @property
    def is_configured(self) -> bool:
        return bool(self.phone_number_id and self.access_token)

    @property
    def base_url(self) -> str:
        return f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"

    def _get_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    async def _post_meta(self, client: httpx.AsyncClient, url: str, payload: dict[str, Any]) -> httpx.Response:
        """Post to Meta Graph API with automatic 401 token invalidation and single retry."""
        resp = await client.post(url, headers=self._get_headers(), json=payload)
        if resp.status_code == 401:
            logger.warning("[WhatsApp] Meta API returned 401 Unauthorized. Invalidating dynamic settings cache and refreshing...")
            from src.services.dynamic_settings import invalidate_dynamic_settings_cache, fetch_remote_settings
            invalidate_dynamic_settings_cache()
            fetch_remote_settings(force_refresh=True)
            resp = await client.post(url, headers=self._get_headers(), json=payload)
        return resp

    async def _get_meta(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        """Get from Meta Graph API with automatic 401 token invalidation and single retry."""
        resp = await client.get(url, headers=self._get_headers())
        if resp.status_code == 401:
            logger.warning("[WhatsApp] Meta API returned 401 Unauthorized. Invalidating dynamic settings cache and refreshing...")
            from src.services.dynamic_settings import invalidate_dynamic_settings_cache, fetch_remote_settings
            invalidate_dynamic_settings_cache()
            fetch_remote_settings(force_refresh=True)
            resp = await client.get(url, headers=self._get_headers())
        return resp

    # -------------------------------------------------------------------------
    # Inbound Webhook Parsing
    # -------------------------------------------------------------------------

    def parse_webhook_events(self, raw: dict[str, Any], default_tenant_id: str = "petroil") -> list[dict[str, Any]]:
        """Parse raw WhatsApp Cloud API webhook into normalized message event dictionaries.
        
        Filters out system delivery/read receipts and extracts user messages,
        GPS locations, interactive button replies, and list selections.
        """
        parsed_events: list[dict[str, Any]] = []

        if not raw or not isinstance(raw, dict):
            return parsed_events

        values: list[dict[str, Any]] = []

        if "entry" in raw and isinstance(raw["entry"], list):
            for entry in raw["entry"]:
                for change in entry.get("changes", []):
                    val = change.get("value")
                    if val and isinstance(val, dict):
                        values.append(val)
        elif "value" in raw and isinstance(raw["value"], dict):
            values.append(raw["value"])
        elif "messages" in raw and isinstance(raw["messages"], list):
            values.append(raw)

        for value in values:
            contacts = {c.get("wa_id"): c.get("profile", {}).get("name", "Cliente") for c in value.get("contacts", []) if isinstance(c, dict)}
            messages = value.get("messages", [])

            for msg in messages:
                msg_id = msg.get("id", "")
                sender_wa_id = msg.get("from", "")
                msg_type = msg.get("type", "text")
                sender_name = contacts.get(sender_wa_id, "Cliente")
                timestamp = msg.get("timestamp", "")

                event: dict[str, Any] = {
                    "msg_id": msg_id,
                    "wa_id": sender_wa_id,
                    "name": sender_name,
                    "timestamp": timestamp,
                    "type": msg_type,
                    "tenant_id": default_tenant_id,
                    "text": "",
                    "location": None,
                    "interactive_id": None,
                    "interactive_title": None,
                    "raw": msg,
                }

                if msg_type == "text":
                    event["text"] = msg.get("text", {}).get("body", "").strip()

                elif msg_type == "location":
                    loc = msg.get("location", {})
                    event["location"] = {
                        "latitude": loc.get("latitude"),
                        "longitude": loc.get("longitude"),
                        "name": loc.get("name", ""),
                        "address": loc.get("address", ""),
                    }

                elif msg_type == "interactive":
                    interactive = msg.get("interactive", {})
                    itype = interactive.get("type")
                    if itype == "button_reply":
                        b_reply = interactive.get("button_reply", {})
                        event["interactive_id"] = b_reply.get("id")
                        event["interactive_title"] = b_reply.get("title")
                        event["text"] = b_reply.get("title", "")
                    elif itype == "list_reply":
                        l_reply = interactive.get("list_reply", {})
                        event["interactive_id"] = l_reply.get("id")
                        event["interactive_title"] = l_reply.get("title")
                        event["text"] = l_reply.get("title", "")

                elif msg_type == "image":
                    img = msg.get("image", {})
                    event["media_id"] = img.get("id")
                    event["mime_type"] = img.get("mime_type", "image/jpeg")
                    event["text"] = img.get("caption", "[Imagen enviada por el cliente]")

                elif msg_type in ("audio", "voice"):
                    audio = msg.get("audio", {}) or msg.get("voice", {})
                    event["media_id"] = audio.get("id")
                    event["mime_type"] = audio.get("mime_type", "audio/ogg")
                    event["text"] = "[Nota de voz recibida]"

                parsed_events.append(event)

        return parsed_events

    def parse_webhook(self, raw: dict[str, Any]) -> InboundMessage:
        """Parse webhook into a single InboundMessage protocol object."""
        events = self.parse_webhook_events(raw)
        if not events:
            return InboundMessage(
                channel="whatsapp",
                channel_message_id="empty-wa-id",
                channel_user_id="anonymous",
                tenant_id="petroil",
                text="",
                received_at=datetime.now(timezone.utc),
                raw_payload=raw,
            )

        ev = events[0]
        return InboundMessage(
            channel="whatsapp",
            channel_message_id=ev["msg_id"],
            channel_user_id=ev["wa_id"],
            tenant_id=ev["tenant_id"],
            text=ev["text"],
            received_at=datetime.now(timezone.utc),
            raw_payload=raw,
        )

    # -------------------------------------------------------------------------
    # Outbound Message Senders & Media Handler (Meta Cloud API)
    # -------------------------------------------------------------------------

    async def download_media(self, media_id: str, dest_path: Path) -> Path | None:
        """Download media file (voice note, audio, image) directly from Meta Graph API."""
        if not self.is_configured or not media_id:
            logger.warning(f"[WhatsApp] Cannot download media '{media_id}': credentials not configured.")
            return None

        try:
            # 1. Consultar URL temporal de descarga desde Meta
            media_info_url = f"https://graph.facebook.com/{self.api_version}/{media_id}"
            async with httpx.AsyncClient(timeout=15.0) as client:
                info_resp = await self._get_meta(client, media_info_url)
                if info_resp.status_code != 200:
                    logger.error(f"[WhatsApp] Failed to get media info for {media_id}: HTTP {info_resp.status_code} - {info_resp.text}")
                    return None

                media_data = info_resp.json()
                download_url = media_data.get("url")
                if not download_url:
                    logger.error(f"[WhatsApp] No download URL returned for media {media_id}: {media_data}")
                    return None

                # 2. Descargar el archivo binario usando el access token en los headers
                file_resp = await self._get_meta(client, download_url)
                if file_resp.status_code != 200:
                    logger.error(f"[WhatsApp] Failed to download binary file for media {media_id}: HTTP {file_resp.status_code}")
                    return None

                dest_path.parent.mkdir(parents=True, exist_ok=True)
                with open(dest_path, "wb") as f:
                    f.write(file_resp.content)

                logger.info(f"[WhatsApp] Media {media_id} downloaded successfully to {dest_path} ({len(file_resp.content)} bytes)")
                return dest_path
        except Exception as e:
            logger.error(f"[WhatsApp] Exception downloading media {media_id}: {e}", exc_info=True)
            return None

    async def mark_as_read(self, message_id: str) -> bool:
        """Mark an incoming WhatsApp message as read."""
        if not self.is_configured or not message_id:
            return False

        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await self._post_meta(client, self.base_url, payload)
                return resp.status_code in (200, 202)
        except Exception as e:
            logger.debug(f"[WhatsApp] mark_as_read error: {e}")
            return False

    async def send_text_message(
        self,
        recipient_wa_id: str,
        text: str,
        preview_url: bool = False,
    ) -> bool:
        """Send a plain or markdown-formatted text message to a WhatsApp user."""
        if not self.is_configured:
            logger.warning(f"[WhatsApp] Cannot send text to {recipient_wa_id}: WhatsApp credentials not configured in .env")
            return False

        if not text:
            return False

        clean_phone = self.normalize_wa_id(recipient_wa_id)
        max_len = 4000

        # Chunk text if exceeds WhatsApp text limit
        chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)]
        success = True

        async with httpx.AsyncClient(timeout=15.0) as client:
            for chunk in chunks:
                payload = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": clean_phone,
                    "type": "text",
                    "text": {
                        "preview_url": preview_url,
                        "body": chunk,
                    },
                }

                try:
                    resp = await self._post_meta(client, self.base_url, payload)
                    if resp.status_code not in (200, 201, 202):
                        logger.error(f"[WhatsApp] HTTP {resp.status_code} error sending to {clean_phone}: {resp.text}")
                        success = False
                except Exception as e:
                    logger.error(f"[WhatsApp] Exception sending text to {clean_phone}: {e}")
                    success = False

        return success

    async def send_interactive_buttons(
        self,
        recipient_wa_id: str,
        body_text: str,
        buttons: list[dict[str, str]],
        header_text: str | None = None,
        footer_text: str | None = "Gas a Tu Puerta - Petroil",
    ) -> bool:
        """Send up to 3 Quick Reply interactive buttons."""
        if not self.is_configured:
            logger.warning(f"[WhatsApp] Cannot send buttons to {recipient_wa_id}: credentials missing.")
            return False

        if not buttons or not body_text:
            return False

        clean_phone = self.normalize_wa_id(recipient_wa_id)
        sliced_buttons = buttons[:3]

        formatted_buttons = []
        for b in sliced_buttons:
            btn_id = b.get("id", "btn")[:256]
            title = b.get("title", "Opción")[:20]
            formatted_buttons.append({
                "type": "reply",
                "reply": {
                    "id": btn_id,
                    "title": title,
                },
            })

        action_dict: dict[str, Any] = {"buttons": formatted_buttons}

        interactive_obj: dict[str, Any] = {
            "type": "button",
            "body": {"text": body_text[:1024]},
            "action": action_dict,
        }

        if header_text:
            interactive_obj["header"] = {"type": "text", "text": header_text[:60]}
        if footer_text:
            interactive_obj["footer"] = {"text": footer_text[:60]}

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "interactive",
            "interactive": interactive_obj,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await self._post_meta(client, self.base_url, payload)
                if resp.status_code in (200, 201, 202):
                    return True
                logger.error(f"[WhatsApp] Error sending buttons ({resp.status_code}): {resp.text}")
                return await self.send_text_message(clean_phone, body_text)
        except Exception as e:
            logger.error(f"[WhatsApp] Exception sending buttons to {clean_phone}: {e}")
            return await self.send_text_message(clean_phone, body_text)

    async def send_interactive_list(
        self,
        recipient_wa_id: str,
        body_text: str,
        button_label: str,
        sections: list[dict[str, Any]],
        header_text: str | None = None,
        footer_text: str | None = "Gas a Tu Puerta - Petroil",
    ) -> bool:
        """Send an interactive list message (menu picker with sections and rows up to 10 items)."""
        if not self.is_configured:
            logger.warning(f"[WhatsApp] Cannot send list to {recipient_wa_id}: credentials missing.")
            return False

        clean_phone = self.normalize_wa_id(recipient_wa_id)

        formatted_sections = []
        total_rows = 0

        for sec in sections:
            sec_title = sec.get("title", "Opciones")[:24]
            raw_rows = sec.get("rows", [])
            valid_rows = []

            for r in raw_rows:
                if total_rows >= 10:
                    break
                row_id = str(r.get("id", "item"))[:200]
                row_title = str(r.get("title", "Opción"))[:24]
                row_desc = str(r.get("description", ""))[:72] if r.get("description") else None

                row_dict: dict[str, Any] = {
                    "id": row_id,
                    "title": row_title,
                }
                if row_desc:
                    row_dict["description"] = row_desc
                valid_rows.append(row_dict)
                total_rows += 1

            if valid_rows:
                formatted_sections.append({
                    "title": sec_title,
                    "rows": valid_rows,
                })

        interactive_obj: dict[str, Any] = {
            "type": "list",
            "body": {"text": body_text[:1024]},
            "action": {
                "button": button_label[:20],
                "sections": formatted_sections,
            },
        }

        if header_text:
            interactive_obj["header"] = {"type": "text", "text": header_text[:60]}
        if footer_text:
            interactive_obj["footer"] = {"text": footer_text[:60]}

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "interactive",
            "interactive": interactive_obj,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await self._post_meta(client, self.base_url, payload)
                if resp.status_code in (200, 201, 202):
                    return True
                logger.error(f"[WhatsApp] Error sending list ({resp.status_code}): {resp.text}")
                return await self.send_text_message(clean_phone, body_text)
        except Exception as e:
            logger.error(f"[WhatsApp] Exception sending list to {clean_phone}: {e}")
            return await self.send_text_message(clean_phone, body_text)

    async def send_location(
        self,
        recipient_wa_id: str,
        lat: float,
        lng: float,
        name: str = "Punto de Entrega",
        address: str = "",
    ) -> bool:
        """Send a location pin to the customer."""
        if not self.is_configured:
            return False

        clean_phone = self.normalize_wa_id(recipient_wa_id)
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "location",
            "location": {
                "latitude": lat,
                "longitude": lng,
                "name": name[:100],
                "address": address[:300],
            },
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await self._post_meta(client, self.base_url, payload)
                return resp.status_code in (200, 201, 202)
        except Exception as e:
            logger.error(f"[WhatsApp] Exception sending location: {e}")
            return False

    async def send_reply(
        self, channel_user_id: str, message: OutboundMessage
    ) -> None:
        """Send OutboundMessage protocol object back to WhatsApp user."""
        if message.text:
            await self.send_text_message(channel_user_id, message.text)

    # -------------------------------------------------------------------------
    # Contextual WhatsApp Menus & Interactive Detection
    # -------------------------------------------------------------------------

    @staticmethod
    def normalize_wa_id(wa_id: str) -> str:
        """Normalize WhatsApp phone ID to standard E.164 digits for Meta Cloud API.
        
        - Strips non-digits.
        - For Mexico mobile numbers (521XXXXXXXXXX -> 13 digits), removes the mobile prefix '1'
          producing 52XXXXXXXXXX (12 digits) required by Meta Graph API and test number allowlists.
        - For 10-digit local numbers, prepends '52' -> 12 digits.
        """
        clean = re.sub(r"\D", "", str(wa_id))
        if clean.startswith("521") and len(clean) == 13:
            clean = "52" + clean[3:]
        elif len(clean) == 10:
            clean = "52" + clean
        return clean

    @staticmethod
    def extract_10_digit_phone(wa_id: str) -> str:
        """Extract a standard 10-digit Mexican phone number from a WhatsApp ID."""
        digits = re.sub(r"\D", "", str(wa_id))
        if digits.startswith("521") and len(digits) == 13:
            return digits[3:]
        if digits.startswith("52") and len(digits) == 12:
            return digits[2:]
        if len(digits) == 10:
            return digits
        return digits[-10:] if len(digits) >= 10 else digits

    def get_service_type_buttons(self) -> list[dict[str, str]]:
        """Interactive buttons for initial service selection."""
        return [
            {"id": "client_svc:cilindro", "title": "🛻 Cilindro de Gas"},
            {"id": "client_svc:estacionario", "title": "🚛 Estacionario"},
        ]

    def get_schedule_buttons(self) -> list[dict[str, str]]:
        """Interactive buttons for delivery schedule selection."""
        return [
            {"id": "client_sch:asap", "title": "⚡ Lo antes posible"},
            {"id": "client_sch:custom", "title": "📅 Programar entrega"},
        ]

    def get_schedule_alternative_buttons(self) -> list[dict[str, str]]:
        """Interactive buttons when a requested schedule is full and an alternative is offered."""
        return [
            {"id": "client_sch:accept", "title": "✅ Aceptar horario"},
            {"id": "client_sch:custom", "title": "📅 Elegir otro"},
        ]

    def get_payment_method_buttons(self) -> list[dict[str, str]]:
        """Interactive buttons for payment method selection."""
        return [
            {"id": "client_pay:efectivo", "title": "💵 Efectivo"},
            {"id": "client_pay:terminal", "title": "💳 Terminal Tarjeta"},
        ]

    def get_confirmation_buttons(self) -> list[dict[str, str]]:
        """Interactive buttons for order confirmation summary."""
        return [
            {"id": "client_confirm:yes", "title": "✅ Confirmar Pedido"},
            {"id": "client_confirm:edit", "title": "✏️ Modificar"},
            {"id": "client_confirm:cancel", "title": "❌ Cancelar"},
        ]

    def get_order_active_buttons(self, order_id: int | str) -> list[dict[str, str]]:
        """Interactive buttons for confirmed / active / in-route orders."""
        return [
            {"id": f"check_order_status:{order_id}", "title": "📍 Ver Estatus"},
            {"id": f"cancel_order_client:{order_id}", "title": "❌ Cancelar Pedido"},
        ]

    def get_order_cancel_confirm_buttons(self, order_id: int | str) -> list[dict[str, str]]:
        """Confirmation buttons when client requests to cancel an order (<= 20 chars per title)."""
        return [
            {"id": f"confirm_cancel_order_client:{order_id}", "title": "⚠️ Sí, Cancelar"},
            {"id": f"keep_order_client:{order_id}", "title": "🔙 No, Conservar"},
        ]

    def get_edit_options_list_sections(self) -> list[dict[str, Any]]:
        """Interactive list sections for editing draft order data."""
        return [{
            "title": "Modificar Pedido",
            "rows": [
                {"id": "client_edit:schedule", "title": "⏰ Cambiar Horario", "description": "Modificar fecha u hora de entrega"},
                {"id": "client_edit:address", "title": "📍 Cambiar Dirección", "description": "Cambiar domicilio de entrega"},
                {"id": "client_edit:payment", "title": "💳 Forma de Pago", "description": "Cambiar efectivo / terminal"},
                {"id": "client_edit:product", "title": "📦 Cambiar Producto", "description": "Modificar cilindros o recarga"},
                {"id": "client_edit:phone", "title": "📱 Cambiar Teléfono", "description": "Corregir número celular"},
                {"id": "client_edit:back", "title": "🔙 Volver al Resumen", "description": "Regresar a confirmación del pedido"},
            ]
        }]


    def get_rating_feedback_sections(self, order_id: int | str, stars: int) -> list[dict[str, Any]]:
        """Return interactive list sections for rating feedback tags."""
        if stars >= 4:
            return [{
                "title": "Aspectos Destacados",
                "rows": [
                    {"id": f"rate_tag:{order_id}:Rapidez", "title": "⚡ Rapidez", "description": "Llegó muy rápido y puntual"},
                    {"id": f"rate_tag:{order_id}:Amabilidad", "title": "😊 Amabilidad", "description": "Trato amable y cordial"},
                    {"id": f"rate_tag:{order_id}:Seguridad", "title": "🛡️ Seguridad", "description": "Manejo seguro del cilindro"},
                    {"id": f"rate_tag:{order_id}:Impecable", "title": "✨ Impecable", "description": "Servicio de alta calidad"},
                    {"id": f"rate_tag:{order_id}:Omitido", "title": "⏩ Finalizar", "description": "Concluir sin más detalles"},
                ]
            }]
        else:
            return [{
                "title": "Motivo de Inconformidad",
                "rows": [
                    {"id": f"rate_tag:{order_id}:Demora", "title": "⏳ Demora", "description": "Tardó más de lo esperado"},
                    {"id": f"rate_tag:{order_id}:Actitud", "title": "🙁 Actitud", "description": "Atención o actitud del chofer"},
                    {"id": f"rate_tag:{order_id}:Cilindro", "title": "📦 Cilindro", "description": "Inconformidad con el cilindro"},
                    {"id": f"rate_tag:{order_id}:Cobro", "title": "💵 Cobro", "description": "Problema con el cobro o cambio"},
                    {"id": f"rate_tag:{order_id}:Omitido", "title": "⏩ Finalizar", "description": "Concluir sin más detalles"},
                ]
            }]

    def get_cylinder_catalog_list_sections(self, tenant_id: str = "petroil") -> list[dict[str, Any]]:
        """Generate interactive list sections directly from real SQLite database products, without duplicates."""
        try:
            repo = get_repository()
            prods = repo.get_all_products(tenant_id)
            cilindros = [
                p for p in prods
                if getattr(p, "in_stock", True) and (
                    (getattr(p, "category", "") or "").lower() in ("cilindros", "gas lp", "gas")
                    or "cilindro" in p.name.lower()
                    or "kg" in p.name.lower()
                )
                and "estacionario" not in p.name.lower()
                and p.id != "entrega-domicilio"
                and "servicio" not in (getattr(p, "category", "") or "").lower()
            ]
        except Exception as e:
            logger.error(f"[WhatsApp] Error loading catalog from DB: {e}")
            cilindros = []

        # Ordenar dinámicamente por capacidad (kg) o precio
        def sort_key(p):
            m = re.search(r"(\d+)\s*kg", p.name, re.IGNORECASE)
            if m:
                return (0, int(m.group(1)))
            return (1, p.price)

        cilindros_sorted = sorted(cilindros, key=sort_key)

        rows = []
        for p in cilindros_sorted:
            title = p.name
            m_kg = re.search(r"(\d+\s*kg)", p.name, re.IGNORECASE)
            if m_kg:
                title = f"Cilindro Gas LP {m_kg.group(1).upper()}"
            if len(title) > 24:
                title = title[:23] + "."

            rows.append({
                "id": f"cart_add:{p.id}:1",
                "title": title,
                "description": f"${p.price:.2f} {p.currency}",
            })

        return [{
            "title": "Catálogo de Cilindros",
            "rows": rows[:10],
        }]

    def get_customer_addresses_buttons(self, addresses: list[CustomerAddress]) -> list[dict[str, str]]:
        """Generate up to 3 Quick Reply buttons for saved customer addresses + new address + delete address."""
        buttons = []
        if addresses:
            addr = addresses[0]
            addr_text = resolve_gps_address_to_name(addr.address.strip())
            addr_text = re.sub(r"^(?:\[(?:Nueva\s*Direcci[oó]n|Direcci[oó]n(?:\s*\d+)?|Principal)\]\s*)+", "", addr_text, flags=re.I).strip()
            es_generico = bool(re.match(r"^(?:principal|predeterminada|nueva\s*direcci[oó]n|direcci[oó]n(?:\s*\d+)?)$", (addr.alias or "").strip(), re.I))
            alias = addr.alias.strip() if addr.alias and not es_generico else ""
            if alias:
                btn_title = f"1. 📍 {alias}"
            else:
                clean_name = re.sub(r"^(?:Calle|Av\.?|Avenida)\s*", "", addr_text, flags=re.I).strip()
                btn_title = f"1. 📍 {clean_name}"
            if len(btn_title) > 20:
                btn_title = btn_title[:19] + "."
            buttons.append({
                "id": "client_addr:1",
                "title": btn_title,
            })

        buttons.append({
            "id": "client_addr:new",
            "title": "➕ Nueva Dirección",
        })

        if addresses:
            buttons.append({
                "id": "client_addr:del_menu",
                "title": "🗑️ Eliminar Dir.",
            })
        return buttons

    def get_customer_addresses_list_sections(self, addresses: list[CustomerAddress]) -> list[dict[str, Any]]:
        """Generate interactive list sections for saved customer addresses with options for new and delete."""
        rows = []
        for i, addr in enumerate(addresses[:8], 1):
            addr_text = resolve_gps_address_to_name(addr.address.strip())
            addr_text = re.sub(r"^(?:\[(?:Nueva\s*Direcci[oó]n|Direcci[oó]n(?:\s*\d+)?|Principal)\]\s*)+", "", addr_text, flags=re.I).strip()
            es_generico = bool(re.match(r"^(?:principal|predeterminada|nueva\s*direcci[oó]n|direcci[oó]n(?:\s*\d+)?)$", (addr.alias or "").strip(), re.I))
            alias = addr.alias.strip() if addr.alias and not es_generico else ""
            alias_tag = f"[{alias}] " if alias else ""
            title = f"{i}. 📍 {alias_tag}{addr_text}"
            if len(title) > 24:
                title = title[:23] + "."

            desc = addr_text if len(addr_text) <= 72 else addr_text[:69] + "..."
            rows.append({
                "id": f"client_addr:{i}",
                "title": title,
                "description": desc,
            })

        rows.append({
            "id": "client_addr:new",
            "title": "➕ Nueva Dirección",
            "description": "Ingresar otro domicilio de entrega",
        })

        if addresses:
            rows.append({
                "id": "client_addr:del_menu",
                "title": "🗑️ Eliminar Dirección",
                "description": "Borrar una de mis direcciones guardadas",
            })

        return [{
            "title": "Direcciones Guardadas",
            "rows": rows,
        }]

    def get_delete_addresses_list_sections(self, addresses: list[CustomerAddress]) -> list[dict[str, Any]]:
        """Generate interactive list sections for deleting customer addresses."""
        rows = []
        for i, addr in enumerate(addresses[:9], 1):
            addr_text = resolve_gps_address_to_name(addr.address.strip())
            addr_text = re.sub(r"^(?:\[(?:Nueva\s*Direcci[oó]n|Direcci[oó]n(?:\s*\d+)?|Principal)\]\s*)+", "", addr_text, flags=re.I).strip()
            es_generico = bool(re.match(r"^(?:principal|predeterminada|nueva\s*direcci[oó]n|direcci[oó]n(?:\s*\d+)?)$", (addr.alias or "").strip(), re.I))
            alias = addr.alias.strip() if addr.alias and not es_generico else ""
            alias_tag = f"[{alias}] " if alias else ""
            title = f"🗑️ {i}. {alias_tag}{addr_text}"
            if len(title) > 24:
                title = title[:23] + "."

            desc = f"Eliminar: {addr_text}"
            if len(desc) > 72:
                desc = desc[:69] + "..."

            rows.append({
                "id": f"del_addr:{addr.id}",
                "title": title,
                "description": desc,
            })

        return [{
            "title": "Selecciona para Eliminar",
            "rows": rows,
        }]

    @staticmethod
    def extract_addresses_from_text(text: str) -> list[CustomerAddress]:
        """Extract numbered addresses from agent response text."""
        addrs: list[CustomerAddress] = []
        lines = text.split("\n")
        for line in lines:
            line_s = line.strip()
            # Match lines starting with a number like "1.", "1)", "1.-", "• 1.", "- 1."
            m_start = re.match(r"^(?:[•\-\*]\s*)?(\d+)[\.\)\-]+\s*(?:📍|\uD83D\uDCCD)?\s*(.+)$", line_s)
            if not m_start:
                continue

            idx = int(m_start.group(1))
            rest = m_start.group(2).strip()

            alias = ""
            # Check for bracketed alias: e.g. [Casa] or **[Casa]** or [Casa de Playa]
            m_alias = re.match(r"^(?:\*{1,2})?\[(.*?)\](?:\*{1,2})?\s*(.*)$", rest)
            if m_alias:
                alias = m_alias.group(1).strip()
                addr_text = m_alias.group(2).strip()
            else:
                addr_text = rest

            if not alias:
                alias = f"Dirección {idx}"

            # Clean trailing markdown or symbols
            addr_text = addr_text.strip("*_ ")

            # Filter out non-address lines (questions, headers)
            if (
                addr_text
                and not addr_text.endswith("?")
                and not addr_text.startswith("¿")
                and len(addr_text) > 3
                and not any(k in addr_text.lower() for k in ["cuál de estas", "cual de estas", "direcciones registradas", "siguientes direcciones"])
            ):
                addrs.append(CustomerAddress(id=idx, address=addr_text, alias=alias))
        return addrs

    def clean_text_for_interactive(self, text: str, interactive_type: str, subtype: str = "") -> str:
        """Clean up redundant text when interactive WhatsApp elements are attached."""
        if subtype == "addresses":
            # Truncar cualquier alucinación en la que el LLM simule la respuesta o confirmación del cliente en el mismo mensaje
            m_stop = re.search(r"(¿(?:cuál opción prefieres|a cuál de tus direcciones|cuál de tus direcciones|cuál opción deseas|cuál prefieres)[^?\n]*\?[\s🏠🏡]*)(.*)", text, flags=re.I | re.S)
            if m_stop and m_stop.group(2).strip():
                text = text[:m_stop.end(1)].strip()
            else:
                m_halluc = re.search(r"\n\s*(?:¡?Gracias[^!\n]*!?\s*(?:🏠|🏡)?\s*(?:He registrado|registré|anoté|seleccioné)?\s*la siguiente dirección.*)", text, flags=re.I | re.S)
                if m_halluc:
                    text = text[:m_halluc.start()].strip()

            lines = text.split("\n")
            filtered = [
                l for l in lines
                if not re.match(r"^\s*(?:[•\-\*]\s*)?\d+[\.\)\-]+\s*(?:📍|\uD83D\uDCCD|\*\*\[|\[)?", l.strip())
            ]
            cleaned = "\n".join(filtered).strip()
            cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
            return cleaned or "¿A cuál de tus direcciones deseas que enviemos tu pedido?"

        if interactive_type == "list":
            if subtype == "catalog":
                lines = text.split("\n")
                filtered = []
                for l in lines:
                    l_str = l.strip()
                    is_item = bool(
                        re.match(r"^\s*(?:[•\-\*▪🔹🔸\d\.\)]+)\s*(?:\*\*)?(?:cilindro|gas\s*lp|gas|recarga|tanque|\d+\s*kg)", l_str, re.I)
                        and (re.search(r"\$\s*\d+", l_str) or re.search(r"\b(?:kg|litros|pesos|mxn)\b", l_str, re.I))
                    )
                    if is_item:
                        continue
                    is_intro = bool(
                        re.search(r"(?:contamos con las siguientes|tenemos estas opciones|a continuación te muestro|te presento las opciones|capacidades disponibles|opciones disponibles|estas son las opciones|opciones de cilindros)", l_str, re.I)
                        and (":" in l_str or "disponible" in l_str.lower() or "opciones" in l_str.lower())
                    )
                    if is_intro:
                        continue
                    filtered.append(l)
                cleaned = "\n".join(filtered).strip()
                cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
                return cleaned or "🛒 Selecciona la capacidad que necesitas en el menú a continuación:"

            if subtype == "payment":
                lines = text.split("\n")
                filtered = [
                    l for l in lines
                    if not re.match(r"^\s*(?:[•\-\*▪\d\.\)]+)\s*(?:\*\*)?(?:efectivo|terminal|tarjeta)", l.strip(), re.I)
                ]
                cleaned = "\n".join(filtered).strip()
                cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
                return cleaned or "¿Cómo deseas realizar tu pago?"

        elif interactive_type == "buttons":
            if subtype == "service":
                lines = text.split("\n")
                filtered = [
                    l for l in lines
                    if not re.search(r"(?:cilindro|tanque\s*estacionario)", l, re.I)
                    and not re.search(r"^\s*(?:¿cuál prefieres\?|¿cual prefieres\?|cuál prefieres|cual prefieres)\s*$", l.strip(), re.I)
                ]
                cleaned = "\n".join(filtered).strip()
                cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
                return cleaned or "¿Qué tipo de servicio de gas necesitas hoy?"
            elif subtype == "payment":
                lines = text.split("\n")
                filtered = [
                    l for l in lines
                    if not re.match(r"^\s*(?:[•\-\*▪\d\.\)]+)\s*(?:\*\*)?(?:efectivo|terminal|tarjeta)", l.strip(), re.I)
                ]
                cleaned = "\n".join(filtered).strip()
                cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
                return cleaned or "¿Cómo deseas realizar tu pago?"
            elif subtype == "schedule":
                lines = text.split("\n")
                filtered = [
                    l for l in lines
                    if not re.search(r"^\s*(?:[•\-\*▪🔹🔸\d\.\)]+)\s*(?:\*\*)?(?:⚡|📅)?\s*(?:lo antes posible|programar entrega)", l.strip(), re.I)
                ]
                cleaned = "\n".join(filtered).strip()
                cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
                return cleaned or "¿Para qué día y horario deseas programar tu entrega?"
            elif subtype == "confirmation":
                return text

        return text

    def detect_interactive_elements(
        self,
        respuesta: str,
        phone: str = "",
        channel_user_id: str = "",
        tenant_id: str = "petroil",
        user_text: str = "",
    ) -> tuple[str, dict[str, Any] | None]:
        """Detect conversational context and produce interactive WhatsApp UI elements.

        Returns (cleaned_text, interactive_spec) or (respuesta, None).
        """
        if not respuesta or not isinstance(respuesta, str):
            return respuesta, None

        resp_lower = respuesta.lower()
        resp_clean = re.sub(r"[*_~`#]", "", resp_lower)

        # 1. ¿Pregunta de confirmación final de pedido? -> 3 Botones (Confirmar / Modificar / Cancelar)
        # Solo si es el resumen formal del pedido (PASO 6), NO una pregunta intermedia de dirección, teléfono u horario.
        es_resumen_pedido = any(k in resp_lower for k in [
            "resumen de tu pedido", "datos de tu pedido", "detalles de tu pedido", "información de tu pedido",
            "informacion de tu pedido", "tu pedido sería", "tu pedido seria", "tu pedido es:", "resumen completo",
            "resumen de la orden", "datos del pedido", "detalles del pedido"
        ]) and ("total:" in resp_lower or "$" in resp_lower)

        es_pregunta_confirmacion = es_resumen_pedido and (
            any(k in resp_lower for k in [
                "confirmar", "confírmame", "confirmame", "correctos", "proceder", "procesar",
                "procedo", "de acuerdo", "¿está todo bien", "¿esta todo bien", "¿es correcto",
                "¿son correctos", "¿deseas confirmar", "¿deseas que proceda", "¿confirmamos tu pedido",
                "¿deseas que registremos", "¿está todo correcto", "¿está correcta la información"
            ])
            or (("confirmar" in resp_lower or "confirmas" in resp_lower) and "?" in resp_lower)
        )
        if es_pregunta_confirmacion:
            cleaned = self.clean_text_for_interactive(respuesta, "buttons", "confirmation")
            return cleaned, {
                "type": "buttons",
                "buttons": self.get_confirmation_buttons(),
            }

        # 1.5. ¿Es confirmación de cancelación de pedido?
        if any(k in resp_lower for k in ["confirmación de cancelación", "confirmacion de cancelacion", "¿estás seguro de que deseas cancelar", "seguro de que deseas cancelar"]):
            match_order = re.search(r"(?:pedido|folio)\s*#?\s*(\d+)", respuesta, re.IGNORECASE)
            if match_order:
                return respuesta, {
                    "type": "buttons",
                    "buttons": self.get_order_cancel_confirm_buttons(match_order.group(1)),
                }

        # 1.8. GUARD: Solicitud de registro de nuevo usuario, nombre, dirección o teléfono celular -> NINGÚN BOTÓN
        es_registro_o_datos_personales = any(k in resp_lower for k in [
            "nombre completo", "cuál es tu nombre", "cual es tu nombre", "para registrar tu cuenta",
            "primer pedido con este número", "primer pedido con este numero", "tu nombre para registrar",
            "cómo te llamas", "como te llamas", "indícame tu nombre", "indicame tu nombre",
            "indícame tu dirección", "indicame tu direccion", "cuál es tu dirección", "cual es tu direccion",
            "ingresa tu dirección", "ingresa tu direccion", "número celular", "numero celular",
            "10 dígitos", "10 digitos", "compárteme tu número", "comparteme tu numero", "para buscar tu cuenta"
        ])
        if es_registro_o_datos_personales:
            return respuesta, None

        # 2. GUARD: ¿Es mensaje de éxito de pedido confirmado, recibo final, asignación o consulta de historial/estatus de pedidos?
        es_recibo_confirmado = (
            bool(re.search(r"pedido\s*#?\d+\s*(confirmado|agendado)", resp_clean))
            or bool(re.search(r"(confirmado|agendado)!\s*", resp_clean) and "total:" in resp_clean)
            or any(k in resp_lower for k in [
                "estamos asignando tu unidad", "el operador está preparando tu unidad",
                "ha sido asignado", "¡tu pedido está confirmado", "tu pedido ha sido registrado",
                "pedido confirmado", "registrado con éxito", "registrado exitosamente"
            ])
            or (
                any(k in resp_lower for k in ["folio #", "folio:"])
                and any(k in resp_lower for k in ["total:", "dirección:", "direccion:", "repartidor", "torre de control"])
            )
        )
        if es_recibo_confirmado:
            match_order = re.search(r"(?:pedido|folio)\s*#?\s*(\d+)", respuesta, re.IGNORECASE)
            is_terminal = any(k in resp_lower for k in ["cancelado", "entregado", "finalizado"])
            if match_order and not is_terminal:
                order_id = match_order.group(1)
                return respuesta, {
                    "type": "buttons",
                    "buttons": self.get_order_active_buttons(order_id),
                }
            return respuesta, None
        es_consulta_o_historial_pedidos = (
            any(k in resp_lower for k in [
                "historial de tus pedidos", "encontré", "encontre", "pedidos en tu historial",
                "información de tu pedido", "informacion de tu pedido", "estatus de tu pedido",
                "se encontraron", "tus pedidos registrados", "detalles de tu pedido"
            ])
            and any(k in resp_lower for k in ["pedido #", "folio #", "pedidos", "pedido(s)"])
        ) or (
            "pedido #" in resp_lower and any(k in resp_lower for k in ["estado:", "confirmado", "entregado", "en ruta", "cancelado"])
            and not any(k in resp_lower for k in ["¿deseas confirmar", "¿confirmamos", "resumen de tu pedido"])
        )

        if es_consulta_o_historial_pedidos:
            match_order = re.search(r"(?:pedido|folio)\s*#?\s*(\d+)", respuesta, re.IGNORECASE)
            if match_order:
                order_id = match_order.group(1)
                es_inactivo = any(k in resp_lower for k in ["cancelado", "entregado", "finalizado"])
                es_activo = any(k in resp_lower for k in ["confirmado", "en camino", "en ruta", "agendado", "programado", "asignado"])
                if es_activo and not es_inactivo:
                    return respuesta, {
                        "type": "buttons",
                        "buttons": self.get_order_active_buttons(order_id),
                    }
            return respuesta, None

        # 3. ¿Pregunta por método de pago? (Efectivo vs Terminal) -> 2 Botones
        es_recibo_pago = any(k in resp_lower for k in ["método de pago:", "metodo de pago:", "pago con:", "forma de pago:"])
        if es_recibo_pago or es_consulta_o_historial_pedidos:
            es_pregunta_pago = False
        else:
            es_pregunta_pago = (
                any(k in resp_lower for k in [
                    "cómo prefieres realizar el pago", "como prefieres realizar el pago",
                    "cómo deseas realizar el pago", "como deseas realizar el pago",
                    "cómo deseas pagar", "como deseas pagar",
                    "cómo prefieres pagar", "como prefieres pagar",
                    "cómo te gustaría pagar", "como te gustaria pagar",
                    "cuál será tu forma de pago", "cual sera tu forma de pago",
                    "en efectivo o con terminal", "en efectivo o terminal",
                    "efectivo o tarjeta", "efectivo o con tarjeta",
                    "pagarás en efectivo", "pagaras en efectivo",
                    "deseas pagar en efectivo", "forma de pago será", "forma de pago sera",
                    "cuál de las dos opciones prefieres", "cual de las dos opciones prefieres",
                ])
                or (
                    ("efectivo" in resp_lower and ("terminal" in resp_lower or "tarjeta" in resp_lower))
                    and any(k in resp_lower for k in ["¿cómo", "¿como", "¿cuál", "¿cual", "¿deseas", "prefieres", "¿pagar"])
                    and not any(k in resp_lower for k in ["pedido #", "folio #", "historial"])
                )
            )

        if es_pregunta_pago:
            cleaned = self.clean_text_for_interactive(respuesta, "buttons", "payment")
            return cleaned, {
                "type": "buttons",
                "buttons": self.get_payment_method_buttons(),
            }

        # Normalizar texto para matching confiable (sin asteriscos ni markdown)
        resp_clean = re.sub(r"[*_~`#]", "", resp_lower)

        # 4. GUARD ESTRICTO DE HORARIO/FECHA O TELÉFONO O CONFIRMACIÓN DE DIRECCIÓN O SOLICITUD DE ESCRITURA DE DIRECCIÓN -> NO botones
        es_pregunta_horario_o_fecha = any(k in resp_clean for k in [
            "qué día", "que dia", "día y hora", "dia y hora", "a qué hora", "a que hora",
            "cuándo deseas recibir", "cuando deseas recibir", "cuándo deseas que", "cuando deseas que",
            "cuándo prefieres recibir", "cuando prefieres recibir", "cuándo te gustaría recibir",
            "cuando te gustaria recibir", "fecha y horario", "fecha de entrega", "horario de entrega",
            "programar tu entrega", "programar la entrega", "programar tu horario", "programar la fecha",
            "en qué horario", "en que horario", "lo antes posible o programar", "para hoy o para mañana"
        ])
        es_pregunta_telefono = any(k in resp_clean for k in [
            "proporcionarme tu número", "proporcionarme tu numero",
            "proporcionar tu número", "proporcionar tu numero",
            "proporcionas tu número", "proporcionas tu numero",
            "me podrías proporcionar tu número", "me podrias proporcionar tu numero",
            "me puedes proporcionar tu número", "me puedes proporcionar tu numero",
            "cuál es tu número", "cual es tu numero",
            "cuál es tu teléfono", "cual es tu telefono",
            "cuál es tu celular", "cual es tu celular",
            "proporcionarme tu teléfono", "proporcionarme tu telefono",
            "proporcionar tu teléfono", "proporcionar tu telefono",
            "proporcionarme tu celular", "proporcionarme tu celular",
            "proporcionar tu celular", "proporcionar tu celular",
            "indicarme tu número", "indicarme tu numero",
            "indicarme tu teléfono", "indicarme tu telefono",
            "indicarme tu celular", "indicarme tu celular",
            "tu número de teléfono para buscar", "tu numero de telefono para buscar",
            "tu número de celular para buscar", "tu numero de celular para buscar",
            "para buscar tu cuenta en nuestro sistema", "para buscar tu cuenta"
        ])
        es_confirmacion_direccion_exitosa = any(k in resp_clean for k in [
            "dirección de entrega queda confirmada", "direccion de entrega queda confirmada",
            "dirección queda confirmada", "direccion queda confirmada",
            "dirección confirmada", "direccion confirmada", "ubicación confirmada", "ubicacion confirmada",
            "domicilio confirmado", "punto de entrega confirmado",
            "registré tu nueva dirección", "registre tu nueva direccion",
            "registrada tu nueva dirección", "registrada tu nueva direccion",
            "guardé tu nueva dirección", "guarde tu nueva direccion",
            "quedó registrada tu dirección", "quedo registrada tu direccion",
            "dirección ha sido registrada", "direccion ha sido registrada",
            "dirección guardada con éxito", "direccion guardada con exito"
        ])
        es_solicitud_escritura_nueva_direccion = (
            any(k in resp_clean for k in [
                "indícame tu nueva dirección", "indicame tu nueva direccion",
                "indícame la nueva dirección", "indicame la nueva direccion",
                "indícame una nueva dirección", "indicame una nueva direccion",
                "indicarme una nueva dirección", "indicarmela una nueva direccion",
                "proporciona los datos de tu nueva dirección", "proporciona los datos de tu nueva direccion",
                "proporciona tu nueva dirección", "proporciona tu nueva direccion",
                "proporcióname tu nueva dirección", "proporcioname tu nueva direccion",
                "proporcióname los datos de tu nueva dirección", "proporcioname los datos de tu nueva direccion",
                "escribe tu nueva dirección", "escribe tu nueva direccion",
                "escribe tu dirección", "escribe tu direccion",
                "ingresa tu nueva dirección", "ingresa tu nueva direccion",
                "ingresa tu dirección", "ingresa tu direccion",
                "compárteme tu nueva dirección", "comparteme tu nueva direccion",
                "compárteme tu dirección", "comparteme tu direccion",
                "comparte tu nueva dirección", "comparte tu nueva direccion",
                "comparte tu ubicación o escribe", "comparte tu ubicacion o escribe",
                "calle, número", "calle, numero", "calle y número", "calle y numero",
                "colonia y referencias", "número exterior", "numero exterior",
                "indícame la dirección completa", "indicame la direccion completa",
                "indícame tu dirección completa", "indicame tu direccion completa",
                "cuál es tu dirección completa", "cual es tu direccion completa",
                "por favor compárteme tu ubicación", "por favor comparteme tu ubicacion",
                "por favor indícame la calle", "por favor indicame la calle",
                "para registrarla en tu pedido", "para registrarla en el sistema",
                "cuál es la nueva dirección", "cual es la nueva direccion"
            ])
            and not any(k in resp_clean for k in [
                "botones interactivos", "seleccionar tu dirección", "seleccionar tu direccion",
                "selecciona tu dirección", "selecciona tu direccion", "a cuál de tus direcciones", "cual de tus direcciones"
            ])
        )

        es_propuesta_horario_alternativo = any(k in resp_clean for k in [
            "próximo horario disponible", "proximo horario disponible",
            "siguiente horario disponible",
            "horario alternativo",
            "no tenemos disponibilidad para",
            "horario se encuentra lleno", "horario está lleno", "horario esta lleno",
            "cupo lleno", "cupo completo",
            "¿te gustaría agendarlo a esa hora", "¿te gustaria agendarlo a esa hora",
            "¿te gustaría esa hora", "¿te gustaria esa hora",
            "¿te parece bien ese horario", "¿te parece bien a esa hora",
            "o prefieres otro horario", "o prefieres otra hora",
        ])
        if es_propuesta_horario_alternativo:
            return respuesta, {
                "type": "buttons",
                "buttons": self.get_schedule_alternative_buttons(),
            }

        if es_pregunta_telefono or es_confirmacion_direccion_exitosa or es_solicitud_escritura_nueva_direccion:
            return respuesta, None

        if es_pregunta_horario_o_fecha:
            if not any(k in resp_clean for k in ["indícame la hora", "indicame la hora", "escribe la hora", "hora y el día", "hora y el dia"]):
                cleaned = self.clean_text_for_interactive(respuesta, "buttons", "schedule")
                return cleaned, {
                    "type": "buttons",
                    "buttons": self.get_schedule_buttons(),
                }
            return respuesta, None

        # 5. ¿Pregunta por direcciones registradas? -> Botones Quick Reply o Lista Interactiva
        es_pregunta_direccion = not es_pregunta_horario_o_fecha and not es_confirmacion_direccion_exitosa and not es_solicitud_escritura_nueva_direccion and any(k in resp_clean for k in [
            "dirección registrada", "direccion registrada", "direcciones registradas",
            "direcciones guardadas", "dirección guardada", "direccion guardada",
            "dirección(es) guardadas", "direccion(es) guardadas", "dirección(es)", "direccion(es)",
            "domicilio registrado", "domicilios registrados", "domicilio guardado", "domicilios guardados",
            "siguientes direcciones", "direcciones para ti",
            "seleccionar tu dirección", "seleccionar tu direccion",
            "selecciona tu dirección", "selecciona tu direccion",
            "seleccionar dirección", "seleccionar direccion",
            "selecciona dirección", "selecciona direccion",
            "seleccionar tu domicilio", "seleccionar domicilio", "selecciona tu domicilio",
            "botones interactivos", "botones interactivos de la pantalla", "botones de la pantalla",
            "a cuál de tus direcciones", "cual de tus direcciones",
            "a cuál de estas direcciones", "cual de estas direcciones",
            "a cuál de tus", "a cual de tus",
            "a cuál de ellas", "a cual de ellas",
            "a cuál de esas direcciones", "cual de esas direcciones",
            "misma dirección", "misma direccion",
            "deseas que entreguemos en", "deseas que enviemos a",
            "deseas que te lo enviemos a", "deseas que te la enviemos a",
            "deseas que enviemos tu pedido", "enviemos tu pedido o prefieres ingresar una nueva",
            "deseas recibir tu pedido en", "deseas recibirlo en",
            "prefieres proporcionar una nueva dirección", "prefieres proporcionar una nueva direccion",
            "ingresar una nueva dirección", "ingresar una nueva direccion", "prefieres ingresar una nueva",
            "proporcionar una nueva dirección", "proporcionar una nueva direccion",
            "cuál de tus domicilios", "cual de tus domicilios",
            "en cuál de tus direcciones", "en cual de tus direcciones",
            "cliente frecuente",
        ])
        if es_pregunta_direccion:
            # 1. Extraer PRIMERO las direcciones numeradas del propio mensaje generado por el asistente
            # Esto asegura que si el pedido es para otro número de teléfono, se muestren las direcciones de ESE cliente
            addrs = self.extract_addresses_from_text(respuesta)

            # 2. Si no venían numeradas en el texto de la respuesta, consultar la base de datos
            if not addrs:
                repo = get_repository()
                cust = None

                # Estrategia A: Teléfono de 10 dígitos en el mensaje que envió el usuario
                if user_text:
                    m_user_phone = re.search(r"\b(\d{10})\b", user_text)
                    if m_user_phone:
                        cust = repo.get_customer_by_phone(tenant_id, m_user_phone.group(1))

                # Estrategia B: Teléfono de 10 dígitos en la respuesta del asistente
                if not cust:
                    m_resp_phone = re.search(r"\b(\d{10})\b", respuesta)
                    if m_resp_phone:
                        cust = repo.get_customer_by_phone(tenant_id, m_resp_phone.group(1))

                # Estrategia C: Teléfono pasado por parámetro (ej. de wa_id o normalizado)
                if not cust and phone:
                    cust = repo.get_customer_by_phone(tenant_id, phone)

                # Estrategia E: channel_user_id (wa_id en customers)
                if not cust and not addrs and not phone and channel_user_id:
                    cust = repo.get_customer(tenant_id, "whatsapp", channel_user_id)

                if cust and not addrs:
                    if cust.addresses:
                        addrs = list(cust.addresses)
                    elif cust.address:
                        addrs = [CustomerAddress(id=1, address=cust.address, alias="Principal")]

            if addrs:
                # Si es exactamente 1 dirección, generar 3 botones Quick Reply (1. Dir, 2. Nueva, 3. Eliminar)
                if len(addrs) == 1:
                    buttons = self.get_customer_addresses_buttons(addrs)
                    cleaned = self.clean_text_for_interactive(respuesta, "buttons", "addresses")
                    return cleaned, {
                        "type": "buttons",
                        "buttons": buttons,
                    }
                else:
                    sections = self.get_customer_addresses_list_sections(addrs)
                    cleaned = self.clean_text_for_interactive(respuesta, "list", "addresses")
                    return cleaned, {
                        "type": "list",
                        "button_label": "Ver Direcciones",
                        "sections": sections,
                    }

        # 6. ¿Pregunta por tipo de servicio inicial (Cilindro vs Estacionario)? -> 2 Botones
        es_pregunta_servicio = (
            (("cilindro" in resp_lower and "estacionario" in resp_lower)
             and any(k in resp_lower for k in ["¿qué", "¿que", "¿cuál", "¿cual", "deseas", "necesitas", "tipo de servicio", " o "]))
            or any(k in resp_lower for k in [
                "¿qué necesitas el día de hoy", "¿que necesitas el dia de hoy",
                "¿qué tipo de servicio", "¿que tipo de servicio",
                "¿qué necesitas hoy", "¿que necesitas hoy",
                "para comenzar, ¿qué necesitas", "para comenzar, ¿que necesitas",
                "para comenzar ¿qué necesitas", "para comenzar ¿que necesitas",
                "cilindro o tanque estacionario", "cilindro o estacionario",
                "tanque estacionario o cilindro"
            ])
        )
        if es_pregunta_servicio:
            cleaned = self.clean_text_for_interactive(respuesta, "buttons", "service")
            return cleaned, {
                "type": "buttons",
                "buttons": self.get_service_type_buttons(),
            }

        # 7. ¿Catálogo de cilindros / selección de capacidad? -> Lista Interactiva (ÚNICAMENTE si ya se eligió Cilindro)
        repo_chk = get_repository()
        db_prods = repo_chk.get_all_products(tenant_id)
        db_kg_keywords = [f"{m.group(1)} kg" for p in db_prods if bool(getattr(p, "in_stock", True)) and (m := re.search(r"(\d+)\s*kg", p.name, re.IGNORECASE))]
        es_tema_cilindro = any(k in resp_lower for k in ["cilindro", "cilindros"]) or any(k in resp_lower for k in db_kg_keywords)
        es_pregunta_catalogo = any(k in resp_lower for k in [
            "qué capacidad", "que capacidad", "cuántos kilos", "cuantos kilos",
            "opciones disponibles", "catálogo", "catalogo", "cuál de estos", "cual de estos",
            "qué tamaño", "que tamaño", "selecciona el cilindro", "capacidad de tu cilindro"
        ])
        if es_tema_cilindro and es_pregunta_catalogo and not es_pregunta_servicio:
            sections = self.get_cylinder_catalog_list_sections(tenant_id)
            cleaned = self.clean_text_for_interactive(respuesta, "list", "catalog")
            return cleaned, {
                "type": "list",
                "button_label": "Ver Catálogo",
                "sections": sections,
            }

        return respuesta, None
