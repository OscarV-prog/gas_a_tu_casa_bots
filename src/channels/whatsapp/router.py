"""WhatsApp Webhook Router (FastAPI).

Receives webhook verification requests and incoming messages from Meta WhatsApp Cloud API,
delegating conversation flow to the LangGraph sales agent without duplicating business logic.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import PlainTextResponse
from langchain_core.messages import HumanMessage

from src.channels.whatsapp.adapter import WhatsAppAdapter
from src.config.settings import get_settings
from src.graphs.sales_graph import compile_sales_graph
from src.repositories import get_repository
from src.repositories.sqlite_repo import get_db_connection
from src.services.geocoding import resolve_gps_address_to_name, reverse_geocode

logger = logging.getLogger(__name__)

router = APIRouter()
adapter = WhatsAppAdapter()
graph = compile_sales_graph()

TENANT_ID = "petroil"


# Carrito de compras interactivo temporal por usuario de WhatsApp (wa_id -> {prod_id: quantity})
wa_carts: dict[str, dict[str, int]] = {}


def get_user_cart(wa_id: str) -> dict[str, int]:
    """Obtiene el carrito activo del usuario."""
    return wa_carts.setdefault(wa_id, {})


def add_to_cart(wa_id: str, prod_id: str, qty: int = 1) -> dict[str, int]:
    """Agrega o incrementa la cantidad de un producto en el carrito del usuario."""
    cart = get_user_cart(wa_id)
    cart[prod_id] = cart.get(prod_id, 0) + qty
    return cart


def clear_cart(wa_id: str) -> None:
    """Vacía el carrito del usuario."""
    wa_carts[wa_id] = {}


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
            lines.append(f"• *{qty}x {name}* — ${subtotal:,.2f} MXN")

    plural = "s" if total_qty > 1 else ""
    summary_text = (
        "🛒 *Tu selección actual:*\n"
        + "\n".join(lines)
        + f"\n\n💰 *Total acumulado:* ${total_price:,.2f} MXN ({total_qty} cilindro{plural})"
    )
    return summary_text, total_price, total_qty


@router.get("", response_class=PlainTextResponse)
@router.get("/", response_class=PlainTextResponse)
async def verify_webhook(request: Request):
    """WhatsApp Cloud API Webhook verification endpoint (Meta Challenge)."""
    settings = get_settings()
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    expected_token = settings.whatsapp_verify_token or "petroil_gas_webhook_secret"

    if mode == "subscribe" and token == expected_token:
        logger.info("[WhatsApp] Webhook successfully verified with Meta.")
        return challenge or ""

    logger.warning(f"[WhatsApp] Verification failed. Received token: {token}")
    raise HTTPException(status_code=403, detail="Verification token mismatch")


import hashlib
import hmac
import json
import time

# Cache de idempotencia para deduplicar mensajes de WhatsApp (msg_id -> timestamp)
_PROCESSED_MSG_IDS: dict[str, float] = {}
_IDEMPOTENCY_TTL_SECONDS = 600.0  # 10 minutos


def _is_duplicate_message(msg_id: str) -> bool:
    """Verifica si el mensaje ya fue recibido y procesado recientemente."""
    if not msg_id:
        return False
    now = time.time()
    # Limpieza periódica de mensajes antiguos
    if len(_PROCESSED_MSG_IDS) > 2000:
        expired_keys = [k for k, ts in _PROCESSED_MSG_IDS.items() if now - ts > _IDEMPOTENCY_TTL_SECONDS]
        for k in expired_keys:
            _PROCESSED_MSG_IDS.pop(k, None)

    if msg_id in _PROCESSED_MSG_IDS and (now - _PROCESSED_MSG_IDS[msg_id]) < _IDEMPOTENCY_TTL_SECONDS:
        return True

    _PROCESSED_MSG_IDS[msg_id] = now
    return False


def verify_whatsapp_signature(body_bytes: bytes, signature_header: str | None, app_secret: str) -> bool:
    """Valida la firma HMAC-SHA256 (X-Hub-Signature-256) enviada por Meta."""
    if not app_secret:
        return True  # Si no está configurado el secreto en local, se permite el paso
    if not signature_header or not signature_header.startswith("sha256="):
        return False

    received_hash = signature_header[len("sha256="):]
    expected_hash = hmac.new(app_secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(received_hash, expected_hash)


@router.post("")
@router.post("/")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receive real-time incoming messages and events from WhatsApp Cloud API."""
    settings = get_settings()
    body_bytes = await request.body()

    # 1. Validación Criptográfica de Firma HMAC-SHA256 (Meta X-Hub-Signature-256)
    if settings.whatsapp_app_secret:
        sig_header = request.headers.get("X-Hub-Signature-256")
        if not verify_whatsapp_signature(body_bytes, sig_header, settings.whatsapp_app_secret):
            logger.warning("[WhatsApp Webhook] Firma X-Hub-Signature-256 INVÁLIDA. Petición rechazada.")
            raise HTTPException(status_code=401, detail="Invalid WhatsApp webhook signature")

    try:
        payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
    except Exception:
        return {"status": "error", "detail": "Invalid JSON"}

    events = adapter.parse_webhook_events(payload, default_tenant_id=TENANT_ID)
    if not events:
        return {"status": "ok", "message": "No actionable user events"}

    queued_count = 0
    for ev in events:
        msg_id = ev.get("msg_id", "")
        # 2. Control de Idempotencia contra reintentos de Meta
        if msg_id and _is_duplicate_message(msg_id):
            logger.info(f"[WhatsApp Webhook] Mensaje duplicado omitido por idempotencia: {msg_id}")
            continue
        background_tasks.add_task(process_whatsapp_event, ev)
        queued_count += 1

    return {"status": "ok", "events_queued": queued_count}



from pathlib import Path
import time
from src.models.customer import CustomerAddress
from src.services.audio_transcription import transcribe_audio_file
from src.services.flow_router import flow_router, clear_session, FlowState
from src.services.notifications import notify_driver

# Mensaje de seguridad estricto contra inyecciones y consultas indebidas
MENSAJE_SEGURIDAD_ATENCION_WA = (
    "Entiendo, pero no puedo decodificar, ejecutar ni procesar payloads de ese tipo. 🙅‍♂️\n\n"
    "Mi función como asistente de *Gas a Tu Puerta - Petroil* es únicamente de atención al cliente:\n\n"
    "• 🟢 *Realizar un pedido* de gas (cilindro o tanque estacionario)\n"
    "• 🔵 *Consultar el estatus* de tu pedido (folio o teléfono)\n"
    "• ❌ *Cancelar* un pedido tuyo\n\n"
    "No tengo capacidad ni autorización para ejecutar código, decodificar datos ni acceder a la base de datos de forma arbitraria.\n\n"
    "¿Te gustaría que te ayude con tu pedido de gas? 😊"
)

