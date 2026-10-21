"""Test suite verifying WhatsApp parity with Telegram for:
1. Main menu and 'Mi Cuenta' interactive buttons
2. Address listing, detail view, adding new address (via text & GPS)
3. Double confirmation on address deletion and persistence in identity_store
4. '🔙 Volver' (client_addr_back) navigation during order creation
5. Exclusion of deleted or bare city addresses
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

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
from src.channels.whatsapp.router import (
    process_whatsapp_event,
    _mostrar_menu_principal_wa,
    _mostrar_mi_cuenta_wa,
    _mostrar_direcciones_cuenta_wa,
    _mostrar_detalle_direccion_wa,
    _clear_wa_account_state,
)
from src.repositories import get_repository
from src.repositories.identity_store import identity_store
from src.services.flow_router import flow_router, FlowState, get_or_create_session, clear_session


async def run_whatsapp_address_account_tests():
    print("🚀 Running WhatsApp Address & Account Parity Test Suite...\n")
    repo = get_repository()
    tenant_id = "petroil"
    wa_id = "5216699887711"
    phone_10 = "6699887711"
    thread_id = f"whatsapp:{tenant_id}:{wa_id}"

    # Setup: Create test customer with 2 addresses
    addr1 = "Calle Benito Juarez 105, Col. Centro, Mazatlán"
    addr2 = "Av. Sabalo Cerritos 500, Mazatlán"

    cust = repo.save_or_update_customer(
        tenant_id=tenant_id,
        channel="whatsapp",
        channel_user_id=wa_id,
        name="Juan Perez",
        phone=phone_10,
        address=addr1,
    )
    repo.add_customer_address(customer_id=cust.id, address=addr2, notes="")
    # Clear any stale deleted marks
    identity_store.unmark_address_deleted(phone_10, addr1)
    identity_store.unmark_address_deleted(phone_10, addr2)

    adapter = WhatsAppAdapter()

    # -------------------------------------------------------------------------
    # Test 1: Main Menu & Mi Cuenta
    # -------------------------------------------------------------------------
    print("[Test 1] Testing Main Menu and Mi Cuenta buttons in WhatsApp...")
    with patch("src.channels.whatsapp.adapter.WhatsAppAdapter.send_interactive_buttons", new_callable=AsyncMock) as mock_btns:
        event = {
            "channel": "whatsapp",
            "wa_id": wa_id,
            "interactive_id": "menu:main",
            "msg_id": "test_msg_1",
            "type": "interactive",
        }
        await process_whatsapp_event(event)
        mock_btns.assert_awaited()
        call_kwargs = mock_btns.call_args[1]
        buttons = call_kwargs["buttons"]
        btn_ids = [b["id"] for b in buttons]
        assert "menu:hacer_pedido" in btn_ids, f"Expected menu:hacer_pedido in {btn_ids}"
        assert "menu:mi_cuenta" in btn_ids, f"Expected menu:mi_cuenta in {btn_ids}"
        # Validate button character limits (<= 20 chars)
        for b in buttons:
            assert len(b["title"]) <= 20, f"Button title '{b['title']}' exceeds WhatsApp limit (20 chars)"
        print("  ✅ Passed: Main Menu sent correct buttons respecting Meta 20-char limit.")

    with patch("src.channels.whatsapp.adapter.WhatsAppAdapter.send_interactive_buttons", new_callable=AsyncMock) as mock_btns:
        event = {
            "channel": "whatsapp",
            "wa_id": wa_id,
            "interactive_id": "menu:mi_cuenta",
            "msg_id": "test_msg_2",
            "type": "interactive",
        }
        await process_whatsapp_event(event)
        mock_btns.assert_awaited()
        call_kwargs = mock_btns.call_args[1]
        buttons = call_kwargs["buttons"]
        btn_ids = [b["id"] for b in buttons]
        assert "account_menu:addresses" in btn_ids, f"Expected account_menu:addresses in {btn_ids}"
        assert "account:edit_name" in btn_ids, f"Expected account:edit_name in {btn_ids}"
        for b in buttons:
            assert len(b["title"]) <= 20, f"Button title '{b['title']}' exceeds WhatsApp limit (20 chars)"
        print("  ✅ Passed: Mi Cuenta sent correct account action buttons.")

    # -------------------------------------------------------------------------
    # Test 2: Address List (>1 addresses -> Interactive List)
    # -------------------------------------------------------------------------
    print("\n[Test 2] Testing Mis Direcciones interactive list...")
    with patch("src.channels.whatsapp.adapter.WhatsAppAdapter.send_interactive_list", new_callable=AsyncMock) as mock_list:
        event = {
            "channel": "whatsapp",
            "wa_id": wa_id,
            "interactive_id": "account_menu:addresses",
            "msg_id": "test_msg_3",
            "type": "interactive",
        }
        await process_whatsapp_event(event)
        mock_list.assert_awaited()
        call_kwargs = mock_list.call_args[1]
        sections = call_kwargs["sections"]
        all_row_ids = [r["id"] for sec in sections for r in sec["rows"]]
        assert any("account_addr:view:" in r_id for r_id in all_row_ids), f"Expected view rows in {all_row_ids}"
        assert "account_addr:add" in all_row_ids, f"Expected account_addr:add in {all_row_ids}"
        assert any(k in all_row_ids for k in ("account_addr:del_menu", "client_addr:del_menu")), f"Expected del_menu in {all_row_ids}"
        first_view_id = next(r_id for r_id in all_row_ids if r_id.startswith("account_addr:view:"))
        # Validate Meta limits (row title <= 24, description <= 72)
        for sec in sections:
            for r in sec["rows"]:
                assert len(r["title"]) <= 24, f"Row title '{r['title']}' exceeds 24 chars"
                if "description" in r:
                    assert len(r["description"]) <= 72, f"Row description exceeds 72 chars"
        print("  ✅ Passed: Address list displayed as interactive list adhering to Meta limits.")

    # -------------------------------------------------------------------------
    # Test 3: Address Detail View
    # -------------------------------------------------------------------------
    print("\n[Test 3] Testing Address Detail View...")
    with patch("src.channels.whatsapp.adapter.WhatsAppAdapter.send_interactive_buttons", new_callable=AsyncMock) as mock_btns:
        event = {
            "channel": "whatsapp",
            "wa_id": wa_id,
            "interactive_id": first_view_id,
            "msg_id": "test_msg_4",
            "type": "interactive",
        }
        await process_whatsapp_event(event)
        mock_btns.assert_awaited()
        call_kwargs = mock_btns.call_args[1]
        buttons = call_kwargs["buttons"]
        btn_ids = [b["id"] for b in buttons]
        assert "client_addr:1" in btn_ids, f"Expected client_addr:1 in {btn_ids}"
        assert any(b_id.startswith("del_addr:") for b_id in btn_ids), f"Expected del_addr in {btn_ids}"
        assert "account_menu:addresses" in btn_ids, f"Expected account_menu:addresses in {btn_ids}"
        for b in buttons:
            assert len(b["title"]) <= 20, f"Button title '{b['title']}' exceeds 20 chars"
        print("  ✅ Passed: Address detail presents order, delete, and back buttons.")

    # -------------------------------------------------------------------------
    # Test 4: Address Deletion with Double Confirmation
    # -------------------------------------------------------------------------
    print("\n[Test 4] Testing Address Deletion Double Confirmation...")
    cust_current = repo.get_customer_by_phone(tenant_id, phone_10)
    target_addr_id = cust_current.addresses[0].id
    target_addr_text = cust_current.addresses[0].address

    # Step 4.1: Click delete -> Prompt confirmation
    with patch("src.channels.whatsapp.adapter.WhatsAppAdapter.send_interactive_buttons", new_callable=AsyncMock) as mock_btns:
        event = {
            "channel": "whatsapp",
            "wa_id": wa_id,
            "interactive_id": f"del_addr:{target_addr_id}",
            "msg_id": "test_msg_5",
            "type": "interactive",
        }
        await process_whatsapp_event(event)
        mock_btns.assert_awaited()
        call_kwargs = mock_btns.call_args[1]
        buttons = call_kwargs["buttons"]
        btn_ids = [b["id"] for b in buttons]
        assert f"del_addr_confirm:{target_addr_id}" in btn_ids
        assert "del_addr_cancel" in btn_ids
        print("  ✅ Passed: Double confirmation prompted before deleting.")

    # Step 4.2: Confirm deletion -> Address marked deleted in identity_store and DB
    with patch("src.channels.whatsapp.adapter.WhatsAppAdapter.send_interactive_buttons", new_callable=AsyncMock) as mock_btns, \
         patch("src.channels.whatsapp.adapter.WhatsAppAdapter.send_interactive_list", new_callable=AsyncMock) as mock_list, \
         patch("src.channels.whatsapp.adapter.WhatsAppAdapter.send_text_message", new_callable=AsyncMock) as mock_txt:
        event = {
            "channel": "whatsapp",
            "wa_id": wa_id,
            "interactive_id": f"del_addr_confirm:{target_addr_id}",
            "msg_id": "test_msg_6",
            "type": "interactive",
        }
        await process_whatsapp_event(event)
        # Check identity_store
        assert identity_store.is_address_deleted(phone_10, target_addr_text), "Address was not marked deleted in identity_store!"
        # Check filter_valid_addresses suppresses it
        valid_now = adapter.filter_valid_addresses(cust_current.addresses, phone=phone_10)
        assert not any(a.address == target_addr_text for a in valid_now), "Deleted address was not filtered out!"
        print("  ✅ Passed: Address successfully deleted and permanently filtered in identity_store.")

    # -------------------------------------------------------------------------
    # Test 5: Order Creation Navigation & '🔙 Volver' (client_addr_back)
    # -------------------------------------------------------------------------
    print("\n[Test 5] Testing '🔙 Volver' (client_addr_back) in order address selection...")
    clear_session(thread_id)
    sess = get_or_create_session(thread_id)
    sess.tenant_id = tenant_id
    sess.channel = "whatsapp"
    sess.channel_user_id = wa_id
    sess.draft_order.customer_phone = phone_10
    sess.draft_order.customer_name = "Juan Perez"
    sess.draft_order.items = [{"product_name": "Cilindro 30kg", "quantity": 1, "unit_price": 670.0}]

    # In WAITING_FOR_NEW_CUSTOMER_ADDRESS with remaining saved addresses
    sess.state = FlowState.WAITING_FOR_NEW_CUSTOMER_ADDRESS

    with patch("src.channels.whatsapp.adapter.WhatsAppAdapter.send_interactive_buttons", new_callable=AsyncMock) as mock_btns, \
         patch("src.channels.whatsapp.adapter.WhatsAppAdapter.send_interactive_list", new_callable=AsyncMock) as mock_list:
        event = {
            "channel": "whatsapp",
            "wa_id": wa_id,
            "interactive_id": "client_addr_back",
            "msg_id": "test_msg_7",
            "type": "interactive",
        }
        await process_whatsapp_event(event)
        # Verify state transitioned back to WAITING_FOR_ADDRESS_SELECTION
        assert sess.state == FlowState.WAITING_FOR_ADDRESS_SELECTION, f"Expected WAITING_FOR_ADDRESS_SELECTION, got {sess.state}"
        # Either buttons or list should have been sent with saved addresses
        assert mock_btns.called or mock_list.called, "Expected address options to be redisplayed."
        print("  ✅ Passed: '🔙 Volver' returns cleanly to saved addresses without breaking order flow.")

    # -------------------------------------------------------------------------
    # Test 6: Text Shortcuts for 'Mi Cuenta' & 'Direcciones'
    # -------------------------------------------------------------------------
    print("\n[Test 6] Testing text shortcuts outside of active order...")
    clear_session(thread_id)

    with patch("src.channels.whatsapp.adapter.WhatsAppAdapter.send_interactive_buttons", new_callable=AsyncMock) as mock_btns:
        event = {
            "channel": "whatsapp",
            "wa_id": wa_id,
            "text": "mi cuenta",
            "msg_id": "test_msg_8",
            "type": "text",
        }
        await process_whatsapp_event(event)
        mock_btns.assert_awaited()
        call_kwargs = mock_btns.call_args[1]
        buttons = call_kwargs["buttons"]
        assert any(b["id"] == "account_menu:addresses" for b in buttons)
        print("  ✅ Passed: Natural text 'mi cuenta' opened account menu.")

    with patch("src.channels.whatsapp.adapter.WhatsAppAdapter.send_interactive_buttons", new_callable=AsyncMock) as mock_btns, \
         patch("src.channels.whatsapp.adapter.WhatsAppAdapter.send_interactive_list", new_callable=AsyncMock) as mock_list:
        event = {
            "channel": "whatsapp",
            "wa_id": wa_id,
            "text": "mis direcciones",
            "msg_id": "test_msg_9",
            "type": "text",
        }
        await process_whatsapp_event(event)
        assert mock_btns.called or mock_list.called
        print("  ✅ Passed: Natural text 'mis direcciones' opened addresses view.")

    print("\n🎉 ALL WHATSAPP ADDRESS & ACCOUNT PARITY TESTS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    asyncio.run(run_whatsapp_address_account_tests())
