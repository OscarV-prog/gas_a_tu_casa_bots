"""Instagram Direct Webhook Router (FastAPI).

Receives incoming messages, quick replies, postbacks, locations, and attachments
from Instagram Direct, orchestrating the sales conversation using flow_router.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import PlainTextResponse

from src.channels.instagram.adapter import InstagramAdapter
from src.config.settings import get_settings
from src.models.customer import CustomerAddress
from src.models.product import Product
from src.repositories import get_repository
from src.repositories.identity_store import identity_store
from src.services.audio_transcription import transcribe_audio_file
from src.services.flow_router import FlowResponse, FlowState, flow_router

logger = logging.getLogger(__name__)

router = APIRouter()
adapter = InstagramAdapter()

TENANT_ID = "petroil"

# Carrito de compras interactivo temporal por usuario de Instagram (igsid -> {prod_id: quantity})
ig_carts: dict[str, dict[str, int]] = {}

# Seguimiento de calificaciones CSAT y comentarios posteriores
_AWAITING_RATING_COMMENTS: dict[str, dict[str, Any]] = {}

# Sesiones activas de creación/levantamiento de pedido (igsid -> timestamp)
_active_order_sessions: dict[str, float] = {}

# Deduplicación e Idempotencia (msg_id -> timestamp)
_PROCESSED_MSG_IDS: dict[str, float] = {}
_IDEMPOTENCY_TTL_SECONDS = 600.0


def get_user_cart(igsid: str) -> dict[str, int]:
    """Obtiene el carrito activo del usuario de Instagram."""
    return ig_carts.setdefault(igsid, {})


def add_to_cart(igsid: str, prod_id: str, qty: int = 1) -> dict[str, int]:
    """Agrega o incrementa la cantidad de un producto en el carrito."""
    cart = get_user_cart(igsid)
    cart[prod_id] = cart.get(prod_id, 0) + qty
    return cart


def clear_cart(igsid: str) -> None:
    """Vacía el carrito del usuario."""
    ig_carts[igsid] = {}


def format_cart_summary(cart: dict[str, int], tenant_id: str = "petroil") -> tuple[str, float, int]:
    """Genera el resumen legible del carrito con totales y subtotales."""
    repo = get_repository()
    prods = repo.get_all_products(tenant_id)
    prods_by_id = {p.id: p for p in prods}

    lines = []
    total_price = 0.0
    total_qty = 0

    for pid, qty in cart.items():
        if qty > 0:
            prod = prods_by_id.get(pid)
            name = prod.name if prod else f"Cilindro ({pid})"
            price = prod.price if prod else 0.0
            subtotal = qty * price
            total_price += subtotal
            total_qty += qty
            lines.append(f"• **{qty}x {name}** — ${subtotal:,.2f} MXN")

    plural = "s" if total_qty > 1 else ""
    summary_text = (
        "🛒 **Tu selección actual:**\n"
        + "\n".join(lines)
        + f"\n\n💰 **Total acumulado:** ${total_price:,.2f} MXN ({total_qty} cilindro{plural})"
    )
    return summary_text, total_price, total_qty


def _is_duplicate_message(msg_id: str) -> bool:
    """Verifica si el mensaje ya fue recibido y procesado recientemente."""
    if not msg_id:
        return False
    now = time.time()
    if len(_PROCESSED_MSG_IDS) > 2000:
        expired_keys = [k for k, ts in _PROCESSED_MSG_IDS.items() if now - ts > _IDEMPOTENCY_TTL_SECONDS]
        for k in expired_keys:
            _PROCESSED_MSG_IDS.pop(k, None)

    if msg_id in _PROCESSED_MSG_IDS and (now - _PROCESSED_MSG_IDS[msg_id]) < _IDEMPOTENCY_TTL_SECONDS:
        return True

    _PROCESSED_MSG_IDS[msg_id] = now
    return False


def verify_instagram_signature(body_bytes: bytes, signature_header: str | None, app_secret: str) -> bool:
    """Valida la firma HMAC-SHA256 (X-Hub-Signature-256) de Meta."""
    if not app_secret:
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    received_hash = signature_header[len("sha256="):]
    expected_hash = hmac.new(app_secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(received_hash, expected_hash)


# -----------------------------------------------------------------------------
# GET Webhook Verification Endpoint (Meta Challenge)
# -----------------------------------------------------------------------------

@router.get("", response_class=PlainTextResponse)
@router.get("/", response_class=PlainTextResponse)
async def verify_webhook(request: Request):
    """Instagram Webhook verification endpoint (Meta Challenge)."""
    settings = get_settings()
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    expected_token = (
        settings.instagram_verify_token
        or settings.messenger_verify_token
        or settings.whatsapp_verify_token
        or "petroil_gas_webhook_secret"
    )

    if mode == "subscribe" and token == expected_token:
        logger.info("[Instagram] Webhook successfully verified with Meta.")
        return challenge or ""

    logger.warning(f"[Instagram] Verification failed. Received token: {token}")
    raise HTTPException(status_code=403, detail="Verification token mismatch")


# -----------------------------------------------------------------------------
# POST Webhook Inbound Message Endpoint
# -----------------------------------------------------------------------------

@router.post("")
@router.post("/")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receive real-time incoming messages and events from Instagram Direct."""
    settings = get_settings()
    body_bytes = await request.body()

    # 1. Validación de Firma Criptográfica si está configurada
    app_secret = settings.instagram_app_secret or settings.messenger_app_secret
    if app_secret:
        sig = request.headers.get("x-hub-signature-256") or request.headers.get("x-hub-signature")
        if not verify_instagram_signature(body_bytes, sig, app_secret):
            logger.warning("[Instagram] Signature mismatch on incoming request.")
            raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        payload = json.loads(body_bytes.decode("utf-8"))
        logger.info(f"[Instagram Webhook] POST received payload: {payload}")
    except Exception as e:
        logger.error(f"[Instagram] Invalid JSON payload received: {e}")
        return {"status": "error", "message": "Invalid JSON"}

    # Extraer y normalizar eventos de Instagram
    events = adapter.parse_webhook_events(payload, default_tenant_id=TENANT_ID)
    logger.info(f"[Instagram Webhook] Extracted {len(events)} events: {events}")
    if not events:
        return {"status": "ok", "processed": 0}

    for ev in events:
        msg_id = ev.get("msg_id")
        if _is_duplicate_message(msg_id):
            logger.info(f"[Instagram] Skipping duplicate message: {msg_id}")
            continue

        background_tasks.add_task(_process_single_instagram_event, ev)

    return {"status": "ok", "processed": len(events)}