# Estado en memoria para comentarios de texto opcionales posteriores a la encuesta (wa_id -> {"order_id": int, "time": float})
_AWAITING_RATING_COMMENTS: dict[str, dict[str, Any]] = {}


async def process_whatsapp_event(event: dict[str, Any]) -> None:
    """Process a single incoming WhatsApp event asynchronously using the deterministic router."""
    wa_id = event["wa_id"]
    if not wa_id:
        return

    msg_id = event.get("msg_id", "")
    if msg_id:
        await adapter.mark_as_read(msg_id)

    phone_10 = WhatsAppAdapter.extract_10_digit_phone(wa_id)
    thread_id = f"whatsapp:{TENANT_ID}:{wa_id}"
    repo = get_repository()

    # -------------------------------------------------------------------------
    # 1. Manejo de Calificación / Encuestas de Entrega (CSAT)
    # -------------------------------------------------------------------------
    interactive_id = event.get("interactive_id") or ""
    if interactive_id.startswith("rate_driver:"):
        parts = interactive_id.split(":")
        order_id = int(parts[1])
        stars = max(1, min(5, int(parts[2])))

        order = repo.get_order_by_id(TENANT_ID, order_id)
        if order:
            repo.save_order_rating(
                tenant_id=TENANT_ID,
                order_id=order_id,
                driver_id=order.driver_id,
                customer_id=order.customer_id,
                rating=stars,
            )

            driver_name = "tu repartidor"
            if order.driver_id:
                d = repo.get_driver(order.driver_id)
                if d:
                    driver_name = d.name

            stars_str = "⭐" * stars
            if stars >= 4:
                body_msg = (
                    f"🌟 *¡Muchas gracias por calificar con {stars_str}!* ({stars}/5)\n\n"
                    f"¿Qué fue lo que más te agradó del servicio de {driver_name}?"
                )
                sections = [{
                    "title": "Aspectos Destacados",
                    "rows": [
                        {"id": f"rate_tag:{order_id}:Rapidez", "title": "⚡ Rapidez y puntualidad"},
                        {"id": f"rate_tag:{order_id}:Amabilidad", "title": "😊 Trato amable"},
                        {"id": f"rate_tag:{order_id}:Seguridad", "title": "🛡️ Cuidado y seguridad"},
                        {"id": f"rate_tag:{order_id}:Impecable", "title": "✨ Servicio impecable"},
                        {"id": f"rate_tag:{order_id}:Omitido", "title": "⏩ Finalizar sin detalles"},
                    ]
                }]
            else:
                body_msg = (
                    f"🙏 *Agradecemos tu calificación de {stars_str}* ({stars}/5)\n\n"
                    f"Lamentamos que tu experiencia con {driver_name} no haya sido óptima.\n"
                    "¿En qué aspecto podemos mejorar?"
                )
                sections = [{
                    "title": "Aspectos a Mejorar",
                    "rows": [
                        {"id": f"rate_tag:{order_id}:Demora", "title": "⏳ Demora en la entrega"},
                        {"id": f"rate_tag:{order_id}:Actitud", "title": "🙁 Actitud del chofer"},
                        {"id": f"rate_tag:{order_id}:Cilindro", "title": "📦 Problema con cilindro"},
                        {"id": f"rate_tag:{order_id}:Cobro", "title": "💵 Cobro o cambio"},
                        {"id": f"rate_tag:{order_id}:Omitido", "title": "⏩ Finalizar sin detalles"},
                    ]
                }]

            await adapter.send_interactive_list(
                recipient_wa_id=wa_id,
                body_text=body_msg,
                button_label="Seleccionar Detalle",
                sections=sections,
            )
            return

    if interactive_id.startswith("rate_tag:"):
        parts = interactive_id.split(":")
        order_id = int(parts[1])
        tag = parts[2]

        tag_labels = {
            "Rapidez": "⚡ Rapidez y puntualidad",
            "Amabilidad": "😊 Trato amable y cordial",
            "Seguridad": "🛡️ Cuidado y manejo seguro",
            "Impecable": "✨ Servicio impecable",
            "Demora": "⏳ Demora o tiempo de espera",
            "Actitud": "🙁 Actitud o atención del chofer",
            "Cilindro": "📦 Estado del cilindro",
            "Cobro": "💵 Inconveniente con el cobro/cambio",
            "Omitido": "Servicio evaluado",
        }
        tag_display = tag_labels.get(tag, tag)
        feedback_to_save = "" if tag == "Omitido" else tag_display
        if feedback_to_save:
            repo.update_order_rating_feedback(TENANT_ID, order_id, feedback_tag=feedback_to_save)

        rating_data = repo.get_order_rating(TENANT_ID, order_id)
        stars_val = rating_data.get("rating", 5) if rating_data else 5
        stars_str = "⭐" * stars_val

        _AWAITING_RATING_COMMENTS[wa_id] = {
            "order_id": order_id,
            "time": time.time(),
        }

        detalle_str = f"\n💬 *Aspecto registrado:* {tag_display}" if feedback_to_save else ""
        msg_final = (
            f"✅ *¡ENCUESTA COMPLETADA CON ÉXITO!*\n\n"
            f"⭐ *Calificación:* {stars_str} ({stars_val}/5){detalle_str}\n\n"
            "¡Muchas gracias por tu tiempo y valiosa opinión! Nos ayuda a premiar a nuestros mejores choferes y mejorar día a día. ¡Estamos a tus órdenes! ⛽🌟\n\n"
            "_💡 Opcional: Si deseas agregar algún comentario o sugerencia escrita sobre tu repartidor, puedes enviarla en tu siguiente mensaje._"
        )
        await adapter.send_text_message(wa_id, msg_final)
        return

    # Soporte para calificación enviada como texto plano (ej. '5', '4', 'Excelente', '⭐⭐⭐⭐⭐')
    raw_text_rating = (event.get("text") or "").strip().lower()
    if not interactive_id and raw_text_rating:
        parsed_stars = None
        if raw_text_rating in ("5", "5 estrellas", "⭐ 5", "⭐⭐⭐⭐⭐", "excelente", "cinco"):
            parsed_stars = 5
        elif raw_text_rating in ("4", "4 estrellas", "⭐ 4", "⭐⭐⭐⭐", "bueno", "cuatro"):
            parsed_stars = 4
        elif raw_text_rating in ("3", "3 estrellas", "⭐ 3", "⭐⭐⭐", "regular", "tres"):
            parsed_stars = 3
        elif raw_text_rating in ("2", "2 estrellas", "⭐ 2", "⭐⭐", "malo", "dos"):
            parsed_stars = 2
        elif raw_text_rating in ("1", "1 estrella", "⭐ 1", "⭐", "muy malo", "uno"):
            parsed_stars = 1

        if parsed_stars is not None:
            delivered_orders = []
            if phone_10:
                delivered_orders = [o for o in repo.get_orders_by_customer_phone(TENANT_ID, phone_10) if o.status == "delivered"]
            if not delivered_orders:
                cust = repo.get_customer(TENANT_ID, "whatsapp", wa_id)
                if cust:
                    delivered_orders = [o for o in repo.get_orders_by_customer(TENANT_ID, cust.id) if o.status == "delivered"]

            if delivered_orders:
                last_delivered = delivered_orders[0]
                existing_r = repo.get_order_rating(TENANT_ID, last_delivered.id)
                if not existing_r or not existing_r.get("rating"):
                    repo.save_order_rating(
                        tenant_id=TENANT_ID,
                        order_id=last_delivered.id,
                        driver_id=last_delivered.driver_id,
                        customer_id=last_delivered.customer_id,
                        rating=parsed_stars,
                    )
                    driver_name = "tu repartidor"
                    if last_delivered.driver_id:
                        d = repo.get_driver(last_delivered.driver_id)
                        if d:
                            driver_name = d.name

                    stars_str = "⭐" * parsed_stars
                    if parsed_stars >= 4:
                        body_msg = (
                            f"🌟 *¡Muchas gracias por calificar con {stars_str}!* ({parsed_stars}/5)\n\n"
                            f"¿Qué fue lo que más te agradó del servicio de {driver_name}?"
                        )
                        sections = [{
                            "title": "Aspectos Destacados",
                            "rows": [
                                {"id": f"rate_tag:{last_delivered.id}:Rapidez", "title": "⚡ Rapidez y puntualidad"},
                                {"id": f"rate_tag:{last_delivered.id}:Amabilidad", "title": "😊 Trato amable"},
                                {"id": f"rate_tag:{last_delivered.id}:Seguridad", "title": "🛡️ Cuidado y seguridad"},
                                {"id": f"rate_tag:{last_delivered.id}:Impecable", "title": "✨ Servicio impecable"},
                                {"id": f"rate_tag:{last_delivered.id}:Omitido", "title": "⏩ Finalizar sin detalles"},
                            ]
                        }]
                    else:
                        body_msg = (
                            f"🙏 *Agradecemos tu calificación de {stars_str}* ({parsed_stars}/5)\n\n"
                            f"Lamentamos que tu experiencia con {driver_name} no haya sido óptima.\n"
                            "¿En qué aspecto podemos mejorar?"
                        )
                        sections = [{
                            "title": "Aspectos a Mejorar",
                            "rows": [
                                {"id": f"rate_tag:{last_delivered.id}:Demora", "title": "⏳ Demora en la entrega"},
                                {"id": f"rate_tag:{last_delivered.id}:Actitud", "title": "🙁 Actitud del chofer"},
                                {"id": f"rate_tag:{last_delivered.id}:Cilindro", "title": "📦 Problema con cilindro"},
                                {"id": f"rate_tag:{last_delivered.id}:Cobro", "title": "💵 Cobro o cambio"},
                                {"id": f"rate_tag:{last_delivered.id}:Omitido", "title": "⏩ Finalizar sin detalles"},
                            ]
                        }]

                    await adapter.send_interactive_list(
                        recipient_wa_id=wa_id,
                        body_text=body_msg,
                        button_label="Seleccionar Detalle",
                        sections=sections,
                    )
                    return

    # -------------------------------------------------------------------------
    # 2. Manejo de Notas de Voz / Audio
    # -------------------------------------------------------------------------
    msg_type = event.get("type", "text")
    if msg_type in ("audio", "voice"):
        media_id = event.get("media_id")
        audio_dir = Path(__file__).parent.parent.parent.parent / "uploads" / "voice_notes"
        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_path = audio_dir / f"voice_wa_{wa_id}_{int(time.time())}.ogg"

        transcription = ""
        if media_id:
            downloaded = await adapter.download_media(media_id, audio_path)
            if downloaded:
                transcription = await transcribe_audio_file(downloaded)

        if transcription:
            event["text"] = transcription
        else:
            await adapter.send_text_message(
                wa_id,
                "🎙️ He recibido tu nota de voz, pero no fue posible transcribirla con claridad. "
                "Por favor intenta escribir tu mensaje o enviar un nuevo audio."
            )
            return

    # -------------------------------------------------------------------------
    # 2.1 Manejo de Imágenes (Catálogo Visual)
    # -------------------------------------------------------------------------
    if msg_type == "image":
        media_id = event.get("media_id")
        img_dir = Path(__file__).parent.parent.parent.parent / "uploads" / "customer_images"
        img_dir.mkdir(parents=True, exist_ok=True)
        img_path = img_dir / f"img_wa_{wa_id}_{int(time.time())}.jpg"

        if media_id:
            await adapter.download_media(media_id, img_path)

        caption = (event.get("text") or "").strip()
        if caption and caption != "[Imagen enviada por el cliente]":
            event["text"] = caption
        else:
            sections = adapter.get_cylinder_catalog_list_sections(TENANT_ID)
            await adapter.send_interactive_list(
                recipient_wa_id=wa_id,
                body_text=(
                    "📸 *¡Imagen recibida!*\n\n"
                    "Si deseas cotizar o solicitar un cilindro de gas o servicio estacionario, "
                    "selecciona una de las capacidades en el catálogo a continuación o descríbenos tu pedido:"
                ),
                button_label="Ver Catálogo",
                sections=sections,
            )
            return

    # -------------------------------------------------------------------------
    # 3. Manejo de Ubicación GPS
    # -------------------------------------------------------------------------
    loc = event.get("location")
    if loc and loc.get("latitude") is not None and loc.get("longitude") is not None:
        lat = float(loc["latitude"])
        lng = float(loc["longitude"])
        flow_res = await flow_router.process_event(
            session_id=thread_id,
            location={"latitude": lat, "longitude": lng},
            channel="whatsapp",
            channel_user_id=wa_id,
            tenant_id=TENANT_ID,
        )
        await _dispatch_flow_response_whatsapp(flow_res, wa_id=wa_id, phone_10=phone_10)
        return

    # -------------------------------------------------------------------------
    # 4. Mapeo de Acciones Interactivas de Botones y Listas
    # -------------------------------------------------------------------------
    texto_usuario = (event.get("text") or "").strip()

    # 4.0 Comentario posterior a la calificación CSAT
    rating_ctx = _AWAITING_RATING_COMMENTS.get(wa_id)
    if rating_ctx and (time.time() - rating_ctx.get("time", 0)) < 600 and texto_usuario:
        texto_lower = texto_usuario.lower()
        es_nuevo_pedido = any(k in texto_lower for k in ["quiero", "cilindro", "estacionario", "tanque", "litros", "pedir", "orden", "hola", "/start"])
        order_id_rating = rating_ctx.get("order_id")
        if not es_nuevo_pedido and order_id_rating:
            _AWAITING_RATING_COMMENTS.pop(wa_id, None)
            repo.update_order_rating_feedback(TENANT_ID, order_id_rating, comment=texto_usuario)
            await adapter.send_text_message(
                wa_id,
                "📝 *¡Comentario registrado!*\n\n"
                "Muchas gracias por compartirnos tu opinión detallada. Tus comentarios han sido guardados para el equipo de calidad de Petroil. ¡Que tengas un excelente día! ⛽🌟"
            )
            return
        else:
            _AWAITING_RATING_COMMENTS.pop(wa_id, None)

    if interactive_id:
        if interactive_id == "client_svc:cilindro":
            clear_cart(wa_id)
            sections = adapter.get_cylinder_catalog_list_sections(TENANT_ID)
            await adapter.send_interactive_list(
                recipient_wa_id=wa_id,
                body_text="🛒 *Catálogo de Cilindros de Gas LP*\nSelecciona la capacidad que necesitas en el menú a continuación:",
                button_label="Ver Opciones",
                sections=sections,
            )
            return

        elif interactive_id == "client_svc:estacionario":
            clear_cart(wa_id)
            flow_res = await flow_router.process_event(
                session_id=thread_id,
                callback_data="client_svc:estacionario",
                channel="whatsapp",
                channel_user_id=wa_id,
                tenant_id=TENANT_ID,
            )
            await _dispatch_flow_response_whatsapp(flow_res, wa_id=wa_id, phone_10=phone_10)
            return

        elif interactive_id.startswith("cart_add:"):
            parts = interactive_id.split(":")
            prod_id = parts[1]
            qty = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
            cart = add_to_cart(wa_id, prod_id, qty)
            summary_text, total_price, total_qty = format_cart_summary(cart, TENANT_ID)

            plural = "s" if total_qty > 1 else ""
            body = (
                f"{summary_text}\n\n"
                f"¿Deseas agregar más cilindros a tu pedido o continuar con tu entrega?"
            )
            btn_checkout_title = f"✅ Continuar ({total_qty})" if len(f"✅ Continuar ({total_qty})") <= 20 else "✅ Continuar"
            buttons = [
                {"id": "cart_more", "title": "➕ Agregar Otro"},
                {"id": "cart_checkout", "title": btn_checkout_title},
                {"id": "cart_clear", "title": "🗑️ Vaciar"},
            ]
            await adapter.send_interactive_buttons(
                recipient_wa_id=wa_id,
                body_text=body,
                buttons=buttons,
            )
            return

        elif interactive_id == "cart_more":
            cart = get_user_cart(wa_id)
            summary_text, _, total_qty = format_cart_summary(cart, TENANT_ID) if cart else ("", 0, 0)
            sections = adapter.get_cylinder_catalog_list_sections(TENANT_ID)
            body = (
                f"{summary_text}\n\nSelecciona el siguiente cilindro que deseas agregar a tu pedido:"
                if summary_text
                else "🛒 *Catálogo de Cilindros de Gas LP*\nSelecciona la capacidad que necesitas en el menú:"
            )
            await adapter.send_interactive_list(
                recipient_wa_id=wa_id,
                body_text=body,
                button_label="Agregar Cilindro",
                sections=sections,
            )
            return

        elif interactive_id == "cart_clear":
            clear_cart(wa_id)
            sections = adapter.get_cylinder_catalog_list_sections(TENANT_ID)
            await adapter.send_interactive_list(
                recipient_wa_id=wa_id,
                body_text="🗑️ *Carrito vaciado.*\n\nSelecciona los cilindros que necesitas en el menú a continuación:",
                button_label="Ver Catálogo",
                sections=sections,
            )
            return

        elif interactive_id == "cart_checkout":
            cart = get_user_cart(wa_id)
            if not cart or sum(cart.values()) == 0:
                sections = adapter.get_cylinder_catalog_list_sections(TENANT_ID)
                await adapter.send_interactive_list(
                    recipient_wa_id=wa_id,
                    body_text="🛒 *Tu carrito está vacío.*\nPor favor selecciona al menos un cilindro para continuar:",
                    button_label="Ver Opciones",
                    sections=sections,
                )
                return

            prods = repo.get_all_products(TENANT_ID)
            prods_by_id = {p.id: p for p in prods}
            items_str = ", ".join(
                f"{qty}x {prods_by_id[pid].name if pid in prods_by_id else pid}"
                for pid, qty in cart.items()
                if qty > 0
            )
            clear_cart(wa_id)
            flow_res = await flow_router.process_event(
                session_id=thread_id,
                text=f"Deseo ordenar los siguientes productos seleccionados de tu catálogo: {items_str}.",
                channel="whatsapp",
                channel_user_id=wa_id,
                tenant_id=TENANT_ID,
            )
            await _dispatch_flow_response_whatsapp(flow_res, wa_id=wa_id, phone_10=phone_10)
            return

        elif interactive_id.startswith("client_sch:") or interactive_id.startswith("client_sch_"):
            flow_res = await flow_router.process_event(
                session_id=thread_id,
                callback_data=interactive_id,
                channel="whatsapp",
                channel_user_id=wa_id,
                tenant_id=TENANT_ID,
            )
            await _dispatch_flow_response_whatsapp(flow_res, wa_id=wa_id, phone_10=phone_10)
            return

        elif interactive_id in ("client_pay:efectivo", "client_pay:terminal"):
            flow_res = await flow_router.process_event(
                session_id=thread_id,
                callback_data=interactive_id,
                channel="whatsapp",
                channel_user_id=wa_id,
                tenant_id=TENANT_ID,
            )
            await _dispatch_flow_response_whatsapp(flow_res, wa_id=wa_id, phone_10=phone_10)
            return

        elif interactive_id in ("client_confirm:yes", "client_confirm:edit", "client_confirm:cancel"):
            if interactive_id == "client_confirm:cancel":
                clear_cart(wa_id)
            flow_res = await flow_router.process_event(
                session_id=thread_id,
                callback_data=interactive_id,
                channel="whatsapp",
                channel_user_id=wa_id,
                tenant_id=TENANT_ID,
            )
            await _dispatch_flow_response_whatsapp(flow_res, wa_id=wa_id, phone_10=phone_10)
            return

        elif interactive_id.startswith("client_edit:"):
            flow_res = await flow_router.process_event(
                session_id=thread_id,
                callback_data=interactive_id,
                channel="whatsapp",
                channel_user_id=wa_id,
                tenant_id=TENANT_ID,
            )
            await _dispatch_flow_response_whatsapp(flow_res, wa_id=wa_id, phone_10=phone_10)
            return

        elif interactive_id.startswith("cancel_order_client:"):
            order_id = int(interactive_id.split(":")[1])
            order = repo.get_order_by_id(TENANT_ID, order_id)
            if not order:
                await adapter.send_text_message(wa_id, "⚠️ Pedido no encontrado.")
                return

            if order.status == "delivered":
                await adapter.send_text_message(wa_id, "⚠️ Tu pedido ya fue entregado y no puede cancelarse.")
                return

            if order.status == "cancelled":
                await adapter.send_text_message(wa_id, f"⚠️ El pedido #{order_id} ya se encuentra cancelado.")
                return

            # Preguntar confirmación previa de cancelación
            buttons = adapter.get_order_cancel_confirm_buttons(order_id)
            confirm_msg = (
                f"⚠️ *¿Estás seguro de que deseas cancelar tu pedido #{order_id}?*\n\n"
                f"📍 *Entrega:* {order.delivery_address}\n"
                f"💰 *Total a pagar:* ${order.total_amount:.2f} ({order.payment_method})\n\n"
                "Si confirmas la cancelación, la unidad de reparto asignada será liberada y tu entrega quedará suspendida definitivamente."
            )
            await adapter.send_interactive_buttons(
                recipient_wa_id=wa_id,
                body_text=confirm_msg,
                buttons=buttons,
            )
            return

        elif interactive_id.startswith("keep_order_client:"):
            order_id = int(interactive_id.split(":")[1])
            order = repo.get_order_by_id(TENANT_ID, order_id)
            if not order:
                await adapter.send_text_message(wa_id, "⚠️ Pedido no encontrado.")
                return

            from src.tools.get_order_status import format_clean_driver_status
            from src.services.notifications import _format_markdown_for_whatsapp
            status_text = format_clean_driver_status(order, repo=repo)
            wa_text = f"✅ *¡Excelente! Tu pedido #{order_id} sigue activo.*\n\n" + _format_markdown_for_whatsapp(status_text)
            buttons = adapter.get_order_active_buttons(order_id)
            await adapter.send_interactive_buttons(
                recipient_wa_id=wa_id,
                body_text=wa_text,
                buttons=buttons,
            )
            return

        elif interactive_id.startswith("confirm_cancel_order_client:"):
            order_id = int(interactive_id.split(":")[1])
            order = repo.get_order_by_id(TENANT_ID, order_id)
            if not order:
                await adapter.send_text_message(wa_id, "⚠️ Pedido no encontrado.")
                return

            if order.status == "delivered":
                await adapter.send_text_message(wa_id, "⚠️ Tu pedido ya fue entregado y no puede cancelarse.")
                return

            if order.status == "cancelled":
                await adapter.send_text_message(wa_id, f"⚠️ El pedido #{order_id} ya se encuentra cancelado.")
                return

            # Eliminar ubicación en tiempo real si existía
            if order.live_location_message_id and order.live_location_chat_id:
                from src.services.notifications import remove_client_live_location
                remove_client_live_location(order.live_location_chat_id, order.live_location_message_id)
            repo.clear_order_live_location(TENANT_ID, order_id)
            from src.repositories.identity_store import identity_store
            identity_store.clear_order_live_location(order_id)

            # Cancelar orden en BD y liberar chofer
            repo.cancel_order(TENANT_ID, order_id, cancelled_by="el cliente")

            # Limpiar botones anteriores de cliente y chofer
            from src.services.notifications import cleanup_client_order_buttons
            cleanup_client_order_buttons(order_id, keep_message_id=None)

            # Notificar al chofer asignado si tiene Telegram y limpiar botones activos de su chat
            if order.driver_id:
                driver = repo.get_driver(order.driver_id)
                if driver and driver.telegram_user_id:
                    from src.services.notifications import notify_driver_order_cancelled
                    notify_driver_order_cancelled(
                        tenant_id=TENANT_ID,
                        order_id=order_id,
                        driver_telegram_user_id=driver.telegram_user_id,
                        customer_name=order.customer_name,
                        delivery_address=order.delivery_address,
                        cancelled_by="el cliente desde WhatsApp",
                    )

            await adapter.send_text_message(
                wa_id,
                f"❌ *Tu pedido #{order_id} ha sido cancelado exitosamente.*\n\n"
                "Si deseas programar un nuevo pedido en el futuro, solo envíame un mensaje. ¡Estamos a tus órdenes! ⛽"
            )
            return

        elif interactive_id.startswith("check_order_status:"):
            order_id = int(interactive_id.split(":")[1])
            order = repo.get_order_by_id(TENANT_ID, order_id)
            if not order:
                await adapter.send_text_message(wa_id, "⚠️ Pedido no encontrado.")
                return

            from src.tools.get_order_status import format_clean_driver_status
            from src.services.notifications import _format_markdown_for_whatsapp
            status_text = format_clean_driver_status(order, repo=repo)
            wa_text = _format_markdown_for_whatsapp(status_text)

            status_raw = str(getattr(order, "status", "")).lower()
            if status_raw in ("confirmed", "confirmado", "in_route", "en_ruta", "scheduled", "programado", "assigned"):
                buttons = adapter.get_order_active_buttons(order_id)
                await adapter.send_interactive_buttons(
                    recipient_wa_id=wa_id,
                    body_text=wa_text,
                    buttons=buttons,
                )
            else:
                await adapter.send_text_message(wa_id, wa_text)
            return

        elif interactive_id == "client_addr:del_menu":
            phone_to_search = phone_10
            cust = repo.get_customer_by_phone(TENANT_ID, phone_to_search) if phone_to_search else None
            if not cust:
                cust = repo.get_customer(TENANT_ID, "whatsapp", wa_id)

            addrs = cust.addresses if (cust and cust.addresses) else []
            if not addrs:
                await adapter.send_text_message(
                    wa_id,
                    "ℹ️ No se encontraron direcciones guardadas en tu cuenta para eliminar."
                )
                return

            sections = adapter.get_delete_addresses_list_sections(addrs)
            body = (
                "🗑️ *Eliminar Dirección Guardada*\n\n"
                "Selecciona en el menú a continuación la dirección que deseas borrar de tu cuenta permanente:"
            )
            await adapter.send_interactive_list(
                recipient_wa_id=wa_id,
                body_text=body,
                button_label="Eliminar Dirección",
                sections=sections,
            )
            return

        elif interactive_id == "del_addr_cancel":
            cust = repo.get_customer_by_phone(TENANT_ID, phone_10) if phone_10 else None
            if not cust:
                cust = repo.get_customer(TENANT_ID, "whatsapp", wa_id)
            addrs = cust.addresses if (cust and cust.addresses) else []
            msg = "ℹ️ *Operación cancelada.*\nTu dirección se mantiene guardada en tu cuenta.\n\n¿A cuál de tus direcciones deseas que enviemos tu pedido?"
            if len(addrs) == 1:
                buttons = adapter.get_customer_addresses_buttons(addrs)
                await adapter.send_interactive_buttons(recipient_wa_id=wa_id, body_text=msg, buttons=buttons)
            elif len(addrs) > 1:
                sections = adapter.get_customer_addresses_list_sections(addrs)
                await adapter.send_interactive_list(recipient_wa_id=wa_id, body_text=msg, button_label="Ver Direcciones", sections=sections)
            else:
                await adapter.send_text_message(wa_id, msg)
            return

        elif interactive_id.startswith("del_addr:") and not interactive_id.startswith("del_addr_confirm:"):
            addr_id_str = interactive_id.split(":", 1)[1]
            if addr_id_str.isdigit():
                addr_id = int(addr_id_str)
                cust = repo.get_customer_by_phone(TENANT_ID, phone_10) if phone_10 else None
                if not cust:
                    cust = repo.get_customer(TENANT_ID, "whatsapp", wa_id)

                target_addr = None
                if cust and cust.addresses:
                    target_addr = next((a for a in cust.addresses if a.id == addr_id), None)

                addr_display = target_addr.address if target_addr else f"Dirección #{addr_id}"
                clean_display = resolve_gps_address_to_name(addr_display.strip())
                clean_display = re.sub(r"^(?:\[(?:Nueva\s*Direcci[oó]n|Direcci[oó]n(?:\s*\d+)?|Principal)\]\s*)+", "", clean_display, flags=re.I).strip()

                confirm_body = (
                    "⚠️ *¿Estás seguro de que deseas eliminar esta dirección?*\n\n"
                    f"📍 *Dirección seleccionada:*\n`{clean_display}`\n\n"
                    "⚠️ _Esta acción no se puede deshacer. Por favor confirma tu decisión:_"
                )
                confirm_buttons = [
                    {"id": f"del_addr_confirm:{addr_id}", "title": "🗑️ Sí, eliminar"},
                    {"id": "del_addr_cancel", "title": "❌ No, cancelar"},
                ]
                await adapter.send_interactive_buttons(
                    recipient_wa_id=wa_id,
                    body_text=confirm_body,
                    buttons=confirm_buttons,
                )
                return

        elif interactive_id.startswith("del_addr_confirm:"):
            addr_id_str = interactive_id.split(":", 1)[1]
            if addr_id_str.isdigit():
                addr_id = int(addr_id_str)
                cust = repo.get_customer_by_phone(TENANT_ID, phone_10) if phone_10 else None
                if not cust:
                    cust = repo.get_customer(TENANT_ID, "whatsapp", wa_id)

                customer_id = cust.id if cust else None
                addr_text_deleted = ""

                with get_db_connection() as conn:
                    row_addr = conn.execute("SELECT * FROM customer_addresses WHERE id = ?", (addr_id,)).fetchone()
                    if row_addr:
                        addr_text_deleted = row_addr["address"]
                        if not customer_id:
                            customer_id = row_addr["customer_id"]

                if customer_id:
                    repo.delete_customer_address(customer_id, addr_id, phone=phone_10, address_text=addr_text_deleted)
                    remaining = repo.get_customer_addresses(customer_id)
                    clean_deleted = resolve_gps_address_to_name(addr_text_deleted.strip()) if addr_text_deleted else ""
                    clean_deleted = re.sub(r"^(?:\[(?:Nueva\s*Direcci[oó]n|Direcci[oó]n(?:\s*\d+)?|Principal)\]\s*)+", "", clean_deleted, flags=re.I).strip()
                    addr_display = clean_deleted or f"#{addr_id}"

                    if remaining:
                        if len(remaining) == 1:
                            buttons = adapter.get_customer_addresses_buttons(remaining)
                            body = (
                                f"✅ *Dirección eliminada con éxito:*\n📍 `{addr_display}`\n\n"
                                "¿A cuál de tus direcciones restantes deseas que enviemos tu pedido o prefieres ingresar una nueva?"
                            )
                            await adapter.send_interactive_buttons(
                                recipient_wa_id=wa_id,
                                body_text=body,
                                buttons=buttons,
                            )
                        else:
                            sections = adapter.get_customer_addresses_list_sections(remaining)
                            body = (
                                f"✅ *Dirección eliminada con éxito:*\n📍 `{addr_display}`\n\n"
                                "¿A cuál de tus direcciones restantes deseas que enviemos tu pedido o prefieres ingresar una nueva?"
                            )
                            await adapter.send_interactive_list(
                                recipient_wa_id=wa_id,
                                body_text=body,
                                button_label="Ver Direcciones",
                                sections=sections,
                            )
                    else:
                        msg = (
                            f"✅ *Dirección eliminada con éxito:*\n📍 `{addr_display}`\n\n"
                            "Ya no tienes más direcciones guardadas en tu cuenta. Por favor escribe tu nueva dirección de entrega completa o comparte tu ubicación GPS 📍 para continuar con tu pedido:"
                        )
                        await adapter.send_text_message(wa_id, msg)
                    return
                else:
                    await adapter.send_text_message(
                        wa_id,
                        "⚠️ No se pudo localizar la dirección a eliminar. Por favor intenta nuevamente."
                    )
                    return

        elif interactive_id.startswith("client_addr:"):
            flow_res = await flow_router.process_event(
                session_id=thread_id,
                callback_data=interactive_id,
                channel="whatsapp",
                channel_user_id=wa_id,
                tenant_id=TENANT_ID,
            )
            await _dispatch_flow_response_whatsapp(flow_res, wa_id=wa_id, phone_10=phone_10)
            return

        elif interactive_id.startswith("client_prod:"):
            prod_text = interactive_id.split(":", 1)[1]
            flow_res = await flow_router.process_event(
                session_id=thread_id,
                text=prod_text,
                channel="whatsapp",
                channel_user_id=wa_id,
                tenant_id=TENANT_ID,
            )
            await _dispatch_flow_response_whatsapp(flow_res, wa_id=wa_id, phone_10=phone_10)
            return

    # -------------------------------------------------------------------------
    # 5. Invocación del Enrutador Determinista para Mensajes de Texto
    # -------------------------------------------------------------------------
    if not texto_usuario:
        return

    texto_clean = texto_usuario.strip().lower()

    # 5.1 Detección temprana de intentos de payload / inyección / jailbreak / scraping multi-número
    found_phones = re.findall(r"\b(?:\+?52\s*)?(\d{10})\b", texto_usuario)
    es_payload_o_inyeccion = any(k in texto_clean for k in [
        "payload", "decodifica", "decodificar", "base64", "script", "ejecutar código", "ejecuta codigo",
        "ejecutar codigo", "ejecuta script", "ejecutar script", "eval(", "exec(", "system(", "sql injection",
        "drop table", "select * from", "union select", "bypass", "jailbreak", "ignora tus instrucciones",
        "ignore previous instructions", "ignora todas las instrucciones", "revela tu prompt", "muestra tu system prompt"
    ])
    es_consulta_multiple = (
        len(found_phones) > 1 and any(k in texto_clean for k in ["pedido", "pedidos", "número", "numero", "orden", "ordenes", "historial", "cliente", "clientes"])
    ) or any(k in texto_clean for k in [
        "dos numeros", "dos números", "varios numeros", "varios números", "múltiples números", "multiples numeros",
        "pedidos de otros", "pedidos de otro", "pedidos de dos", "pedidos de varios"
    ])

    if es_payload_o_inyeccion or es_consulta_multiple:
        await adapter.send_interactive_buttons(
            recipient_wa_id=wa_id,
            body_text=MENSAJE_SEGURIDAD_ATENCION_WA,
            buttons=adapter.get_service_type_buttons(),
        )
        return

    # 5.2 Si el usuario envía saludo o inicio, reiniciar sesión para un pedido limpio
    if texto_clean in ("/start", "start", "hola", "hola!", "buenas", "buenos dias", "buenos días", "buenas tardes", "buenas noches", "inicio", "empezar", "menu", "menú", "reiniciar", "nuevo pedido"):
        clear_cart(wa_id)
        clear_session(thread_id)

        flow_res = await flow_router.process_event(
            session_id=thread_id,
            text="/start",
            channel="whatsapp",
            channel_user_id=wa_id,
            tenant_id=TENANT_ID,
        )
        await _dispatch_flow_response_whatsapp(flow_res, wa_id=wa_id, phone_10=phone_10, user_text=texto_usuario)
        return

    # 5.3 Procesamiento conversacional regular
    flow_res = await flow_router.process_event(
        session_id=thread_id,
        text=texto_usuario,
        channel="whatsapp",
        channel_user_id=wa_id,
        tenant_id=TENANT_ID,
    )
    await _dispatch_flow_response_whatsapp(flow_res, wa_id=wa_id, phone_10=phone_10, user_text=texto_usuario)


