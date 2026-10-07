import unittest
from src.database import init_db
from src.models.customer import CustomerAddress
from src.repositories import get_repository
from src.repositories.identity_store import identity_store
from src.services.flow_router import FlowResponse, FlowState, flow_router, clear_session
from telegram_bot import get_markup_for_flow_response, detectar_botones_mensaje


class TestAccountAddressIsolation(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        init_db()
        self.repo = get_repository()
        self.tenant_id = "petroil"

        # Customer A: Oscar with 3 addresses bound to telegram ID "user_tg_111"
        cust_a = self.repo.save_or_update_customer(
            tenant_id=self.tenant_id,
            channel="telegram",
            channel_user_id="user_tg_111",
            name="Oscar Vizcarra",
            phone="6699123501",
            address="Hotel Pueblo Bonito Mazatlán, Zona Dorada",
        )
        if hasattr(self.repo, "add_customer_address"):
            self.repo.add_customer_address(cust_a.id, "Hotel Pueblo Bonito Mazatlán, Zona Dorada")
            self.repo.add_customer_address(cust_a.id, "Misión San Javier 5246, Fracc. Las Misiones")
            self.repo.add_customer_address(cust_a.id, "Caoba 361, Col. Los Mangos 1")

        identity_store.bind_channel_user_phone("telegram", "user_tg_111", "6699123501")

        # Customer B: Usuario Prueba with 1 address and phone "6695090909"
        cust_b = self.repo.save_or_update_customer(
            tenant_id=self.tenant_id,
            channel="telegram",
            channel_user_id="user_tg_different",
            name="Usuario Prueba",
            phone="6695090909",
            address="Av del Mar 1000, Mazatlán",
        )
        if hasattr(self.repo, "add_customer_address"):
            self.repo.add_customer_address(cust_b.id, "Av del Mar 1000, Mazatlán")

        clear_session("telegram:petroil:user_tg_111")

    async def test_get_markup_does_not_leak_other_account_addresses(self):
        """When phone='6695090909' is specified, markup must never show Oscar's 3 addresses."""
        flow_res = FlowResponse(
            text="¿A cuál de tus 1 dirección(es) guardadas deseas que enviemos tu pedido o prefieres ingresar una nueva?",
            state=FlowState.WAITING_FOR_ADDRESS_SELECTION,
            action_performed="show_address_buttons",
        )

        markup = get_markup_for_flow_response(flow_res, phone="6695090909", user_id="user_tg_111")
        self.assertIsNotNone(markup)

        button_texts = [btn.text for row in markup.inline_keyboard for btn in row]
        # Should have Customer B's address
        self.assertTrue(any("Av del Mar 1000" in t for t in button_texts))
        # MUST NOT have ANY of Customer A's addresses
        self.assertFalse(any("Hotel Pueblo Bonito" in t for t in button_texts))
        self.assertFalse(any("Misión San Javier" in t for t in button_texts))
        self.assertFalse(any("Caoba 361" in t for t in button_texts))

    async def test_detectar_botones_mensaje_does_not_leak_addresses(self):
        """detectar_botones_mensaje must isolate addresses by phone and not fallback to channel_user_id."""
        msg = "¿A cuál de tus 1 dirección(es) guardadas deseas que enviemos tu pedido o prefieres ingresar una nueva?"
        markup = detectar_botones_mensaje(msg, phone="6695090909", channel_user_id="user_tg_111")
        self.assertIsNotNone(markup)

        button_texts = [btn.text for row in markup.inline_keyboard for btn in row]
        self.assertTrue(any("Av del Mar 1000" in t for t in button_texts))
        self.assertFalse(any("Hotel Pueblo Bonito" in t for t in button_texts))
        self.assertFalse(any("Misión San Javier" in t for t in button_texts))
        self.assertFalse(any("Caoba 361" in t for t in button_texts))

    async def test_unknown_phone_does_not_fallback_to_other_account(self):
        """When a phone has no saved addresses, do NOT fall back to user_tg_111 and leak Oscar's addresses."""
        flow_res = FlowResponse(
            text="¿A cuál de tus direcciones guardadas deseas que enviemos tu pedido?",
            state=FlowState.WAITING_FOR_ADDRESS_SELECTION,
            action_performed="show_address_buttons",
        )

        # Phone with no customer
        markup = get_markup_for_flow_response(flow_res, phone="6698887766", user_id="user_tg_111")
        self.assertIsNone(markup)

    async def test_flow_router_enters_phone_and_generates_isolated_buttons(self):
        """Flow router updates draft_order.customer_phone and presents isolated address buttons."""
        session_id = "telegram:petroil:user_tg_111"
        clear_session(session_id)

        # Step 1: Select cylinder
        res1 = await flow_router.process_event(
            session_id=session_id,
            text="Quiero 1 cilindro de 30 kg",
            channel="telegram",
            channel_user_id="user_tg_111",
            tenant_id="petroil",
        )
        self.assertEqual(res1.state, FlowState.WAITING_FOR_PHONE)

        # Step 2: User enters Customer B's phone
        res2 = await flow_router.process_event(
            session_id=session_id,
            text="6695090909",
            channel="telegram",
            channel_user_id="user_tg_111",
            tenant_id="petroil",
        )
        self.assertEqual(res2.state, FlowState.WAITING_FOR_ADDRESS_SELECTION)
        self.assertIn("Usuario Prueba", res2.text)

        sess = flow_router.get_session(session_id)
        self.assertEqual(sess.draft_order.customer_phone, "6695090909")

        # Generate markup using the active session phone
        markup = get_markup_for_flow_response(res2, phone=sess.draft_order.customer_phone, user_id="user_tg_111")
        self.assertIsNotNone(markup)

        button_texts = [btn.text for row in markup.inline_keyboard for btn in row]
        self.assertTrue(any("Av del Mar 1000" in t for t in button_texts))
        self.assertFalse(any("Hotel Pueblo Bonito" in t for t in button_texts))
        self.assertFalse(any("Misión San Javier" in t for t in button_texts))
        self.assertFalse(any("Caoba 361" in t for t in button_texts))


if __name__ == "__main__":
    unittest.main()
