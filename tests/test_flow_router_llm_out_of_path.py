"""Unit tests for FlowRouter out-of-flow handling, order status inquiries, cancellations, and address rejection."""

import unittest
from src.services.flow_router import flow_router, FlowState, get_or_create_session, clear_session


class TestFlowRouterLLMOutOfPath(unittest.IsolatedAsyncioTestCase):

    async def test_out_of_flow_price_inquiry_steers_back(self):
        """Verify that asking price questions outside the flow returns price and attaches continuation prompt."""
        sid = "test_out_of_flow_1"
        clear_session(sid)

        resp = await flow_router.process_event(session_id=sid, text="¿Cuánto cuesta el cilindro de 30 kg?", channel="test")
        self.assertIn("30 kg", resp.text)
        self.assertIn("(Continuando con tu pedido)", resp.text)
        self.assertEqual(resp.state, FlowState.INITIAL)

    async def test_out_of_flow_hours_inquiry_with_llm(self):
        """Verify that asking conversational questions (hours, coverage) triggers LLM and steers back to state."""
        sid = "test_out_of_flow_2"
        clear_session(sid)
        session = get_or_create_session(sid)
        session.state = FlowState.WAITING_FOR_PHONE
        session.draft_order.service_type = "cilindro"

        resp = await flow_router.process_event(session_id=sid, text="¿A qué hora cierran hoy?", channel="test")
        self.assertTrue(resp.is_llm)
        self.assertIn("(Continuando con tu pedido)", resp.text)
        self.assertIn("número de teléfono celular", resp.text)
        self.assertEqual(resp.state, FlowState.WAITING_FOR_PHONE)

    async def test_address_state_rejects_fake_address(self):
        """Verify that entering a fake address in WAITING_FOR_NEW_CUSTOMER_ADDRESS is rejected."""
        sid = "test_addr_rejection"
        clear_session(sid)
        session = get_or_create_session(sid)
        session.state = FlowState.WAITING_FOR_NEW_CUSTOMER_ADDRESS
        session.draft_order.customer_name = "Juan Pérez"
        session.draft_order.customer_phone = "6691234567"

        resp = await flow_router.process_event(session_id=sid, text="vivo en la luna 123 jajaja", channel="test")
        self.assertIn("⚠️", resp.text)
        self.assertEqual(resp.state, FlowState.WAITING_FOR_NEW_CUSTOMER_ADDRESS)
        self.assertEqual(session.draft_order.delivery_address, "")

    async def test_address_state_accepts_valid_address(self):
        """Verify that entering a real Mazatlán address advances to WAITING_FOR_SCHEDULE."""
        sid = "test_addr_success"
        clear_session(sid)
        session = get_or_create_session(sid)
        session.state = FlowState.WAITING_FOR_NEW_CUSTOMER_ADDRESS
        session.draft_order.customer_name = "Juan Pérez"
        session.draft_order.customer_phone = "6691234567"

        resp = await flow_router.process_event(
            session_id=sid,
            text="Av. Insurgentes #1204, Col. Estadio, portón blanco",
            channel="test"
        )
        self.assertEqual(resp.state, FlowState.WAITING_FOR_SCHEDULE)
        self.assertIn("Dirección verificada", resp.text)
        self.assertIn("Insurgentes", session.draft_order.delivery_address)
