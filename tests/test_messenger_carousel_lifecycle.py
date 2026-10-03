"""Test Messenger product carousel and buy button lifecycle."""

import time
import unittest
from unittest.mock import AsyncMock, patch, MagicMock

from fastapi.testclient import TestClient
from src.app import app
from src.channels.messenger.adapter import MessengerAdapter
from src.channels.messenger.router import (
    _process_single_messenger_event,
    _active_order_sessions,
    msgr_carts,
    clear_cart,
)
from src.models.order import Order


class TestMessengerCarouselLifecycle(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.psid = "test_user_psid_999"
        clear_cart(self.psid)
        _active_order_sessions.pop(self.psid, None)

    async def test_carousel_active_during_order_creation_and_inactive_after_delivered(self):
        adapter = MessengerAdapter()

        # 1. Al iniciar pedido con client_svc:cilindro, se envía el carrusel con botones Comprar activos
        event_svc = {
            "psid": self.psid,
            "tenant_id": "petroil",
            "type": "postback",
            "postback": {"payload": "client_svc:cilindro"},
            "interactive_id": "client_svc:cilindro",
        }

        with patch("src.channels.messenger.router.adapter.send_generic_template", new_callable=AsyncMock) as mock_send_carousel, \
             patch("src.channels.messenger.router.adapter.send_quick_replies", new_callable=AsyncMock) as mock_send_qr, \
             patch("src.channels.messenger.router.adapter.send_text_message", new_callable=AsyncMock) as mock_send_text:

            await _process_single_messenger_event(event_svc)

            # Verificar que el carrusel se envió y NO se enviaron botones abajo
            self.assertTrue(mock_send_carousel.called)
            self.assertFalse(mock_send_qr.called)
            sent_elements = mock_send_carousel.call_args[1]["elements"]
            self.assertGreater(len(sent_elements), 0)
            for el in sent_elements:
                self.assertIn("buttons", el)
                self.assertTrue(any(b.get("title") == "🛒 Comprar" for b in el["buttons"]))

            # Verificar que la sesión quedó marcada como activa
            self.assertIn(self.psid, _active_order_sessions)

            # 2. Pulsar botón "🛒 Comprar" avanza directamente
            event_add = {
                "psid": self.psid,
                "tenant_id": "petroil",
                "type": "postback",
                "postback": {"payload": "cart_add:prod_cilindro_30:1"},
                "interactive_id": "cart_add:prod_cilindro_30:1",
            }
            await _process_single_messenger_event(event_add)
            # Al no tener teléfono registrado, solicita el celular para avanzar
            self.assertTrue(mock_send_text.called)
            text_arg = mock_send_text.call_args[0][1] if len(mock_send_text.call_args[0]) > 1 else mock_send_text.call_args[1].get("text", "")
            self.assertIn("celular", text_arg.lower())
            self.assertEqual(msgr_carts[self.psid].get("prod_cilindro_30"), 1)

            # 3. Simular que el pedido se cierra y se entrega
            clear_cart(self.psid)
            _active_order_sessions.pop(self.psid, None)
            from src.services.flow_router import FlowState, flow_router
            sess = flow_router.get_session(self.psid)
            sess.state = FlowState.COMPLETED

            # Mock de orden entregada
            mock_order = MagicMock(spec=Order)
            mock_order.id = 777
            mock_order.status = "delivered"

            with patch("src.channels.messenger.router.get_repository") as mock_repo_getter:
                mock_repo = MagicMock()
                mock_repo.get_customer.return_value = MagicMock(phone="6691234567")
                mock_repo.get_orders_by_customer_phone.return_value = [mock_order]
                mock_repo_getter.return_value = mock_repo

                # Pulsar el botón del banner viejo cuando el pedido ya está entregado y cerrado
                mock_send_qr.reset_mock()
                await _process_single_messenger_event(event_add)

                # Debe responder que el botón expiró porque el pedido ya fue entregado y cerrado
                self.assertTrue(mock_send_qr.called)
                qr_call_text = mock_send_qr.call_args[1]["text"]
                self.assertIn("cerrado y entregado", qr_call_text)
                self.assertIn("ha expirado", qr_call_text)
                # Debe ofrecer botón para levantar un nuevo pedido
                qr_options = mock_send_qr.call_args[1]["quick_replies"]
                self.assertTrue(any(q["id"] == "client_svc:cilindro" for q in qr_options))

    async def test_carousel_direct_advance_with_registered_customer(self):
        """Verifica que un usuario con cuenta avance directo a seleccionar dirección al pulsar Comprar."""
        from src.models.customer import Customer, CustomerAddress
        from src.models.product import Product
        from src.services.flow_router import FlowState, flow_router

        psid = "user_direct_advance_123"
        clear_cart(psid)
        _active_order_sessions[psid] = time.time()
        sess = flow_router.get_session(psid)
        sess.state = FlowState.WAITING_FOR_PRODUCT_OR_QUANTITY

        mock_cust = Customer(
            id=10,
            tenant_id="petroil",
            name="Roberto Gómez",
            phone="6699887766",
            address="Av. Ejército Mexicano 123",
            channel="messenger",
            channel_user_id=psid,
            addresses=[
                CustomerAddress(id=1, address="Av. Ejército Mexicano 123, Palos Prietos", alias="Casa"),
                CustomerAddress(id=2, address="Calle Benito Juárez 456, Centro", alias="Oficina"),
            ]
        )

        mock_prod = Product(
            id="gas-lp-30kg",
            tenant_id="petroil",
            name="Cilindro 30 kg",
            price=670.0,
            description="Cilindro 30 kg",
            category="CILINDRO",
            unit="pieza",
        )

        with patch("src.channels.messenger.router.get_repository") as mock_repo_getter, \
             patch("src.channels.messenger.router.adapter.send_quick_replies", new_callable=AsyncMock) as mock_send_qr, \
             patch("src.channels.messenger.router.adapter.send_generic_template", new_callable=AsyncMock) as mock_send_carousel:

            mock_repo = MagicMock()
            mock_repo.get_all_products.return_value = [mock_prod]
            mock_repo.get_customer.return_value = mock_cust
            mock_repo.get_customer_by_phone.return_value = mock_cust
            mock_repo.get_orders_by_customer_phone.return_value = []
            mock_repo_getter.return_value = mock_repo

            event_buy = {
                "psid": psid,
                "tenant_id": "petroil",
                "type": "postback",
                "postback": {"payload": "cart_add:gas-lp-30kg:1"},
                "interactive_id": "cart_add:gas-lp-30kg:1",
            }

            await _process_single_messenger_event(event_buy)

            # Debe haber avanzado a WAITING_FOR_PHONE para solicitar el celular
            self.assertEqual(sess.state, FlowState.WAITING_FOR_PHONE)
            # El item debe haber quedado registrado en el draft del pedido
            self.assertEqual(len(sess.draft_order.items), 1)
            self.assertEqual(sess.draft_order.items[0]["product_id"], "gas-lp-30kg")

            # Al ingresar su teléfono celular a 10 dígitos, avanza a direcciones guardadas
            event_phone = {
                "psid": psid,
                "tenant_id": "petroil",
                "type": "text",
                "text": "6699123456",
            }
            await _process_single_messenger_event(event_phone)
            self.assertEqual(sess.state, FlowState.WAITING_FOR_ADDRESS_SELECTION)
            self.assertTrue(mock_send_qr.called)
            qr_text = mock_send_qr.call_args[1]["text"]
            self.assertIn("direcciones", qr_text.lower())
            qr_replies = mock_send_qr.call_args[1]["quick_replies"]
            self.assertTrue(any(q["id"] == "client_addr:1" for q in qr_replies))
            self.assertTrue(any("Ejército" in q.get("title", "") for q in qr_replies))
            self.assertTrue(any(q["id"] == "client_addr:2" for q in qr_replies))
            self.assertTrue(any(q["id"] == "client_addr:new" for q in qr_replies))


if __name__ == "__main__":
    unittest.main()