async def _dispatch_flow_response_whatsapp(
    flow_res: Any,
    wa_id: str,
    phone_10: str = "",
    user_text: str = "",
) -> None:
    """Dispatch formatted WhatsApp response with interactive buttons/lists where appropriate."""
    try:
        respuesta = flow_res.text if hasattr(flow_res, "text") else str(flow_res)
        action_performed = getattr(flow_res, "action_performed", None)
        state = getattr(flow_res, "state", None)

        # 1. Mapeo directo y prioritario según acción o estado del FlowResponse
        if action_performed == "show_service_buttons":
            await adapter.send_interactive_buttons(
                recipient_wa_id=wa_id,
                body_text=respuesta,
                buttons=adapter.get_service_type_buttons(),
            )
            return

        elif action_performed == "show_cylinder_catalog" or state == FlowState.WAITING_FOR_PRODUCT_OR_QUANTITY:
            sections = adapter.get_cylinder_catalog_list_sections(TENANT_ID)
            await adapter.send_interactive_list(
                recipient_wa_id=wa_id,
                body_text=respuesta or "🛒 *Catálogo de Cilindros de Gas LP*\nSelecciona la capacidad que necesitas en el menú a continuación:",
                button_label="Ver Opciones",
                sections=sections,
            )
            return
        elif state in (
            FlowState.WAITING_FOR_NEW_CUSTOMER_NAME,
            FlowState.WAITING_FOR_NEW_CUSTOMER_ADDRESS,
            FlowState.WAITING_FOR_PHONE,
        ) or action_performed in ("ask_phone", "ask_new_customer_name", "ask_new_customer_address"):
            from src.services.notifications import _format_markdown_for_whatsapp
            await adapter.send_text_message(
                recipient_wa_id=wa_id,
                text=_format_markdown_for_whatsapp(respuesta),
            )
            return

        elif action_performed == "show_address_buttons" or state == FlowState.WAITING_FOR_ADDRESS_SELECTION:
            repo = get_repository()
            phone_to_search = phone_10
            if not phone_to_search and wa_id:
                sess = flow_router.get_session(f"whatsapp:{TENANT_ID}:{wa_id}")
                if sess and sess.draft_order and sess.draft_order.customer_phone:
                    phone_to_search = sess.draft_order.customer_phone

            cust = repo.get_customer_by_phone(TENANT_ID, phone_to_search) if phone_to_search else None
            if not cust and wa_id:
                cust = repo.get_customer(TENANT_ID, "whatsapp", wa_id)

            addrs = cust.addresses if (cust and cust.addresses) else ([CustomerAddress(id=1, address=cust.address, alias="Principal")] if cust and cust.address else [])
            if addrs:
                if len(addrs) == 1:
                    buttons = adapter.get_customer_addresses_buttons(addrs)
                    cleaned = adapter.clean_text_for_interactive(respuesta, "buttons", "addresses")
                    await adapter.send_interactive_buttons(
                        recipient_wa_id=wa_id,
                        body_text=cleaned,
                        buttons=buttons,
                    )
                    return
                else:
                    sections = adapter.get_customer_addresses_list_sections(addrs)
                    cleaned = adapter.clean_text_for_interactive(respuesta, "list", "addresses")
                    await adapter.send_interactive_list(
                        recipient_wa_id=wa_id,
                        body_text=cleaned,
                        button_label="Ver Direcciones",
                        sections=sections,
                    )
                    return

        elif action_performed == "ask_schedule_text":
            await adapter.send_text_message(
                recipient_wa_id=wa_id,
                text=respuesta,
            )
            return

        elif action_performed == "show_schedule_alternative":
            await adapter.send_interactive_buttons(
                recipient_wa_id=wa_id,
                body_text=respuesta,
                buttons=adapter.get_schedule_alternative_buttons(),
            )
            return

        elif action_performed == "show_schedule_buttons" or (state == FlowState.WAITING_FOR_SCHEDULE and not any(k in respuesta.lower() for k in ["indícame la hora", "indicame la hora", "escribe la hora", "hora y el día", "hora y el dia", "horario alternativo", "próximo horario", "proximo horario", "no tenemos disponibilidad", "está lleno", "esta lleno"])):
            cleaned = adapter.clean_text_for_interactive(respuesta, "buttons", "schedule")
            await adapter.send_interactive_buttons(
                recipient_wa_id=wa_id,
                body_text=cleaned,
                buttons=adapter.get_schedule_buttons(),
            )
            return

        elif action_performed == "show_payment_buttons" or state == FlowState.WAITING_FOR_PAYMENT_METHOD:
            cleaned = adapter.clean_text_for_interactive(respuesta, "buttons", "payment")
            await adapter.send_interactive_buttons(
                recipient_wa_id=wa_id,
                body_text=cleaned,
                buttons=adapter.get_payment_method_buttons(),
            )
            return

        elif action_performed == "show_edit_options":
            sections = adapter.get_edit_options_list_sections()
            await adapter.send_interactive_list(
                recipient_wa_id=wa_id,
                body_text=respuesta or "✏️ *Modificar Pedido*\nSelecciona qué dato deseas modificar en las opciones:",
                button_label="Ver Opciones",
                sections=sections,
            )
            return

        elif action_performed == "show_confirmation" or state == FlowState.WAITING_FOR_CONFIRMATION:
            cleaned = adapter.clean_text_for_interactive(respuesta, "buttons", "confirmation")
            await adapter.send_interactive_buttons(
                recipient_wa_id=wa_id,
                body_text=cleaned,
                buttons=adapter.get_confirmation_buttons(),
            )
            return

        elif action_performed == "order_created":
            from src.services.notifications import _format_markdown_for_whatsapp
            wa_text = _format_markdown_for_whatsapp(respuesta)
            order_match = re.search(r"(?:pedido|folio)\s*#?\s*(\d+)", respuesta, re.IGNORECASE)
            if order_match:
                order_id = order_match.group(1)
                await adapter.send_interactive_buttons(
                    recipient_wa_id=wa_id,
                    body_text=wa_text,
                    buttons=adapter.get_order_active_buttons(order_id),
                )
            else:
                await adapter.send_text_message(
                    recipient_wa_id=wa_id,
                    text=wa_text,
                )
            return

        # 2. Detector heurístico contextual si no hubo acción explícita
        cleaned_text, interactive_spec = adapter.detect_interactive_elements(
            respuesta=respuesta,
            phone=phone_10,
            channel_user_id=wa_id,
            tenant_id=TENANT_ID,
            user_text=user_text,
        )

        if interactive_spec:
            spec_type = interactive_spec.get("type")
            if spec_type == "buttons":
                await adapter.send_interactive_buttons(
                    recipient_wa_id=wa_id,
                    body_text=cleaned_text,
                    buttons=interactive_spec["buttons"],
                )
                return
            elif spec_type == "list":
                await adapter.send_interactive_list(
                    recipient_wa_id=wa_id,
                    body_text=cleaned_text,
                    button_label=interactive_spec.get("button_label", "Ver Opciones"),
                    sections=interactive_spec["sections"],
                )
                return

        # Mensaje de texto normal
        await adapter.send_text_message(recipient_wa_id=wa_id, text=respuesta)

    except Exception as e:
        logger.error(f"❌ Error al procesar mensaje de WhatsApp para {wa_id}: {e}", exc_info=True)
        await adapter.send_text_message(
            recipient_wa_id=wa_id,
            text="⚠️ Ocurrió un error al procesar tu solicitud. Por favor intenta de nuevo en unos momentos.",
        )


