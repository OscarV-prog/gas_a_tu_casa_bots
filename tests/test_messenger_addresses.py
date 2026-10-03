"""Tests for Messenger multi-address management and preservation."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from src.models.customer import Customer, CustomerAddress
from src.channels.messenger.adapter import MessengerAdapter
from src.channels.messenger.router import router, _dispatch_flow_response_messenger
from src.services.flow_router import FlowResponse, FlowState, flow_router


class TestMessengerAddresses(unittest.TestCase):
    def setUp(self):
        self.adapter = MessengerAdapter()

    def test_quick_replies_show_all_addresses(self):
        """Verify that up to 10 addresses are formatted and included in quick replies without replacing."""
        addresses = [
            CustomerAddress(id="addr_1", address="Hotel Pueblo Bonito Mazatlán, Zona Sábalo Country", alias="Principal", is_default=True),
            CustomerAddress(id="addr_2", address="Misión San Javier 5246, Fracc. Las Misiones", alias="Dirección 2", is_default=False),
            CustomerAddress(id="addr_3", address="Calle Caoba 361, Los Mangos 1", alias="Dirección 3", is_default=False),
        ]
        replies = self.adapter.get_customer_addresses_quick_replies(addresses)

        # Must have 3 addresses + 1 new + 1 delete = 5 replies
        self.assertEqual(len(replies), 5)
        self.assertEqual(replies[0]["id"], "client_addr:1")
        self.assertIn("1. Hotel Pueblo", replies[0]["title"])
        self.assertEqual(replies[1]["id"], "client_addr:2")
        self.assertIn("2. Misión San", replies[1]["title"])
        self.assertEqual(replies[2]["id"], "client_addr:3")
        self.assertIn("3. Calle Caoba", replies[2]["title"])
        self.assertEqual(replies[3]["id"], "client_addr:new")
        self.assertEqual(replies[4]["id"], "client_addr:del_menu")

    @patch("src.channels.messenger.router.get_repository")
    @patch("src.channels.messenger.router.adapter")
    async def _async_test_show_addresses_lists_all(self, mock_adapter, mock_get_repo):
        psid = "test_psid_999"
        mock_adapter.get_customer_addresses_quick_replies.side_effect = self.adapter.get_customer_addresses_quick_replies
        mock_adapter.send_quick_replies = AsyncMock()
        mock_adapter.send_sender_action = AsyncMock()
        mock_repo = MagicMock()
        mock_get_repo.return_value = mock_repo

        cust = Customer(
            id="cust_uuid_123",
            tenant_id="petroil",
            channel="messenger",
            channel_user_id=psid,
            name="Oscar",
            phone="6699123501",
            address="Hotel Pueblo Bonito",
            addresses=[
                CustomerAddress(id="id_1", address="Hotel Pueblo Bonito Mazatlán", alias="Principal", is_default=True),
                CustomerAddress(id="id_2", address="Misión San Javier 5246", alias="Dirección 2", is_default=False),
            ],
        )
        mock_repo.get_customer_by_phone.return_value = cust
        mock_repo.get_customer.return_value = cust

        flow_res = FlowResponse(
            text="¿A cuál de tus direcciones deseas que enviemos tu pedido?",
            state=FlowState.WAITING_FOR_ADDRESS_SELECTION,
            action_performed="show_address_buttons",
        )

        await _dispatch_flow_response_messenger(flow_res, psid=psid)

        mock_adapter.send_quick_replies.assert_called_once()
        args, kwargs = mock_adapter.send_quick_replies.call_args
        sent_text = kwargs.get("text", "")
        # Las direcciones NO deben aparecer en el mensaje de texto
        self.assertNotIn("Hotel Pueblo Bonito Mazatlán", sent_text)
        self.assertNotIn("Misión San Javier 5246", sent_text)
        # Las direcciones SÍ deben aparecer como botones en quick_replies
        replies = kwargs.get("quick_replies", [])
        self.assertTrue(any("1. Hotel Pueblo" in r.get("title", "") for r in replies))
        self.assertTrue(any("2. Misión San" in r.get("title", "") for r in replies))

    def test_show_addresses_lists_all(self):
        import asyncio
        asyncio.run(self._async_test_show_addresses_lists_all())

    @patch("src.services.flow_router.get_repository")
    @patch("src.services.flow_router.validate_address_with_llm")
    async def _async_test_flow_router_adds_address_without_replacing(self, mock_val, mock_get_repo):
        from src.services.address_validator import AddressValidationResult
        mock_val.return_value = AddressValidationResult(
            is_valid=True,
            is_joke_or_fake=False,
            confidence=0.95,
            normalized_address="Calle Caoba 361, Los Mangos 1",
            street="Calle Caoba",
            number="361",
            colonia="Los Mangos 1",
            references="",
            reason="Valido",
            user_feedback="",
        )

        mock_repo = MagicMock()
        mock_cust = Customer(
            id="cust_uuid_123",
            tenant_id="petroil",
            channel="messenger",
            channel_user_id="psid_123",
            name="Oscar",
            phone="6699123501",
            address="Hotel Pueblo Bonito",
            addresses=[CustomerAddress(id="id_1", address="Hotel Pueblo Bonito", alias="Principal")],
        )
        mock_repo.save_or_update_customer.return_value = mock_cust
        mock_get_repo.return_value = mock_repo

        session_id = "test_sess_addr_99"
        session = flow_router.get_session(session_id)
        session.state = FlowState.WAITING_FOR_NEW_CUSTOMER_ADDRESS
        session.channel = "messenger"
        session.channel_user_id = "psid_123"
        session.draft_order.customer_phone = "6699123501"
        session.draft_order.customer_name = "Oscar"
        session.draft_order.is_existing_customer = True

        res = await flow_router.process_event(session_id=session_id, text="Calle Caoba 361, Los Mangos 1", channel="messenger", channel_user_id="psid_123")

        mock_repo.save_or_update_customer.assert_called_once()
        mock_repo.add_customer_address.assert_called_once_with(
            customer_id="cust_uuid_123",
            address="Calle Caoba 361, Los Mangos 1",
            notes="",
        )
        self.assertEqual(res.state, FlowState.WAITING_FOR_SCHEDULE)

    def test_flow_router_adds_address_without_replacing(self):
        import asyncio
        asyncio.run(self._async_test_flow_router_adds_address_without_replacing())


if __name__ == "__main__":
    unittest.main()