# -----------------------------------------------------------------------------
# Core Event Processor for Instagram
# -----------------------------------------------------------------------------

async def _process_single_instagram_event(event: dict[str, Any]) -> None:
    """Process a single normalized Instagram Direct message event."""
    igsid = event.get("igsid") or event.get("psid")
    if not igsid:
        return

    # Visual feedback: Mark seen & show typing indicator
    await adapter.send_sender_action(igsid, "mark_seen")
    await adapter.send_sender_action(igsid, "typing_on")

    repo = get_repository()
    interactive_id = event.get("interactive_id") or ""
    texto_usuario = (event.get("text") or "").strip()

    # -------------------------------------------------------------------------
    # 1. Manejo de Calificación CSAT (Encuesta de Satisfacción Post-Entrega)
    # -------------------------------------------------------------------------
    if interactive_id.startswith("rate:"):
        parts = interactive_id.split(":")
        order_id = int(parts[1])
        stars = int(parts[2])

        repo.save_order_rating(
            tenant_id=TENANT_ID,
            order_id=order_id,
            rating=stars,
        )

        order = repo.get_order_by_id(TENANT_ID, order_id)
        driver_name = "tu repartidor"
        if order and order.driver_id:
            d = repo.get_driver(order.driver_id)
            if d:
                driver_name = d.name

        stars_str = "⭐" * stars
        if stars >= 4:
            body_msg = (
                f"🌟 **¡Muchas gracias por calificar con {stars_str}!** ({stars}/5)\n\n"
                f"¿Qué fue lo que más te agradó del servicio de {driver_name}?"
            )
        else:
            body_msg = (
                f"🙏 **Agradecemos tu calificación de {stars_str}** ({stars}/5)\n\n"
                f"Lamentamos que tu experiencia con {driver_name} no haya sido óptima.\n"
                "¿En qué aspecto podemos mejorar?"
            )

        quick_replies = adapter.get_rating_feedback_quick_replies(order_id, stars)
        await adapter.send_quick_replies(
            recipient_igsid=igsid,
            text=body_msg,
            quick_replies=quick_replies,
        )
        return

    elif interactive_id.startswith("rate_tag:"):
        parts = interactive_id.split(":")
        order_id = int(parts[1])
        tag = parts[2]
        feedback_to_save = None if tag == "Omitido" else tag

        if feedback_to_save:
            repo.update_order_rating_feedback(TENANT_ID, order_id, feedback_tag=feedback_to_save)

        rating_data = repo.get_order_rating(TENANT_ID, order_id)
        stars_val = rating_data.get("rating", 5) if rating_data else 5
        stars_str = "⭐" * stars_val

        _AWAITING_RATING_COMMENTS[igsid] = {
            "order_id": order_id,
            "time": time.time(),
        }

        detalle_str = f"\n💬 **Aspecto registrado:** {feedback_to_save}" if feedback_to_save else ""
        msg_final = (
            f"✅ **¡ENCUESTA COMPLETADA CON ÉXITO!**\n\n"
            f"⭐ **Calificación:** {stars_str} ({stars_val}/5){detalle_str}\n\n"
            "¡Muchas gracias por tu tiempo y valiosa opinión! Nos ayuda a premiar a nuestros mejores choferes y mejorar día a día. ¡Estamos a tus órdenes! ⛽🌟\n\n"
            "_💡 Opcional: Si deseas agregar algún comentario o sugerencia escrita sobre tu repartidor, puedes enviarla en tu siguiente mensaje._"
        )
        await adapter.send_text_message(igsid, msg_final)
        return

    # Comentario posterior a la calificación CSAT
    rating_ctx = _AWAITING_RATING_COMMENTS.get(igsid)
    if rating_ctx and (time.time() - rating_ctx.get("time", 0)) < 600 and texto_usuario:
        texto_lower = texto_usuario.lower()
        es_nuevo_pedido = any(k in texto_lower for k in ["quiero", "cilindro", "estacionario", "tanque", "litros", "pedir", "orden", "hola", "/start"])
        order_id_rating = rating_ctx.get("order_id")
        if not es_nuevo_pedido and order_id_rating:
            _AWAITING_RATING_COMMENTS.pop(igsid, None)
            repo.update_order_rating_feedback(TENANT_ID, order_id_rating, comment=texto_usuario)
            await adapter.send_text_message(
                igsid,
                "📝 **¡Comentario registrado!**\n\n"
                "Muchas gracias por compartirnos tu opinión detallada. Tus comentarios han sido guardados para el equipo de calidad de Petroil. ¡Que tengas un excelente día! ⛽🌟"
            )
            return
        else:
            _AWAITING_RATING_COMMENTS.pop(igsid, None)

    # -------------------------------------------------------------------------
    # 2. Manejo de Notas de Voz / Audio
    # -------------------------------------------------------------------------
    msg_type = event.get("type", "text")
    if msg_type == "audio":
        media_url = event.get("media_url")
        audio_dir = Path(__file__).parent.parent.parent.parent / "uploads" / "voice_notes"
        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_path = audio_dir / f"voice_ig_{igsid}_{int(time.time())}.mp4"

        transcription = ""
        if media_url:
            downloaded = await adapter.download_media(media_url, audio_path)
            if downloaded:
                transcription = await transcribe_audio_file(downloaded)

        if transcription:
            texto_usuario = transcription
        else:
            await adapter.send_text_message(
                igsid,
                "🎙️ He recibido tu nota de voz, pero no fue posible transcribirla con claridad. "
                "Por favor intenta escribir tu mensaje o enviar un nuevo audio."
            )
            return

    # -------------------------------------------------------------------------
    # 3. Manejo de Imágenes (Catálogo Visual)
    # -------------------------------------------------------------------------
    if msg_type == "image":
        caption = (event.get("text") or "").strip()
        if caption and caption != "[Imagen enviada por el cliente]":
            texto_usuario = caption
        else:
            _active_order_sessions[igsid] = time.time()
            elements = adapter.get_cylinder_catalog_elements(TENANT_ID, include_buttons=True)
            await adapter.send_generic_template(
                recipient_igsid=igsid,
                elements=elements,
            )
            return

    # -------------------------------------------------------------------------
    # 4. Manejo de Ubicación GPS
    # -------------------------------------------------------------------------
    loc = event.get("location")
    if loc and loc.get("latitude") is not None and loc.get("longitude") is not None:
        lat = float(loc["latitude"])
        lng = float(loc["longitude"])
        flow_res = await flow_router.process_event(
            session_id=igsid,
            location={"latitude": lat, "longitude": lng},
            channel="instagram",
            channel_user_id=igsid,
            tenant_id=TENANT_ID,
        )
        await _dispatch_flow_response_instagram(flow_res, igsid=igsid)
        return

    # -------------------------------------------------------------------------
    # 5. Mapeo de Acciones Interactivas de Botones y Carrito
    # -------------------------------------------------------------------------
    if interactive_id:
        # Verificación si el pedido consultado ya fue entregado / cerrado
        cust = repo.get_customer(TENANT_ID, "instagram", igsid)
        user_phone = (cust.phone if cust else None) or identity_store.get_phone_for_channel_user("instagram", igsid)
        if not user_phone:
            sess = flow_router.get_session(igsid)
            if sess and sess.draft_order and sess.draft_order.customer_phone:
                user_phone = sess.draft_order.customer_phone

        if user_phone:
            user_orders = repo.get_orders_by_customer_phone(TENANT_ID, user_phone, limit=3)
            if user_orders:
                latest_order = user_orders[0]
                is_closed = latest_order.status in ("delivered", "entregado", "completed", "cancelled", "cancelado")
                if is_closed:
                    if any(interactive_id.startswith(p) for p in ("cancel_order_client:", "keep_order_client:", "confirm_cancel_client:")):
                        await adapter.send_text_message(
                            igsid,
                            f"📦 **Tu pedido #{latest_order.id} ya fue finalizado exitosamente.**\n\n"
                            "Los botones de este servicio han quedado inactivos. Si requieres un nuevo servicio de gas, escribe *Hola* o selecciona un servicio en el menú. ⛽✨",
                        )
                        return
                    if interactive_id.startswith(("cylinder_qty:", "cart_more", "cart_clear", "cart_checkout", "cart_add:")):
                        sess = flow_router.get_session(igsid)
                        is_active_lifting = (
                            (igsid in _active_order_sessions)
                            or bool(get_user_cart(igsid))
                            or (sess and sess.state in (
                                FlowState.INITIAL,
                                FlowState.WAITING_FOR_PRODUCT_OR_QUANTITY,
                                FlowState.WAITING_FOR_PHONE,
                                FlowState.WAITING_FOR_ADDRESS_SELECTION,
                            ))
                        )
                        if not is_active_lifting and sess and sess.state == FlowState.COMPLETED:
                            await adapter.send_quick_replies(
                                recipient_igsid=igsid,
                                text=(
                                    f"📦 **Tu pedido #{latest_order.id} ya fue cerrado y entregado exitosamente.**\n\n"
                                    "El botón de compra de ese banner ha expirado. Si deseas realizar un nuevo pedido, pulsa abajo para abrir tu catálogo activo: 👇"
                                ),
                                quick_replies=[{"id": "client_svc:cilindro", "title": "🛻 Nuevo Pedido"}],
                            )
                            return

        if any(interactive_id.startswith(p) for p in ("cancel_order_client:", "keep_order_client:", "confirm_cancel_client:")):
            raw_parts = interactive_id.split(":")
            if len(raw_parts) > 1 and raw_parts[1].isdigit():
                chk_oid = int(raw_parts[1])
                chk_order = repo.get_order_by_id(TENANT_ID, chk_oid)
                if chk_order and chk_order.status in ("delivered", "entregado", "completed", "cancelled", "cancelado"):
                    await adapter.send_text_message(
                        igsid,
                        f"📦 **Tu pedido #{chk_oid} ya fue finalizado exitosamente.**\n\n"
                        "Los botones de este servicio han quedado inactivos. Si requieres un nuevo servicio de gas, escribe *Hola* o selecciona un servicio en el menú. ⛽✨",
                    )
                    return

        if interactive_id == "client_svc:cilindro":
            _active_order_sessions[igsid] = time.time()
            clear_cart(igsid)
            elements = adapter.get_cylinder_catalog_elements(TENANT_ID, include_buttons=True)
            await adapter.send_generic_template(
                recipient_igsid=igsid,
                elements=elements,
            )
            return

        elif interactive_id == "client_svc:estacionario":
            _active_order_sessions[igsid] = time.time()
            clear_cart(igsid)
            flow_res = await flow_router.process_event(
                session_id=igsid,
                callback_data="client_svc:estacionario",
                channel="instagram",
                channel_user_id=igsid,
                tenant_id=TENANT_ID,
            )
            await _dispatch_flow_response_instagram(flow_res, igsid=igsid)
            return

        elif interactive_id.startswith("cart_add:"):
            _active_order_sessions[igsid] = time.time()
            clear_cart(igsid)
            parts = interactive_id.split(":")
            prod_id = parts[1]
            qty = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
            add_to_cart(igsid, prod_id, qty)

            cart = get_user_cart(igsid)
            summary_text, total_val, total_qty = format_cart_summary(cart, TENANT_ID)

            prods = repo.get_all_products(TENANT_ID)
            p_obj = next((p for p in prods if p.id == prod_id), None)
            p_name = p_obj.name if p_obj else f"Cilindro ({prod_id})"

            qty_buttons = [
                {"id": f"cylinder_qty:{prod_id}:1", "title": "1 Cilindro"},
                {"id": f"cylinder_qty:{prod_id}:2", "title": "2 Cilindros"},
                {"id": f"cylinder_qty:{prod_id}:3", "title": "3 Cilindros"},
                {"id": "cart_more", "title": "➕ Otro Tipo"},
                {"id": "cart_checkout", "title": "✅ Continuar"},
                {"id": "cart_clear", "title": "🗑️ Vaciar"},
            ]

            prompt_msg = (
                f"{summary_text}\n\n"
                f"¿Cuántas unidades de **{p_name}** deseas solicitar? Puedes pulsar una cantidad o continuar directo: 👇"
            )
            await adapter.send_quick_replies(
                recipient_igsid=igsid,
                text=prompt_msg,
                quick_replies=qty_buttons,
            )
            return

        elif interactive_id.startswith("cylinder_qty:"):
            parts = interactive_id.split(":")
            prod_id = parts[1]
            qty = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1

            cart = get_user_cart(igsid)
            cart[prod_id] = qty

            summary_text, total_val, total_qty = format_cart_summary(cart, TENANT_ID)
            buttons = adapter.get_cart_quick_replies(total_qty)

            msg_cart = (
                f"{summary_text}\n\n"
                "¿Deseas agregar otro cilindro diferente o continuar con tu pedido?"
            )
            await adapter.send_quick_replies(
                recipient_igsid=igsid,
                text=msg_cart,
                quick_replies=buttons,
            )
            return

        elif interactive_id == "cart_more":
            _active_order_sessions[igsid] = time.time()
            elements = adapter.get_cylinder_catalog_elements(TENANT_ID, include_buttons=True)
            await adapter.send_generic_template(
                recipient_igsid=igsid,
                elements=elements,
            )
            return

        elif interactive_id == "cart_clear":
            clear_cart(igsid)
            _active_order_sessions[igsid] = time.time()
            await adapter.send_quick_replies(
                recipient_igsid=igsid,
                text="🗑️ **Carrito vaciado.** ¿Qué tipo de servicio de gas necesitas?",
                quick_replies=adapter.get_service_quick_replies(),
            )
            return

        elif interactive_id == "cart_checkout":
            cart = get_user_cart(igsid)
            if not cart or sum(cart.values()) == 0:
                elements = adapter.get_cylinder_catalog_elements(TENANT_ID, include_buttons=True)
                await adapter.send_text_message(igsid, "🛒 **Tu carrito está vacío.** Por favor selecciona un cilindro en el catálogo:")
                await adapter.send_generic_template(recipient_igsid=igsid, elements=elements)
                return

            prods = repo.get_all_products(TENANT_ID)
            prods_by_id = {p.id: p for p in prods}
            items_str = ", ".join(
                f"{qty}x {prods_by_id[pid].name if pid in prods_by_id else pid}"
                for pid, qty in cart.items()
                if qty > 0
            )
            clear_cart(igsid)
            flow_res = await flow_router.process_event(
                session_id=igsid,
                text=f"Deseo ordenar los siguientes productos seleccionados de tu catálogo: {items_str}.",
                channel="instagram",
                channel_user_id=igsid,
                tenant_id=TENANT_ID,
            )
            await _dispatch_flow_response_instagram(flow_res, igsid=igsid)
            return

        elif interactive_id in ("client_addr:del_menu", "client_addr_del_menu"):
            sess = flow_router.get_session(igsid)
            phone_to_search = (sess.draft_order.customer_phone if (sess and sess.draft_order and sess.draft_order.customer_phone) else None) or identity_store.get_phone_for_channel_user("instagram", igsid)
            cust = repo.get_customer_by_phone(TENANT_ID, phone_to_search) if phone_to_search else None
            if not cust:
                cust = repo.get_customer(TENANT_ID, "instagram", igsid)

            addrs = cust.addresses if (cust and cust.addresses) else ([CustomerAddress(id=1, address=cust.address, alias="Principal")] if cust and cust.address else [])
            if not addrs:
                await adapter.send_text_message(igsid, "ℹ️ No tienes direcciones registradas para eliminar.")
                return

            del_replies = []
            for i, a in enumerate(addrs[:10], start=1):
                c_addr = resolve_gps_address_to_name(a.address.strip())
                c_addr = re.sub(r"^(?:\[(?:Nueva\s*Direcci[oó]n|Direcci[oó]n(?:\s*\d+)?|Principal)\]\s*)+", "", c_addr, flags=re.I).strip()
                calle = c_addr.split(",")[0].strip() if c_addr else "Domicilio"
                short = calle[:13] if len(calle) > 13 else calle
                addr_id = a.id if a.id else i
                del_replies.append({"id": f"del_addr_prompt:{addr_id}", "title": f"🗑️ {i}. {short}"[:20]})
            del_replies.append({"id": "client_addr:cancel_del", "title": "🔙 Cancelar"})

            msg_del = (
                "🗑️ **Eliminar Dirección Guardada**\n\n"
                "Selecciona abajo cuál de tus direcciones deseas borrar definitivamente de tu cuenta:"
            )
            await adapter.send_quick_replies(igsid, msg_del, del_replies)
            return

        elif interactive_id.startswith("del_addr_prompt:"):
            addr_id_str = interactive_id.split(":", 1)[1]
            sess = flow_router.get_session(igsid)
            phone_to_search = (sess.draft_order.customer_phone if (sess and sess.draft_order and sess.draft_order.customer_phone) else None) or identity_store.get_phone_for_channel_user("instagram", igsid)
            cust = repo.get_customer_by_phone(TENANT_ID, phone_to_search) if phone_to_search else None
            if not cust:
                cust = repo.get_customer(TENANT_ID, "instagram", igsid)

            target_addr = None
            if cust and cust.addresses:
                target_addr = next((a for a in cust.addresses if str(a.id) == str(addr_id_str)), None)

            addr_display = target_addr.address if target_addr else f"Dirección #{addr_id_str}"
            clean_display = resolve_gps_address_to_name(addr_display.strip())
            clean_display = re.sub(r"^(?:\[(?:Nueva\s*Direcci[oó]n|Direcci[oó]n(?:\s*\d+)?|Principal)\]\s*)+", "", clean_display, flags=re.I).strip()

            confirm_msg = (
                "⚠️ **¿Estás seguro de que deseas eliminar esta dirección?**\n\n"
                f"📍 `{clean_display}`\n\n"
                "Esta acción no se puede deshacer. Por favor confirma tu decisión:"
            )
            confirm_replies = [
                {"id": f"del_addr_confirm:{addr_id_str}", "title": "🗑️ Sí, eliminar"},
                {"id": "client_addr:cancel_del", "title": "❌ No, cancelar"},
            ]
            await adapter.send_quick_replies(igsid, confirm_msg, confirm_replies)
            return

        elif interactive_id.startswith("del_addr_confirm:"):
            addr_id_str = interactive_id.split(":", 1)[1]
            sess = flow_router.get_session(igsid)
            phone_to_search = (sess.draft_order.customer_phone if (sess and sess.draft_order and sess.draft_order.customer_phone) else None) or identity_store.get_phone_for_channel_user("instagram", igsid)
            cust = repo.get_customer_by_phone(TENANT_ID, phone_to_search) if phone_to_search else None
            if not cust:
                cust = repo.get_customer(TENANT_ID, "instagram", igsid)

            if cust and addr_id_str:
                addr_id_val = int(addr_id_str) if addr_id_str.isdigit() else addr_id_str
                target_addr = next((a for a in cust.addresses if str(a.id) == str(addr_id_str)), None) if cust.addresses else None
                addr_text = target_addr.address if target_addr else ""
                repo.delete_customer_address(cust.id, addr_id_val, phone=phone_to_search, address_text=addr_text)
                remaining = repo.get_customer_addresses(cust.id) if hasattr(repo, "get_customer_addresses") else []
                if remaining:
                    succ_msg = (
                        "✅ **Dirección eliminada con éxito.**\n\n"
                        "¿A cuál de tus direcciones enviamos tu pedido o prefieres ingresar una nueva?"
                    )
                    await adapter.send_quick_replies(igsid, succ_msg, adapter.get_customer_addresses_quick_replies(remaining))
                else:
                    succ_msg = (
                        "✅ **Dirección eliminada con éxito.**\n\n"
                        "Ya no tienes direcciones guardadas en tu cuenta. Por favor escribe tu dirección de entrega completa o pulsa el botón a continuación:"
                    )
                    await adapter.send_quick_replies(igsid, succ_msg, [{"id": "client_addr:new", "title": "➕ Nueva Dirección"}])
                return

        elif interactive_id in ("client_addr:cancel_del", "client_addr_cancel_del"):
            sess = flow_router.get_session(igsid)
            phone_to_search = (sess.draft_order.customer_phone if (sess and sess.draft_order and sess.draft_order.customer_phone) else None) or identity_store.get_phone_for_channel_user("instagram", igsid)
            cust = repo.get_customer_by_phone(TENANT_ID, phone_to_search) if phone_to_search else None
            if not cust:
                cust = repo.get_customer(TENANT_ID, "instagram", igsid)
            addrs = cust.addresses if (cust and cust.addresses) else ([CustomerAddress(id=1, address=cust.address, alias="Principal")] if cust and cust.address else [])
            if addrs:
                full_text = "ℹ️ **Operación cancelada.** Tu dirección se mantiene guardada.\n\n¿A cuál de tus direcciones deseas que enviemos tu pedido o prefieres registrar una nueva?"
                await adapter.send_quick_replies(igsid, full_text, adapter.get_customer_addresses_quick_replies(addrs))
            return

        elif interactive_id.startswith("client_addr:") or interactive_id in ("client_addr_new", "client_addr:new"):
            flow_res = await flow_router.process_event(
                session_id=igsid,
                callback_data=interactive_id,
                channel="instagram",
                channel_user_id=igsid,
                tenant_id=TENANT_ID,
            )
            await _dispatch_flow_response_instagram(flow_res, igsid=igsid)
            return

        elif interactive_id.startswith("client_sch:") or interactive_id.startswith("client_sch_"):
            flow_res = await flow_router.process_event(
                session_id=igsid,
                callback_data=interactive_id,
                channel="instagram",
                channel_user_id=igsid,
                tenant_id=TENANT_ID,
            )
            await _dispatch_flow_response_instagram(flow_res, igsid=igsid)
            return

        elif interactive_id in ("client_pay:efectivo", "client_pay:terminal"):
            flow_res = await flow_router.process_event(
                session_id=igsid,
                callback_data=interactive_id,
                channel="instagram",
                channel_user_id=igsid,
                tenant_id=TENANT_ID,
            )
            await _dispatch_flow_response_instagram(flow_res, igsid=igsid)
            return

        elif interactive_id in ("client_confirm:yes", "client_confirm:edit", "client_confirm:cancel"):
            if interactive_id == "client_confirm:cancel":
                clear_cart(igsid)
            flow_res = await flow_router.process_event(
                session_id=igsid,
                callback_data=interactive_id,
                channel="instagram",
                channel_user_id=igsid,
                tenant_id=TENANT_ID,
            )
            await _dispatch_flow_response_instagram(flow_res, igsid=igsid)
            return

        elif interactive_id.startswith("client_edit:"):
            flow_res = await flow_router.process_event(
                session_id=igsid,
                callback_data=interactive_id,
                channel="instagram",
                channel_user_id=igsid,
                tenant_id=TENANT_ID,
            )
            await _dispatch_flow_response_instagram(flow_res, igsid=igsid)
            return

        elif interactive_id.startswith("cancel_order_client:"):
            order_id = int(interactive_id.split(":")[1])
            order = repo.get_order_by_id(TENANT_ID, order_id)
            if not order:
                await adapter.send_text_message(igsid, "⚠️ Pedido no encontrado.")
                return

            if order.status in ("delivered", "entregado"):
                await adapter.send_text_message(igsid, "⚠️ Tu pedido ya fue entregado y no puede cancelarse.")
                return

            if order.status in ("cancelled", "cancelado"):
                await adapter.send_text_message(igsid, f"⚠️ El pedido #{order_id} ya se encuentra cancelado.")
                return

            buttons = adapter.get_order_cancel_confirm_quick_replies(order_id)
            confirm_msg = (
                f"⚠️ **¿Estás seguro de que deseas cancelar tu pedido #{order_id}?**\n\n"
                f"📍 **Entrega:** {order.delivery_address}\n"
                f"💰 **Total a pagar:** ${order.total_amount:.2f} ({order.payment_method})\n\n"
                "Si confirmas la cancelación, la unidad de reparto asignada será liberada y tu entrega quedará suspendida definitivamente."
            )
            await adapter.send_quick_replies(
                recipient_igsid=igsid,
                text=confirm_msg,
                quick_replies=buttons,
            )
            return

        elif interactive_id.startswith("keep_order_client:"):
            order_id = int(interactive_id.split(":")[1])
            order = repo.get_order_by_id(TENANT_ID, order_id)
            if not order:
                await adapter.send_text_message(igsid, "⚠️ Pedido no encontrado.")
                return

            from src.tools.get_order_status import format_clean_driver_status
            status_text = format_clean_driver_status(order, repo=repo)
            ig_text = f"✅ **¡Excelente! Tu pedido #{order_id} sigue activo.**\n\n" + status_text
            buttons = adapter.get_order_active_quick_replies(order_id)
            await adapter.send_quick_replies(
                recipient_igsid=igsid,
                text=ig_text,
                quick_replies=buttons,
            )
            return

        elif interactive_id.startswith("confirm_cancel_order_client:"):
            order_id = int(interactive_id.split(":")[1])
            order = repo.get_order_by_id(TENANT_ID, order_id)
            if not order:
                await adapter.send_text_message(igsid, "⚠️ Pedido no encontrado.")
                return

            repo.cancel_order(TENANT_ID, order_id, cancelled_by="el cliente")
            identity_store.save_order_cancellation(order_id, cancelled_by="el cliente", reason="Cancelado por el cliente desde Instagram")
            try:
                from src.services.order_events import _EVENT_DEDUP_CACHE
                _EVENT_DEDUP_CACHE[f"cancelled:{order_id}"] = time.time()
            except Exception:
                pass

            if order.driver_id:
                driver = repo.get_driver(order.driver_id)
                if driver and driver.telegram_chat_id:
                    from src.services.notifications import notify_driver_order_cancelled
                    notify_driver_order_cancelled(
                        telegram_chat_id=driver.telegram_chat_id,
                        order_id=order_id,
                        cancelled_by="el cliente vía Instagram",
                        customer_name=order.customer_name or "Cliente Instagram",
                    )

            cancel_msg = (
                f"🚫 **Tu pedido #{order_id} ha sido CANCELADO exitosamente.**\n\n"
                "La unidad asignada ha sido notificada y liberada. No se realizará ningún cargo ni cobro.\n\n"
                "Si deseas solicitar un nuevo cilindro o servicio en cualquier momento, solo escribe **'Hola'** o selecciona un servicio en el menú."
            )
            buttons = adapter.get_service_quick_replies()
            await adapter.send_quick_replies(
                recipient_igsid=igsid,
                text=cancel_msg,
                quick_replies=buttons,
            )
            return

    # -------------------------------------------------------------------------
    # 6. Procesamiento de Mensajes de Texto con FlowRouter
    # -------------------------------------------------------------------------
    if not texto_usuario:
        return

    # Si es un nuevo cliente en Instagram, intentar recuperar su perfil de Meta
    existing_cust = repo.get_customer(TENANT_ID, "instagram", igsid)
    if not existing_cust:
        profile = await adapter.get_user_profile(igsid)
        if profile and (profile.get("name") or profile.get("username")):
            full_name = profile.get("name") or f"@{profile.get('username')}"
            repo.get_or_create_customer(
                tenant_id=TENANT_ID,
                channel="instagram",
                channel_user_id=igsid,
                name=full_name,
            )

    flow_res = await flow_router.process_event(
        session_id=igsid,
        text=texto_usuario,
        channel="instagram",
        channel_user_id=igsid,
        tenant_id=TENANT_ID,
    )
    await _dispatch_flow_response_instagram(flow_res, igsid=igsid)