async def _invoke_graph_and_reply(
    user_text: str,
    wa_id: str,
    phone_10: str,
    config: dict[str, Any],
) -> None:
    """Invoke LangGraph agent and dispatch formatted WhatsApp response."""
    try:
        resultado = await graph.ainvoke(
            {
                "messages": [HumanMessage(content=user_text)],
                "channel": "whatsapp",
                "channel_user_id": wa_id,
            },
            config=config,
        )

        ai_message = resultado["messages"][-1]
        respuesta = ai_message.content
        if not isinstance(respuesta, str):
            respuesta = str(respuesta)

        # Detectar botones o listas interactivas contextuales
        cleaned_text, interactive_spec = adapter.detect_interactive_elements(
            respuesta=respuesta,
            phone=phone_10,
            channel_user_id=wa_id,
            tenant_id=TENANT_ID,
            user_text=user_text,
        )

        if interactive_spec:
            spec_type = interactive_spec.get("type")
            if spec_type == "buttons":
                await adapter.send_interactive_buttons(
                    recipient_wa_id=wa_id,
                    body_text=cleaned_text,
                    buttons=interactive_spec["buttons"],
                )
                return
            elif spec_type == "list":
                await adapter.send_interactive_list(
                    recipient_wa_id=wa_id,
                    body_text=cleaned_text,
                    button_label=interactive_spec.get("button_label", "Ver Opciones"),
                    sections=interactive_spec["sections"],
                )
                return

        # Mensaje de texto normal
        await adapter.send_text_message(recipient_wa_id=wa_id, text=respuesta)

    except Exception as e:
        logger.error(f"❌ Error al procesar mensaje de WhatsApp para {wa_id}: {e}", exc_info=True)
        await adapter.send_text_message(
            recipient_wa_id=wa_id,
            text="⚠️ Ocurrió un error al procesar tu solicitud. Por favor intenta de nuevo en unos momentos.",
        )
