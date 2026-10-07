"""Test unitario para validar el registro de nueva dirección por GPS en clientes."""

import unittest
from unittest.mock import MagicMock, patch

from src.services.flow_router import (
    flow_router,
    FlowState,
    get_or_create_session,
    clear_session,
)


class TestFlowRouterLocationOrder(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.session_id = "test_user_new_addr_123"
        clear_session(self.session_id)

    def tearDown(self):
        clear_session(self.session_id)

    @patch("src.services.flow_router.reverse_geocode")
    @patch("src.services.flow_router.get_repository")
    async def test_gps_location_in_new_customer_address_advances_order(self, mock_get_repo, mock_rev_geo):
        """Verifica que enviar ubicación GPS en WAITING_FOR_NEW_CUSTOMER_ADDRESS avanza el pedido a WAITING_FOR_SCHEDULE."""
        mock_rev_geo.return_value = "Avenida Óscar Pérez Escobosa 3416, Alarcón Infonavit, Mazatlán, Sinaloa, 82132"
        mock_repo = MagicMock()
        mock_repo.get_driver_by_telegram_id.return_value = MagicMock(id=99, name="Chofer Test")
        mock_repo.get_driver_by_phone.return_value = MagicMock(id=99, name="Chofer Test")
        mock_repo.get_orders_by_driver.return_value = []
        mock_get_repo.return_value = mock_repo

        session = get_or_create_session(self.session_id, channel="telegram", channel_user_id="123456")
        session.state = FlowState.WAITING_FOR_NEW_CUSTOMER_ADDRESS
        session.draft_order.customer_name = "Juan Perez"
        session.draft_order.customer_phone = "6691234567"
        session.draft_order.items = [{"product_id": "gas-lp-30kg", "product_name": "Cilindro 30 kg", "quantity": 1, "unit_price": 670.0}]

        # Enviar ubicación GPS
        resp = await flow_router.process_event(
            session_id=self.session_id,
            location={"latitude": 23.2654, "longitude": -106.4123},
            channel="telegram",
            channel_user_id="123456",
        )

        # 1. No debe interceptarse como chofer en despacho
        self.assertNotIn("Tu posición en tiempo real ha sido actualizada para el monitoreo de ruta", resp.text)
        self.assertIn("Avenida Óscar Pérez Escobosa 3416", resp.text)
        self.assertIn("qué día y horario", resp.text.lower())

        # 2. El estado debe avanzar a WAITING_FOR_SCHEDULE
        self.assertEqual(session.state, FlowState.WAITING_FOR_SCHEDULE)
        self.assertEqual(session.draft_order.delivery_lat, 23.2654)
        self.assertEqual(session.draft_order.delivery_lng, -106.4123)
        self.assertEqual(session.draft_order.delivery_address, "Avenida Óscar Pérez Escobosa 3416, Alarcón Infonavit, Mazatlán, Sinaloa, 82132")

        # 3. Si el usuario responde "Okey", debe continuar al método de pago sin error de dirección corta
        resp2 = await flow_router.process_event(
            session_id=self.session_id,
            text="Okey",
            channel="telegram",
            channel_user_id="123456",
        )
        self.assertNotIn("La dirección es demasiado corta", resp2.text)
        self.assertEqual(session.state, FlowState.WAITING_FOR_PAYMENT_METHOD)
        self.assertEqual(session.draft_order.delivery_schedule, "Lo antes posible")
        self.assertIn("método de pago", resp2.text.lower())


if __name__ == "__main__":
    unittest.main()
