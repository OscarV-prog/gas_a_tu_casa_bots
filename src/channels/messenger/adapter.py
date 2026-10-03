"""Facebook Messenger Adapter (Meta Graph API).

Translates incoming Meta Messenger webhooks into InboundMessage protocol objects
and dispatches outbound messages, quick replies, carousels, and templates.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from src.channels.base import ChannelAdapter
from src.config.settings import get_settings
from src.models.customer import CustomerAddress
from src.models.message import InboundMessage, OutboundMessage
from src.repositories import get_repository
from src.services.geocoding import resolve_gps_address_to_name

logger = logging.getLogger(__name__)


class MessengerAdapter(ChannelAdapter):
    """Enterprise Adapter for Facebook Messenger (Meta Graph API)."""

    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def api_version(self) -> str:
        return self.settings.messenger_api_version or "v21.0"

    @property
    def access_token(self) -> str:
        return (
            self.settings.messenger_page_access_token
            or self.settings.whatsapp_token  # Fallback to shared Meta access token if present
        )

    @property
    def verify_token(self) -> str:
        return self.settings.messenger_verify_token or "petroil_gas_webhook_secret"

    @property
    def is_configured(self) -> bool:
        return bool(self.access_token)

    @property
    def base_url(self) -> str:
        return f"https://graph.facebook.com/{self.api_version}/me/messages"

    def _get_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    async def _post_meta(self, client: httpx.AsyncClient, url: str, payload: dict[str, Any]) -> httpx.Response:
        """Post to Meta Graph API with automatic 401 token invalidation and single retry."""
        resp = await client.post(url, headers=self._get_headers(), json=payload)
        if resp.status_code == 401:
            logger.warning("[Messenger] Meta API returned 401 Unauthorized. Invalidating dynamic settings cache and refreshing...")
            from src.services.dynamic_settings import invalidate_dynamic_settings_cache, fetch_remote_settings
            invalidate_dynamic_settings_cache()
            fetch_remote_settings(force_refresh=True)
            resp = await client.post(url, headers=self._get_headers(), json=payload)
        return resp

    async def _get_meta(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        """Get from Meta Graph API with automatic 401 token invalidation and single retry."""
        resp = await client.get(url, headers=self._get_headers())
        if resp.status_code == 401:
            logger.warning("[Messenger] Meta API returned 401 Unauthorized. Invalidating dynamic settings cache and refreshing...")
            from src.services.dynamic_settings import invalidate_dynamic_settings_cache, fetch_remote_settings
            invalidate_dynamic_settings_cache()
            fetch_remote_settings(force_refresh=True)
            resp = await client.get(url, headers=self._get_headers())
        return resp

    # -------------------------------------------------------------------------
    # Inbound Webhook Parsing
    # -------------------------------------------------------------------------

    def parse_webhook_events(self, raw: dict[str, Any], default_tenant_id: str = "petroil") -> list[dict[str, Any]]:
        """Parse raw Messenger webhook payload into normalized message events.
        
        Handles:
        - Text messages
        - Quick reply button responses
        - Postback button responses
        - GPS location attachments
        - Voice notes / audio attachments
        - Image attachments
        - Filters out echo messages (sent by page) and read/delivery receipts.
        """
        parsed_events: list[dict[str, Any]] = []
        if not raw or not isinstance(raw, dict):
            return parsed_events

        # Messenger payloads are structured as: {"object": "page", "entry": [{"id": ..., "messaging": [...]}]}
        entries = raw.get("entry", [])
        if not isinstance(entries, list):
            return parsed_events

        for entry in entries:
            messaging_list = entry.get("messaging", [])
            for event_data in messaging_list:
                # 1. Ignorar ecos de mensajes enviados por el bot/página
                msg = event_data.get("message", {})
                if msg.get("is_echo"):
                    continue

                # 2. Ignorar confirmaciones de entrega o lectura
                if "delivery" in event_data or "read" in event_data:
                    continue

                sender = event_data.get("sender", {})
                psid = str(sender.get("id", "")).strip()
                if not psid:
                    continue

                mid = msg.get("mid", f"mid_{int(datetime.now().timestamp())}")
                timestamp = str(event_data.get("timestamp", ""))

                event: dict[str, Any] = {
                    "msg_id": mid,
                    "psid": psid,
                    "channel_user_id": psid,
                    "name": "Cliente Messenger",
                    "timestamp": timestamp,
                    "type": "text",
                    "tenant_id": default_tenant_id,
                    "text": "",
                    "location": None,
                    "interactive_id": None,
                    "interactive_title": None,
                    "media_url": None,
                    "raw": event_data,
                }

                # Quick Reply response
                quick_reply = msg.get("quick_reply", {})
                if quick_reply and quick_reply.get("payload"):
                    event["interactive_id"] = quick_reply.get("payload")
                    event["interactive_title"] = msg.get("text", "")
                    event["text"] = quick_reply.get("payload")
                    parsed_events.append(event)
                    continue

                # Postback Button response
                postback = event_data.get("postback", {})
                if postback and postback.get("payload"):
                    event["interactive_id"] = postback.get("payload")
                    event["interactive_title"] = postback.get("title", "")
                    event["text"] = postback.get("payload")
                    parsed_events.append(event)
                    continue

                # Attachments: location, audio, image
                attachments = msg.get("attachments", [])
                if attachments and isinstance(attachments, list):
                    first_att = attachments[0]
                    att_type = first_att.get("type", "")
                    att_payload = first_att.get("payload", {})

                    if att_type == "location":
                        coords = att_payload.get("coordinates", {})
                        if coords.get("lat") is not None and coords.get("long") is not None:
                            event["type"] = "location"
                            event["location"] = {
                                "latitude": float(coords["lat"]),
                                "longitude": float(coords["long"]),
                                "name": "Ubicación compartida por Messenger",
                                "address": "",
                            }
                            parsed_events.append(event)
                            continue

                    elif att_type == "audio":
                        event["type"] = "audio"
                        event["media_url"] = att_payload.get("url")
                        event["text"] = "[Nota de voz recibida]"
                        parsed_events.append(event)
                        continue

                    elif att_type == "image":
                        event["type"] = "image"
                        event["media_url"] = att_payload.get("url")
                        event["text"] = msg.get("text", "") or "[Imagen enviada por el cliente]"
                        parsed_events.append(event)
                        continue

                # Plain Text Message
                if msg.get("text"):
                    event["type"] = "text"
                    event["text"] = str(msg.get("text", "")).strip()
                    parsed_events.append(event)

        return parsed_events

    def parse_webhook(self, raw: dict[str, Any]) -> InboundMessage:
        """Parse webhook into a single InboundMessage object."""
        events = self.parse_webhook_events(raw)
        if not events:
            return InboundMessage(
                channel="messenger",
                channel_message_id="empty-msg-id",
                channel_user_id="anonymous",
                tenant_id="petroil",
                text="",
                received_at=datetime.now(timezone.utc),
                raw_payload=raw,
            )

        ev = events[0]
        return InboundMessage(
            channel="messenger",
            channel_message_id=ev["msg_id"],
            channel_user_id=ev["psid"],
            tenant_id=ev["tenant_id"],
            text=ev["text"],
            received_at=datetime.now(timezone.utc),
            raw_payload=raw,
        )

    # -------------------------------------------------------------------------
    # Outbound Message Senders (Meta Send API)
    # -------------------------------------------------------------------------

    async def send_sender_action(self, recipient_psid: str, action: str = "typing_on") -> bool:
        """Send a sender action: 'mark_seen', 'typing_on', or 'typing_off'."""
        if not self.is_configured or not recipient_psid:
            return False

        payload = {
            "recipient": {"id": str(recipient_psid).strip()},
            "sender_action": action,
        }

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await self._post_meta(client, self.base_url, payload)
                return resp.status_code in (200, 201, 202)
        except Exception as e:
            logger.debug(f"[Messenger] sender_action error ({action}): {e}")
            return False

    async def send_text_message(self, recipient_psid: str, text: str) -> bool:
        """Send a plain or markdown-formatted text message to a Messenger user."""
        if not self.is_configured:
            logger.warning(f"[Messenger] Cannot send text to {recipient_psid}: credentials not configured.")
            return False

        if not text or not str(text).strip():
            return False

        psid = str(recipient_psid).strip()
        max_len = 1950  # Messenger text limit is 2000 chars

        # Chunk text if it exceeds Messenger limits
        chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)]
        success = True

        async with httpx.AsyncClient(timeout=15.0) as client:
            for chunk in chunks:
                payload = {
                    "recipient": {"id": psid},
                    "messaging_type": "RESPONSE",
                    "message": {"text": chunk},
                }

                try:
                    resp = await self._post_meta(client, self.base_url, payload)
                    if resp.status_code not in (200, 201, 202):
                        logger.error(f"[Messenger] HTTP {resp.status_code} error sending to {psid}: {resp.text}")
                        success = False
                except Exception as e:
                    logger.error(f"[Messenger] Exception sending text to {psid}: {e}")
                    success = False

        return success

    async def send_quick_replies(
        self,
        recipient_psid: str,
        text: str,
        quick_replies: list[dict[str, str]],
    ) -> bool:
        """Send Quick Reply interactive buttons (up to 13 buttons)."""
        if not self.is_configured:
            logger.warning(f"[Messenger] Cannot send quick replies to {recipient_psid}: credentials missing.")
            return False

        if not quick_replies or not text:
            return False

        psid = str(recipient_psid).strip()
        # Max 13 quick replies in Messenger
        sliced_qr = quick_replies[:13]

        formatted_qr = []
        for qr in sliced_qr:
            title = qr.get("title", "Opción")[:20]
            payload_val = qr.get("payload", qr.get("id", "btn"))[:1000]
            formatted_qr.append({
                "content_type": "text",
                "title": title,
                "payload": payload_val,
            })

        body_payload = {
            "recipient": {"id": psid},
            "messaging_type": "RESPONSE",
            "message": {
                "text": text[:1950],
                "quick_replies": formatted_qr,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await self._post_meta(client, self.base_url, body_payload)
                if resp.status_code in (200, 201, 202):
                    return True
                logger.error(f"[Messenger] Error sending quick replies ({resp.status_code}): {resp.text}")
                return await self.send_text_message(psid, text)
        except Exception as e:
            logger.error(f"[Messenger] Exception sending quick replies to {psid}: {e}")
            return await self.send_text_message(psid, text)

    async def send_button_template(
        self,
        recipient_psid: str,
        text: str,
        buttons: list[dict[str, str]],
    ) -> bool:
        """Send a Button Template message (up to 3 buttons)."""
        if not self.is_configured:
            return False

        psid = str(recipient_psid).strip()
        sliced_btns = buttons[:3]

        formatted_buttons = []
        for b in sliced_btns:
            title = b.get("title", "Opción")[:20]
            b_type = str(b.get("type", "")).lower()
            if b_type == "web_url" or "url" in b:
                formatted_buttons.append({
                    "type": "web_url",
                    "title": title,
                    "url": b.get("url"),
                })
            else:
                payload_val = b.get("payload", b.get("id", "btn"))[:1000]
                formatted_buttons.append({
                    "type": "postback",
                    "title": title,
                    "payload": payload_val,
                })

        body_payload = {
            "recipient": {"id": psid},
            "messaging_type": "RESPONSE",
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "button",
                        "text": text[:640],
                        "buttons": formatted_buttons,
                    },
                },
            },
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await self._post_meta(client, self.base_url, body_payload)
                if resp.status_code in (200, 201, 202):
                    return True
                logger.error(f"[Messenger] Error sending button template ({resp.status_code}): {resp.text}")
                return await self.send_quick_replies(psid, text, buttons)
        except Exception as e:
            logger.error(f"[Messenger] Exception sending button template to {psid}: {e}")
            return await self.send_quick_replies(psid, text, buttons)

    async def send_generic_template(
        self,
        recipient_psid: str,
        elements: list[dict[str, Any]],
    ) -> bool:
        """Send a Generic Template Carousel / Cards message (up to 10 cards)."""
        if not self.is_configured or not elements:
            return False

        psid = str(recipient_psid).strip()
        sliced_elements = elements[:10]

        formatted_elements = []
        for el in sliced_elements:
            title = el.get("title", "Producto")[:80]
            subtitle = el.get("subtitle", "")[:80]
            image_url = el.get("image_url")
            raw_buttons = el.get("buttons", [])[:3]

            formatted_btns = []
            for b in raw_buttons:
                btn_title = b.get("title", "Seleccionar")[:20]
                btn_payload = b.get("payload", b.get("id", "btn"))[:1000]
                formatted_btns.append({
                    "type": "postback",
                    "title": btn_title,
                    "payload": btn_payload,
                })

            item_dict: dict[str, Any] = {
                "title": title,
                "subtitle": subtitle,
            }
            if image_url:
                item_dict["image_url"] = image_url
            if formatted_btns:
                item_dict["buttons"] = formatted_btns

            formatted_elements.append(item_dict)

        body_payload = {
            "recipient": {"id": psid},
            "messaging_type": "RESPONSE",
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "generic",
                        "elements": formatted_elements,
                    },
                },
            },
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await self._post_meta(client, self.base_url, body_payload)
                if resp.status_code in (200, 201, 202):
                    return True
                logger.error(f"[Messenger] Error sending generic template ({resp.status_code}): {resp.text}")
                return False
        except Exception as e:
            logger.error(f"[Messenger] Exception sending generic template to {psid}: {e}")
            return False

    async def get_user_profile(self, recipient_psid: str) -> dict[str, str]:
        """Fetch user's public profile from Meta Graph API (first_name, last_name, profile_pic)."""
        if not self.is_configured or not recipient_psid:
            return {}

        url = f"https://graph.facebook.com/{self.api_version}/{recipient_psid}?fields=first_name,last_name,profile_pic"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await self._get_meta(client, url)
                if resp.status_code == 200:
                    return resp.json()
        except Exception as e:
            logger.debug(f"[Messenger] Could not fetch profile for {recipient_psid}: {e}")
        return {}

    async def download_media(self, media_url: str, dest_path: Path) -> Path | None:
        """Download media file (voice note or image) from Messenger attachment URL."""
        if not media_url:
            return None
        try:
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                resp = await client.get(media_url)
                if resp.status_code == 200:
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(dest_path, "wb") as f:
                        f.write(resp.content)
                    return dest_path
        except Exception as e:
            logger.error(f"[Messenger] Error downloading media from {media_url}: {e}")
        return None

    # -------------------------------------------------------------------------
    # ChannelAdapter Protocol Implementation
    # -------------------------------------------------------------------------

    async def send_reply(self, channel_user_id: str, message: OutboundMessage) -> None:
        """Protocol bridge to send outbound messages."""
        if message.text:
            await self.send_text_message(channel_user_id, message.text)

    # -------------------------------------------------------------------------
    # Interactive UI Builders (Catalog, Services, Addresses, Schedules, Payments)
    # -------------------------------------------------------------------------

    def get_service_quick_replies(self) -> list[dict[str, str]]:
        """Quick replies for initial service selection."""
        return [
            {"id": "client_svc:cilindro", "title": "🛻 Cilindro de Gas"},
            {"id": "client_svc:estacionario", "title": "🚛 Estacionario"},
        ]

    def get_cylinder_catalog_elements(self, tenant_id: str = "petroil", include_buttons: bool = True) -> list[dict[str, Any]]:
        """Carousel elements of cylinder products for Messenger Generic Template."""
        repo = get_repository()
        prods = repo.get_all_products(tenant_id)
        cylinders = [p for p in prods if "cilindro" in p.id.lower() or "cilindro" in p.name.lower()]
        if not cylinders:
            cylinders = prods[:4]

        # Imágenes representativas de alta calidad para cilindros de gas
        img_map = {
            "10": "https://images.unsplash.com/photo-1585776245991-cf89dd7fc73a?w=600&auto=format&fit=crop&q=80",
            "20": "https://images.unsplash.com/photo-1585776245991-cf89dd7fc73a?w=600&auto=format&fit=crop&q=80",
            "30": "https://images.unsplash.com/photo-1585776245991-cf89dd7fc73a?w=600&auto=format&fit=crop&q=80",
            "45": "https://images.unsplash.com/photo-1585776245991-cf89dd7fc73a?w=600&auto=format&fit=crop&q=80",
        }

        elements = []
        for p in cylinders:
            cap_match = re.search(r"(\d+)\s*kg", p.name, re.I)
            cap_str = cap_match.group(1) if cap_match else "30"
            img_url = img_map.get(cap_str, img_map["30"])

            item_dict: dict[str, Any] = {
                "title": f"🛻 {p.name}",
                "subtitle": f"${p.price:,.2f} {p.currency} • Entrega express con sello garantizado",
                "image_url": img_url,
                "buttons": [
                    {"id": f"cart_add:{p.id}:1", "title": "🛒 Comprar"},
                ],
            }
            elements.append(item_dict)
        return elements

    def get_cylinder_quick_replies(self, tenant_id: str = "petroil") -> list[dict[str, str]]:
        """Quick reply buttons for quick cylinder capacity selection."""
        repo = get_repository()
        prods = repo.get_all_products(tenant_id)
        cylinders = [p for p in prods if "cilindro" in p.id.lower() or "cilindro" in p.name.lower()]
        if not cylinders:
            cylinders = prods[:4]

        replies = []
        for p in cylinders:
            cap_match = re.search(r"(\d+)\s*kg", p.name, re.I)
            title = f"🛻 {cap_match.group(1)}kg (${int(p.price)})" if cap_match else f"🛻 {p.name[:12]}"
            replies.append({
                "id": f"cart_add:{p.id}:1",
                "title": title[:20],
            })
        return replies

    def get_cart_quick_replies(self, total_qty: int) -> list[dict[str, str]]:
        """Quick replies for interactive shopping cart operations."""
        btn_continue_title = f"✅ Continuar ({total_qty})" if len(f"✅ Continuar ({total_qty})") <= 20 else "✅ Continuar"
        return [
            {"id": "cart_more", "title": "➕ Agregar Otro"},
            {"id": "cart_checkout", "title": btn_continue_title},
            {"id": "cart_clear", "title": "🗑️ Vaciar Carrito"},
        ]

    def get_customer_addresses_buttons(self, addresses: list[CustomerAddress]) -> list[dict[str, str]]:
        """Postback buttons for Button Template (up to 3 buttons max in Messenger)."""
        buttons = []
        for i, addr in enumerate(addresses[:1], start=1):
            addr_text = resolve_gps_address_to_name(addr.address.strip()) if addr.address else ""
            addr_text = re.sub(r"^(?:\[(?:Nueva\s*Direcci[oó]n|Direcci[oó]n(?:\s*\d+)?|Principal)\]\s*)+", "", addr_text, flags=re.I).strip()
            calle = addr_text.split(",")[0].strip() if addr_text else "Domicilio"
            short = calle[:13] if len(calle) > 13 else calle
            title = f"📍 {i}. {short}"[:20]
            buttons.append({"id": f"client_addr:{i}", "title": title})
        buttons.append({"id": "client_addr:new", "title": "➕ Nueva Dirección"})
        if addresses:
            buttons.append({"id": "client_addr:del_menu", "title": "🗑️ Borrar Dirección"})
        return buttons

    def get_customer_addresses_quick_replies(self, addresses: list[CustomerAddress]) -> list[dict[str, str]]:
        """Quick replies for choosing from saved customer delivery addresses."""
        replies = []
        for i, addr in enumerate(addresses[:10], start=1):
            addr_text = resolve_gps_address_to_name(addr.address.strip()) if addr.address else ""
            addr_text = re.sub(r"^(?:\[(?:Nueva\s*Direcci[oó]n|Direcci[oó]n(?:\s*\d+)?|Principal)\]\s*)+", "", addr_text, flags=re.I).strip()
            calle = addr_text.split(",")[0].strip() if addr_text else "Domicilio"
            short = calle[:13] if len(calle) > 13 else calle
            title = f"📍 {i}. {short}"[:20]
            replies.append({"id": f"client_addr:{i}", "title": title})
        replies.append({"id": "client_addr:new", "title": "➕ Nueva Dirección"})
        if addresses:
            replies.append({"id": "client_addr:del_menu", "title": "🗑️ Borrar Dirección"})
        return replies

    def get_schedule_quick_replies(self) -> list[dict[str, str]]:
        """Quick replies for delivery schedule."""
        return [
            {"id": "client_sch:asap", "title": "⚡ Lo antes posible"},
            {"id": "client_sch:custom", "title": "📅 Programar horario"},
        ]

    def get_schedule_alternative_quick_replies(self) -> list[dict[str, str]]:
        """Quick replies when requested schedule is full and an alternative is suggested."""
        return [
            {"id": "client_sch:accept", "title": "✅ Aceptar horario"},
            {"id": "client_sch:custom", "title": "📅 Elegir otro"},
        ]

    def get_payment_method_quick_replies(self) -> list[dict[str, str]]:
        """Quick replies for payment method selection."""
        return [
            {"id": "client_pay:efectivo", "title": "💵 Efectivo"},
            {"id": "client_pay:terminal", "title": "💳 Terminal Tarjeta"},
        ]

    def get_confirmation_quick_replies(self) -> list[dict[str, str]]:
        """Quick replies for order confirmation summary."""
        return [
            {"id": "client_confirm:yes", "title": "✅ Confirmar Pedido"},
            {"id": "client_confirm:edit", "title": "✏️ Modificar"},
            {"id": "client_confirm:cancel", "title": "❌ Cancelar"},
        ]

    def get_edit_options_quick_replies(self) -> list[dict[str, str]]:
        """Quick replies for editing draft order fields."""
        return [
            {"id": "client_edit:schedule", "title": "⏰ Horario"},
            {"id": "client_edit:address", "title": "📍 Dirección"},
            {"id": "client_edit:payment", "title": "💳 Forma de Pago"},
            {"id": "client_edit:product", "title": "📦 Producto"},
            {"id": "client_edit:phone", "title": "📱 Teléfono"},
            {"id": "client_edit:back", "title": "🔙 Volver"},
        ]

    def get_order_active_quick_replies(self, order_id: int | str) -> list[dict[str, str]]:
        """Quick replies for active/in-route order."""
        return [
            {"id": f"cancel_order_client:{order_id}", "title": "❌ Cancelar Pedido"},
        ]

    def get_order_cancel_confirm_quick_replies(self, order_id: int | str) -> list[dict[str, str]]:
        """Confirmation buttons before cancelling an order."""
        return [
            {"id": f"confirm_cancel_order_client:{order_id}", "title": "⚠️ Sí, Cancelar"},
            {"id": f"keep_order_client:{order_id}", "title": "🔙 No, Conservar"},
        ]

    def get_rating_quick_replies(self, order_id: int | str) -> list[dict[str, str]]:
        """Quick replies for post-delivery CSAT satisfaction rating."""
        return [
            {"id": f"rate:{order_id}:5", "title": "⭐⭐⭐⭐⭐ Excelente"},
            {"id": f"rate:{order_id}:4", "title": "⭐⭐⭐⭐ Muy Bueno"},
            {"id": f"rate:{order_id}:3", "title": "⭐⭐⭐ Regular"},
            {"id": f"rate:{order_id}:2", "title": "⭐⭐ Malo"},
            {"id": f"rate:{order_id}:1", "title": "⭐ Muy Malo"},
        ]

    def get_rating_feedback_quick_replies(self, order_id: int | str, stars: int) -> list[dict[str, str]]:
        """Quick replies for rating feedback tags."""
        if stars >= 4:
            return [
                {"id": f"rate_tag:{order_id}:Rapidez", "title": "⚡ Rapidez"},
                {"id": f"rate_tag:{order_id}:Amabilidad", "title": "😊 Trato amable"},
                {"id": f"rate_tag:{order_id}:Seguridad", "title": "🛡️ Seguridad"},
                {"id": f"rate_tag:{order_id}:Impecable", "title": "✨ Impecable"},
                {"id": f"rate_tag:{order_id}:Omitido", "title": "⏩ Finalizar"},
            ]
        else:
            return [
                {"id": f"rate_tag:{order_id}:Demora", "title": "⏳ Demora entrega"},
                {"id": f"rate_tag:{order_id}:Actitud", "title": "🙁 Actitud chofer"},
                {"id": f"rate_tag:{order_id}:Cilindro", "title": "📦 Problema cilindro"},
                {"id": f"rate_tag:{order_id}:Cobro", "title": "💵 Cobro o cambio"},
                {"id": f"rate_tag:{order_id}:Omitido", "title": "⏩ Finalizar"},
            ]

    # -------------------------------------------------------------------------
    # Interactive UI Detection & Text Sanitization
    # -------------------------------------------------------------------------

    def clean_text_for_interactive(self, text: str, element_type: str, subtype: str = "") -> str:
        """Strip redundant lists or button prompts from text when sending interactive buttons."""
        if not text:
            return ""

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
                if not re.search(r"^\s*(?:[•\-\*▪🔹🔸\d\.\)]+)\s*(?:\*\*)?(?:⚡|📅)?\s*(?:lo antes posible|programar entrega|programar horario)", l.strip(), re.I)
            ]
            cleaned = "\n".join(filtered).strip()
            cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
            return cleaned or "¿Para qué día y horario deseas programar tu entrega?"

        return text

    def detect_interactive_elements(
        self,
        respuesta: str,
        psid: str = "",
        tenant_id: str = "petroil",
        user_text: str = "",
    ) -> tuple[str, dict[str, Any] | None]:
        """Detect conversational context and produce interactive Messenger UI elements.

        Returns (cleaned_text, interactive_spec) or (respuesta, None).
        """
        if not respuesta or not isinstance(respuesta, str):
            return respuesta, None

        resp_lower = respuesta.lower()
        resp_clean = re.sub(r"[*_~`#]", "", resp_lower)

        # 1. ¿Pregunta por tipo de servicio (cilindro vs estacionario)?
        es_pregunta_servicio = (
            any(k in resp_clean for k in [
                "cilindro o tanque estacionario", "cilindro o estacionario", "cilindro de gas o",
                "tanque estacionario o cilindro", "tipo de servicio necesitas", "tipo de servicio deseas",
                "gas estacionario o de cilindro", "¿cilindro o estacionario?", "servicio de cilindro o"
            ])
            and not any(k in resp_clean for k in ["confirmar", "resumen de tu pedido", "total a pagar", "folio"])
        )
        if es_pregunta_servicio:
            cleaned = self.clean_text_for_interactive(respuesta, "quick_replies", "service")
            return cleaned, {
                "type": "quick_replies",
                "quick_replies": self.get_service_quick_replies(),
            }

        # 2. ¿Confirmación final de pedido?
        es_confirmacion = any(k in resp_clean for k in [
            "¿confirmas tu pedido?", "confirmas tu pedido", "deseas confirmar tu pedido",
            "¿está todo correcto para proceder?", "esta todo correcto para proceder",
            "para proceder con el envío", "para proceder con el envio", "para agendarlo",
            "resumen de tu pedido:", "resumen de tu pedido", "detalles de tu pedido"
        ]) and any(k in resp_clean for k in ["total", "dirección", "direccion", "pago"])
        if es_confirmacion:
            return respuesta, {
                "type": "quick_replies",
                "quick_replies": self.get_confirmation_quick_replies(),
            }

        # 3. ¿Pregunta por método de pago?
        es_pregunta_pago = any(k in resp_clean for k in [
            "cómo deseas realizar tu pago", "como deseas realizar tu pago",
            "cuál será tu método de pago", "cual sera tu metodo de pago",
            "método de pago", "metodo de pago", "forma de pago",
            "pagarás en efectivo", "pagaras en efectivo", "efectivo o terminal",
            "efectivo o tarjeta"
        ])
        if es_pregunta_pago:
            cleaned = self.clean_text_for_interactive(respuesta, "quick_replies", "payment")
            return cleaned, {
                "type": "quick_replies",
                "quick_replies": self.get_payment_method_quick_replies(),
            }

        # 4. Propuesta de horario alternativo (cupo lleno)
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
                "type": "quick_replies",
                "quick_replies": self.get_schedule_alternative_quick_replies(),
            }

        # 5. Pregunta general de horario/fecha
        es_pregunta_horario_o_fecha = any(k in resp_clean for k in [
            "qué día", "que dia", "día y hora", "dia y hora", "a qué hora", "a que hora",
            "cuándo deseas recibir", "cuando deseas recibir", "cuándo deseas que", "cuando deseas que",
            "cuándo prefieres recibir", "cuando prefieres recibir", "cuándo te gustaría recibir",
            "cuando te gustaria recibir", "fecha y horario", "fecha de entrega", "horario de entrega",
            "programar tu entrega", "programar la entrega", "programar tu horario", "programar la fecha",
            "en qué horario", "en que horario", "lo antes posible o programar", "para hoy o para mañana"
        ])
        if es_pregunta_horario_o_fecha:
            if not any(k in resp_clean for k in ["indícame la hora", "indicame la hora", "escribe la hora", "hora y el día", "hora y el dia"]):
                cleaned = self.clean_text_for_interactive(respuesta, "quick_replies", "schedule")
                return cleaned, {
                    "type": "quick_replies",
                    "quick_replies": self.get_schedule_quick_replies(),
                }

        # 6. ¿Pregunta por direcciones registradas?
        es_pregunta_direccion = any(k in resp_clean for k in [
            "dirección registrada", "direccion registrada", "direcciones registradas",
            "direcciones guardadas", "dirección guardada", "direccion guardada",
            "a cuál de tus direcciones", "cual de tus direcciones",
            "a cuál de estas direcciones", "cual de estas direcciones",
            "deseas recibir tu pedido en", "deseas que enviemos tu pedido",
            "en cuál de tus domicilios", "en cual de tus domicilios"
        ])
        if es_pregunta_direccion and psid:
            repo = get_repository()
            phone_to_search = None
            try:
                from src.services.flow_router import flow_router
                sess = flow_router.get_session(psid)
                if sess and sess.draft_order and sess.draft_order.customer_phone:
                    phone_to_search = sess.draft_order.customer_phone
            except Exception:
                pass

            cust = repo.get_customer_by_phone(tenant_id, phone_to_search) if phone_to_search else None
            if not cust:
                cust = repo.get_customer(tenant_id, "messenger", psid)

            addrs = cust.addresses if (cust and cust.addresses) else ([CustomerAddress(id=1, address=cust.address, alias="Principal")] if cust and cust.address else [])
            if addrs:
                addr_lines = "\n".join(f"📍 **{i}.** {a.address}" for i, a in enumerate(addrs, start=1))
                text_with_addrs = (
                    f"🏠 **Tus direcciones registradas:**\n\n"
                    f"{addr_lines}\n\n"
                    f"¿A cuál de tus direcciones deseas que enviemos tu pedido o prefieres ingresar una nueva?"
                )
                return text_with_addrs, {
                    "type": "quick_replies",
                    "quick_replies": self.get_customer_addresses_quick_replies(addrs),
                }

        return respuesta, None
