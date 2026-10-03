"""Unit tests for escaping address validation traps via new order intent and phone prompting."""

import unittest
from unittest.mock import patch, MagicMock
from src.services.flow_router import (
    flow_router,
    FlowState,
    get_or_create_session,
    clear_session,
    check_new_order_or_reset_semantic,
)


class TestNewOrderEscapeAndPhone(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.session_id = "test_user_escape_123"
        clear_session(self.session_id)
        self.session = get_or_create_session(self.session_id, tenant_id="petroil", channel="telegram")

    async def test_semantic_helper_detects_variations(self):
        """Test check_new_order_or_reset_semantic on multiple Mexican Spanish variations."""
        variations = [
            "quiero hacer un nuevo pedido",
            "nuevo pedido",
            "hacer un nuevo pedido",
            "ocupo hacer un nuevo pedido",
            "quiero pedir gas",
            "ocupo gas",
            "quiero 2 cilindros de 30 kg",
            "empezar de nuevo",
            "volver al inicio",
            "cancelar",
        ]
        for v in variations:
            is_new, items = await check_new_order_or_reset_semantic(v, "petroil")
            self.assertTrue(is_new, f"Failed to detect new order intent for '{v}'")

    async def test_escape_from_waiting_for_new_customer_address(self):
        """When user is in WAITING_FOR_NEW_CUSTOMER_ADDRESS, 'quiero hacer un nuevo pedido' resets flow instead of rejecting as invalid address."""
        self.session.state = FlowState.WAITING_FOR_NEW_CUSTOMER_ADDRESS
        self.session.draft_order.customer_name = "Carlos López"
        self.session.draft_order.customer_phone = "6699123456"

        resp = await flow_router.process_event(
            session_id=self.session_id,
            text="quiero hacer un nuevo pedido",
            channel="telegram",
            channel_user_id="user_tg_123",
            tenant_id="petroil",
        )

        self.assertNotIn("⚠️ Por favor indícanos tu calle", resp.text)
        self.assertIn("nuevo pedido", resp.text.lower())
        self.assertEqual(resp.state, FlowState.INITIAL)
        self.assertEqual(resp.action_performed, "show_service_buttons")

    async def test_escape_from_address_with_direct_product_request(self):
        """When in WAITING_FOR_NEW_CUSTOMER_ADDRESS and user writes 'quiero 2 de 30 kg', routes to phone prompt with items."""
        self.session.state = FlowState.WAITING_FOR_NEW_CUSTOMER_ADDRESS

        resp = await flow_router.process_event(
            session_id=self.session_id,
            text="quiero 2 cilindros de 30 kg",
            channel="telegram",
            channel_user_id="user_tg_123",
            tenant_id="petroil",
        )

        self.assertNotIn("⚠️ Por favor indícanos", resp.text)
        self.assertEqual(resp.state, FlowState.WAITING_FOR_PHONE)
        self.assertTrue(len(self.session.draft_order.items) > 0)
        self.assertEqual(self.session.draft_order.items[0]["quantity"], 2)
        self.assertIn("30", self.session.draft_order.items[0]["product_name"])

    async def test_escape_from_waiting_for_address_selection(self):
        """When user is in WAITING_FOR_ADDRESS_SELECTION, 'nuevo pedido' escapes."""
        self.session.state = FlowState.WAITING_FOR_ADDRESS_SELECTION
        self.session.draft_order.customer_name = "Carlos López"
        self.session.draft_order.customer_phone = "6699123456"

        resp = await flow_router.process_event(
            session_id=self.session_id,
            text="iniciar nuevo pedido",
            channel="telegram",
            channel_user_id="user_tg_123",
            tenant_id="petroil",
        )

        self.assertNotIn("Por favor selecciona en los botones una de tus direcciones guardadas", resp.text)
        self.assertEqual(resp.state, FlowState.INITIAL)

    async def test_escape_from_waiting_for_new_customer_name(self):
        """When user is in WAITING_FOR_NEW_CUSTOMER_NAME, 'ocupo hacer un nuevo pedido' escapes."""
        self.session.state = FlowState.WAITING_FOR_NEW_CUSTOMER_NAME

        resp = await flow_router.process_event(
            session_id=self.session_id,
            text="ocupo hacer un nuevo pedido",
            channel="telegram",
            channel_user_id="user_tg_123",
            tenant_id="petroil",
        )

        self.assertNotIn("Para poder registrar tu cuenta correctamente", resp.text)
        self.assertEqual(resp.state, FlowState.INITIAL)

    async def test_real_address_not_mistaken_for_new_order(self):
        """A legitimate address must NOT be classified as new order."""
        addr = "Calle Caoba 361, Fracc Los Mangos"
        is_new, _ = await check_new_order_or_reset_semantic(addr, "petroil")
        self.assertFalse(is_new, "A real address was wrongly classified as new order intent")


if __name__ == "__main__":
    unittest.main()