# -----------------------------------------------------------------------------
# Dispatcher: Emite la respuesta de FlowRouter con UI Rica de Instagram
# -----------------------------------------------------------------------------

async def _dispatch_flow_response_instagram(flow_res: FlowResponse, igsid: str) -> None:
    """Dispatches the FlowResponse to the Instagram user with appropriate interactive elements."""
    if not flow_res:
        return

    action_performed = flow_res.action_performed
    respuesta = flow_res.text or ""
    state = flow_res.state
    repo = get_repository()

    # Turn off typing before sending response
    await adapter.send_sender_action(igsid, "typing_off")

    if action_performed in ("ask_service_type", "show_service_buttons") or state == FlowState.INITIAL:
        cleaned = adapter.clean_text_for_interactive(respuesta, "quick_replies", "service")
        await adapter.send_quick_replies(
            recipient_igsid=igsid,
            text=cleaned,
            quick_replies=adapter.get_service_quick_replies(),
        )
        return

    elif action_performed in ("show_catalog", "show_cylinder_catalog") or state == FlowState.WAITING_FOR_PRODUCT_OR_QUANTITY:
        _active_order_sessions[igsid] = time.time()
        elements = adapter.get_cylinder_catalog_elements(TENANT_ID, include_buttons=True)
        await adapter.send_generic_template(
            recipient_igsid=igsid,
            elements=elements,
        )
        return

    elif action_performed in ("show_address_buttons", "select_address") or state == FlowState.WAITING_FOR_ADDRESS_SELECTION:
        sess = flow_router.get_session(igsid)
        phone_to_search = (sess.draft_order.customer_phone if (sess and sess.draft_order and sess.draft_order.customer_phone) else None) or identity_store.get_phone_for_channel_user("instagram", igsid)

        cust = repo.get_customer_by_phone(TENANT_ID, phone_to_search) if phone_to_search else None
        if not cust:
            cust = repo.get_customer(TENANT_ID, "instagram", igsid)

        addrs = cust.addresses if (cust and cust.addresses) else ([CustomerAddress(id=1, address=cust.address, alias="Principal")] if cust and cust.address else [])
        if addrs:
            full_text = "¿A cuál de tus direcciones deseas que enviemos tu pedido o prefieres ingresar una nueva?"
            quick_replies = adapter.get_customer_addresses_quick_replies(addrs)
            await adapter.send_quick_replies(
                recipient_igsid=igsid,
                text=full_text,
                quick_replies=quick_replies,
            )
            return
        else:
            if sess:
                sess.state = FlowState.WAITING_FOR_NEW_CUSTOMER_ADDRESS
            cust_name = cust.name if cust and cust.name else "estimado cliente"
            await adapter.send_text_message(
                igsid,
                f"¡Hola de nuevo, **{cust_name}**! 👋 Qué gusto atenderte.\n\n"
                "Aún no tienes direcciones registradas en tu cuenta. Por favor compárteme tu **dirección de entrega completa** (calle, número, colonia y referencias) o comparte tu **ubicación GPS** 📍:",
            )
            return

    elif action_performed == "show_schedule_alternative":
        await adapter.send_quick_replies(
            recipient_igsid=igsid,
            text=respuesta,
            quick_replies=adapter.get_schedule_alternative_quick_replies(),
        )
        return

    elif action_performed == "ask_schedule_text":
        await adapter.send_text_message(recipient_igsid=igsid, text=respuesta)
        return

    elif action_performed == "show_schedule_buttons" or (
        state == FlowState.WAITING_FOR_SCHEDULE
        and not any(k in respuesta.lower() for k in ["indícame la hora", "indicame la hora", "escribe la hora", "hora y el día", "hora y el dia"])
    ):
        cleaned = adapter.clean_text_for_interactive(respuesta, "quick_replies", "schedule")
        await adapter.send_quick_replies(
            recipient_igsid=igsid,
            text=cleaned,
            quick_replies=adapter.get_schedule_quick_replies(),
        )
        return

    elif action_performed == "show_payment_buttons" or state == FlowState.WAITING_FOR_PAYMENT_METHOD:
        cleaned = adapter.clean_text_for_interactive(respuesta, "quick_replies", "payment")
        await adapter.send_quick_replies(
            recipient_igsid=igsid,
            text=cleaned,
            quick_replies=adapter.get_payment_method_quick_replies(),
        )
        return

    elif action_performed == "show_edit_options":
        await adapter.send_quick_replies(
            recipient_igsid=igsid,
            text=respuesta or "✏️ ¿Qué dato deseas modificar de tu pedido?",
            quick_replies=adapter.get_edit_options_quick_replies(),
        )
        return

    elif action_performed == "show_confirmation" or state == FlowState.WAITING_FOR_CONFIRMATION:
        await adapter.send_quick_replies(
            recipient_igsid=igsid,
            text=respuesta,
            quick_replies=adapter.get_confirmation_quick_replies(),
        )
        return

    elif action_performed == "order_created":
        _active_order_sessions.pop(igsid, None)
        clear_cart(igsid)
        order_match = re.search(r"(?:pedido|folio)\s*#?\s*(\d+)", respuesta, re.IGNORECASE)
        if order_match:
            order_id = order_match.group(1)
            await adapter.send_quick_replies(
                recipient_igsid=igsid,
                text=respuesta,
                quick_replies=[
                    {"id": f"cancel_order_client:{order_id}", "title": "❌ Cancelar Pedido"}
                ],
            )
            return
        await adapter.send_text_message(igsid, respuesta)
        return

    # Detección heurística de contexto si no hubo acción explícita
    cleaned_text, interactive_spec = adapter.detect_interactive_elements(
        respuesta,
        igsid=igsid,
        tenant_id=TENANT_ID,
    )

    if interactive_spec:
        if interactive_spec.get("type") == "quick_replies":
            await adapter.send_quick_replies(
                recipient_igsid=igsid,
                text=cleaned_text,
                quick_replies=interactive_spec.get("quick_replies", []),
            )
            return
        elif interactive_spec.get("type") == "button_template":
            q_replies = []
            for btn in interactive_spec.get("buttons", []):
                b_id = btn.get("payload") or btn.get("id", "")
                b_title = btn.get("title", "")[:20]
                if b_id and b_title:
                    q_replies.append({"id": b_id, "title": b_title})
            if q_replies:
                await adapter.send_quick_replies(
                    recipient_igsid=igsid,
                    text=cleaned_text,
                    quick_replies=q_replies,
                )
                return
            await adapter.send_quick_replies(
                recipient_igsid=igsid,
                text=cleaned_text,
                quick_replies=interactive_spec.get("quick_replies", []),
            )
            return

    # Mensaje plano por defecto
    await adapter.send_text_message(igsid, respuesta)
