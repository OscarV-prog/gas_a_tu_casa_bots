"""Asynchronous test suite verifying extra features ported to WhatsApp without disrupting the sales flow:
1. Live location tracking message with active order cancel button
2. Cancellation flow with double confirmation (cancel_order_client -> confirm_cancel_order_client / keep_order_client)
3. Natural text "cancelar pedido" auto-resolves active order
4. CSAT rating and feedback tags on delivery
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from src.channels.whatsapp.adapter import WhatsAppAdapter
from src.channels.whatsapp.router import process_whatsapp_event
from src.repositories import get_repository
from src.repositories.identity_store import identity_store
from src.services.flow_router import flow_router, FlowState, get_or_create_session, clear_session
from src.services.notifications import send_client_live_location


async def run_whatsapp_feature_tests():
    print("🚀 Running WhatsApp Extra Features Test Suite...\n")
    repo = get_repository()
    tenant_id = "petroil"

    # Setup: Create test customer and driver
    cust_phone = "6699887766"
    existing_drivers = [d for d in repo.get_all_drivers(tenant_id) if getattr(d, "telegram_user_id", None)]
    if existing_drivers:
        driver = existing_drivers[0]
    else:
        driver = repo.create_driver(
            tenant_id=tenant_id,
            name="Chofer WhatsApp Test",
            phone="6691112233",
            telegram_user_id="tg_driver_wa_test_123",
            vehicle_plate="WA-1234",
        )

    # Create active order
    order = repo.create_order(
        tenant_id=tenant_id,
        customer_name="Cliente WhatsApp Test",
        customer_phone=cust_phone,
        delivery_address="Av del Mar 100, Mazatlán",
        items=[{"product_name": "Cilindro 30kg", "quantity": 1, "unit_price": 670.0}],
        payment_method="Efectivo",
        channel="whatsapp",
        channel_user_id=f"521{cust_phone}",
    )
    repo.update_order_status(tenant_id, order.id, "in_route", driver_id=driver.id)
    from src.database.connection import get_db_connection
    with get_db_connection() as conn:
        conn.execute("UPDATE orders SET driver_id = 1, status = 'in_route' WHERE id = ?", (order.id,))

    # -------------------------------------------------------------------------
    # TEST 1: Live location sharing with active order Cancel Button
    # -------------------------------------------------------------------------
    print("[Test 1] Testing send_client_live_location on WhatsApp with order_id...")
    with patch("src.services.notifications._send_whatsapp_location_sync") as mock_wa_loc, \
         patch("src.services.notifications._send_whatsapp_buttons_sync") as mock_wa_btn:

        msg_id = send_client_live_location(
            channel_user_id=f"521{cust_phone}",
            latitude=23.2350,
            longitude=-106.4250,
            channel="whatsapp",
            order_id=order.id,
        )

        assert msg_id == 999999
        mock_wa_loc.assert_called_once()
        mock_wa_btn.assert_called_once()
        call_args = mock_wa_btn.call_args[0]
        # Target phone
        assert cust_phone in call_args[0]
        # Message mentions Pedido #id and tracking URL
        assert "mapa" in call_args[1].lower() or "google.com/maps" in call_args[1]
        # Buttons include cancel_order_client
        buttons = call_args[2]
        assert len(buttons) == 1
        assert buttons[0]["id"] == f"cancel_order_client:{order.id}"
        assert "Cancelar" in buttons[0]["title"]
    print("  ✅ Passed: WhatsApp received map pin + tracking message with [❌ Cancelar Pedido] button.\n")

    # -------------------------------------------------------------------------
    # TEST 2: Customer clicks [❌ Cancelar Pedido] -> double confirmation prompt
    # -------------------------------------------------------------------------
    print("[Test 2] Testing customer clicking [❌ Cancelar Pedido] in WhatsApp...")
    with patch("src.channels.whatsapp.adapter.WhatsAppAdapter.send_interactive_buttons", new_callable=AsyncMock) as mock_send_btns:
        event_cancel_click = {
            "wa_id": f"521{cust_phone}",
            "msg_id": "wamid.test.1",
            "type": "interactive",
            "interactive_id": f"cancel_order_client:{order.id}",
            "text": "❌ Cancelar Pedido",
        }
        await process_whatsapp_event(event_cancel_click)

        mock_send_btns.assert_called_once()
        c_args = mock_send_btns.call_args[1]
        assert f"¿Estás seguro de que deseas cancelar tu pedido #{order.id}?" in c_args["body_text"]
        c_buttons = c_args["buttons"]
        btn_ids = [b["id"] for b in c_buttons]
        assert f"confirm_cancel_order_client:{order.id}" in btn_ids
        assert f"keep_order_client:{order.id}" in btn_ids
    print("  ✅ Passed: Double confirmation prompt correctly sent with [⚠️ Sí, Cancelar] and [🔙 No, Conservar].\n")

    # -------------------------------------------------------------------------
    # TEST 3: Customer clicks [🔙 No, Conservar] -> Order remains active
    # -------------------------------------------------------------------------
    print("[Test 3] Testing customer clicking [🔙 No, Conservar]...")
    with patch("src.channels.whatsapp.adapter.WhatsAppAdapter.send_interactive_buttons", new_callable=AsyncMock) as mock_send_btns:
        event_keep = {
            "wa_id": f"521{cust_phone}",
            "msg_id": "wamid.test.2",
            "type": "interactive",
            "interactive_id": f"keep_order_client:{order.id}",
            "text": "🔙 No, Conservar",
        }
        await process_whatsapp_event(event_keep)

        mock_send_btns.assert_called_once()
        c_args = mock_send_btns.call_args[1]
        assert "sigue activo" in c_args["body_text"]
        ord_db = repo.get_order_by_id(tenant_id, order.id)
        assert ord_db.status in ("in_route", "assigned", "confirmed")
    print("  ✅ Passed: Order remained in_route with active buttons.\n")

    # -------------------------------------------------------------------------
    # TEST 4: Customer clicks [⚠️ Sí, Cancelar] -> Order cancelled, driver notified
    # -------------------------------------------------------------------------
    print("[Test 4] Testing customer confirming cancellation...")
    # Asegurar driver_id en order para prueba aislada
    orig_get_order = repo.get_order_by_id
    def mock_get_order(tid, oid):
        ord_res = orig_get_order(tid, oid)
        if ord_res and ord_res.id == order.id and getattr(ord_res, "status", "") != "cancelled":
            ord_res.driver_id = driver.id
        return ord_res

    with patch.object(repo, "get_driver", return_value=driver), \
         patch.object(repo, "get_order_by_id", side_effect=mock_get_order), \
         patch("src.channels.whatsapp.adapter.WhatsAppAdapter.send_text_message", new_callable=AsyncMock) as mock_send_txt, \
         patch("src.services.notifications.notify_driver_order_cancelled") as mock_notify_driver:

            event_confirm_cancel = {
                "wa_id": f"521{cust_phone}",
                "msg_id": "wamid.test.3",
                "type": "interactive",
                "interactive_id": f"confirm_cancel_order_client:{order.id}",
                "text": "⚠️ Sí, Cancelar",
            }
            await process_whatsapp_event(event_confirm_cancel)

            # Order must be cancelled in DB
            ord_cancelled = repo.get_order_by_id(tenant_id, order.id)
            assert ord_cancelled.status == "cancelled"

            # Driver must be notified via telegram
            mock_notify_driver.assert_called_once()
            assert mock_notify_driver.call_args[1]["order_id"] == order.id
            assert mock_notify_driver.call_args[1]["driver_telegram_user_id"] == driver.telegram_user_id

            # Customer receives confirmation text
            mock_send_txt.assert_called_once()
            assert f"ha sido cancelado exitosamente" in mock_send_txt.call_args[0][1]
    print("  ✅ Passed: Order successfully cancelled, driver notified, live location cleared.\n")

    # -------------------------------------------------------------------------
    # TEST 5: Customer sends text 'cancelar pedido' without folio -> Resolves active order
    # -------------------------------------------------------------------------
    print("[Test 5] Testing natural text 'cancelar pedido' with active order...")
    # Create another active order
    order2 = repo.create_order(
        tenant_id=tenant_id,
        customer_name="Cliente WhatsApp Test",
        customer_phone=cust_phone,
        delivery_address="Av del Mar 200, Mazatlán",
        items=[{"product_name": "Cilindro 30kg", "quantity": 1, "unit_price": 670.0}],
        payment_method="Efectivo",
        channel="whatsapp",
        channel_user_id=f"521{cust_phone}",
    )
    repo.update_order_status(tenant_id, order2.id, "confirmed")

    session_id = f"whatsapp:{tenant_id}:521{cust_phone}"
    clear_session(session_id)

    flow_res = await flow_router.process_event(
        session_id=session_id,
        text="deseo cancelar mi pedido por favor",
        channel="whatsapp",
        channel_user_id=f"521{cust_phone}",
        tenant_id=tenant_id,
    )

    assert f"Confirmación de Cancelación para el Pedido #{order2.id}" in flow_res.text
    # Verify adapter detects the confirmation buttons
    adapter = WhatsAppAdapter()
    cleaned_txt, spec = adapter.detect_interactive_elements(
        respuesta=flow_res.text,
        phone=cust_phone,
        channel_user_id=f"521{cust_phone}",
        tenant_id=tenant_id,
        user_text="deseo cancelar mi pedido por favor",
    )
    assert spec is not None
    assert spec["type"] == "buttons"
    assert spec["buttons"][0]["id"] == f"confirm_cancel_order_client:{order2.id}"
    print("  ✅ Passed: Natural language 'cancelar mi pedido' auto-resolved active order and presented confirmation buttons.\n")

    # -------------------------------------------------------------------------
    # TEST 6: Delivery CSAT Rating & Feedback Tags
    # -------------------------------------------------------------------------
    print("[Test 6] Testing CSAT rating flow and tag feedback...")
    repo.update_order_status(tenant_id, order2.id, "delivered", driver_id=driver.id)

    with patch("src.channels.whatsapp.adapter.WhatsAppAdapter.send_interactive_list", new_callable=AsyncMock) as mock_send_list:
        event_rate = {
            "wa_id": f"521{cust_phone}",
            "msg_id": "wamid.test.4",
            "type": "interactive",
            "interactive_id": f"rate_driver:{order2.id}:5",
            "text": "⭐⭐⭐⭐⭐ 5 Estrellas",
        }
        await process_whatsapp_event(event_rate)

        # Rating saved
        rating_rec = repo.get_order_rating(tenant_id, order2.id)
        assert rating_rec is not None
        assert rating_rec["rating"] == 5

        # Interactive feedback tags sent
        mock_send_list.assert_called_once()
        s_args = mock_send_list.call_args[1]
        assert "Muchas gracias por calificar con ⭐⭐⭐⭐⭐" in s_args["body_text"]
        rows = s_args["sections"][0]["rows"]
        row_ids = [r["id"] for r in rows]
        assert f"rate_tag:{order2.id}:Rapidez" in row_ids
        assert f"rate_tag:{order2.id}:Amabilidad" in row_ids

    # Step 6.2: Click feedback tag
    with patch("src.channels.whatsapp.adapter.WhatsAppAdapter.send_text_message", new_callable=AsyncMock) as mock_send_txt:
        event_tag = {
            "wa_id": f"521{cust_phone}",
            "msg_id": "wamid.test.5",
            "type": "interactive",
            "interactive_id": f"rate_tag:{order2.id}:Rapidez",
            "text": "⚡ Rapidez",
        }
        await process_whatsapp_event(event_tag)

        # Feedback tag saved in DB
        rating_rec = repo.get_order_rating(tenant_id, order2.id)
        assert rating_rec["feedback_tag"] == "⚡ Rapidez y puntualidad"

        mock_send_txt.assert_called_once()
        assert "ENCUESTA COMPLETADA CON ÉXITO" in mock_send_txt.call_args[0][1]
    print("  ✅ Passed: CSAT rating and feedback tag saved, completed survey message sent.\n")

    print("🎉 ALL WHATSAPP EXTRA FEATURE TESTS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    asyncio.run(run_whatsapp_feature_tests())
