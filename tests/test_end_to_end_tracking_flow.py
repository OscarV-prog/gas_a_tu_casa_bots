"""Unit and integration tests for end-to-end order tracking & survey across Telegram, WhatsApp, Messenger."""

import unittest
from unittest.mock import MagicMock, patch
import asyncio

from src.repositories import get_repository
from src.services.dispatch import dispatch_order
from src.services.notifications import (
    send_client_live_location,
    notify_client,
    notify_delivery_survey,
)
from src.tools.create_order import create_order


class TestEndToEndTrackingFlow(unittest.TestCase):

    def setUp(self):
        self.repo = get_repository()
        self.tenant_id = "petroil"

    def test_messenger_live_location_sends_button_template(self):
        """Test that send_client_live_location sends live tracking link and quick reply cancel button on Messenger."""
        with patch("src.services.notifications._send_messenger_button_template_sync", return_value=True) as mock_send_msgr, \
             patch("src.services.notifications._send_messenger_buttons_sync", return_value=True) as mock_send_qr:
            msg_id = send_client_live_location(
                channel_user_id="psid_user_test_123",
                latitude=23.2435,
                longitude=-106.4123,
                channel="messenger",
                order_id=999,
            )
            self.assertEqual(msg_id, 888888)
            mock_send_msgr.assert_called_once()
            call_args = mock_send_msgr.call_args[0]
            self.assertEqual(call_args[0], "psid_user_test_123")
            self.assertIn("va en camino", call_args[1])
            buttons = call_args[2]
            self.assertEqual(len(buttons), 2)
            self.assertEqual(buttons[0]["type"], "web_url")
            self.assertEqual(buttons[1]["type"], "web_url")
            self.assertTrue("tracking/999" in buttons[0]["url"])
            self.assertTrue("google.com/maps" in buttons[1]["url"])
            mock_send_qr.assert_called_once()

    def test_messenger_delivery_survey(self):
        """Test that notify_delivery_survey sends quick replies with 5 stars on Messenger."""
        # Create a mock order with channel = messenger
        mock_order = MagicMock()
        mock_order.id = 777
        mock_order.channel = "messenger"
        mock_order.channel_user_id = "psid_survey_123"
        mock_order.customer_phone = "6691234567"
        mock_order.total_amount = 670.0
        mock_order.currency = "MXN"
        mock_order.payment_method = "Efectivo"
        mock_order.driver_id = None

        with patch.object(self.repo, "get_order_by_id", return_value=mock_order), \
             patch("src.services.notifications._send_messenger_buttons_sync", return_value=True) as mock_msgr_buttons:
            result = notify_delivery_survey(777, self.tenant_id)
            self.assertTrue(result)
            mock_msgr_buttons.assert_called_once()
            recipient, text, buttons = mock_msgr_buttons.call_args[0]
            self.assertEqual(recipient, "psid_survey_123")
            self.assertIn("entregado exitosamente", text)
            self.assertEqual(len(buttons), 5)
            self.assertEqual(buttons[0]["id"], "rate:777:5")

    def test_create_order_does_not_auto_dispatch(self):
        """Test that create_order tool does NOT auto-dispatch; leaves order pending for Torre de Control."""
        with patch("src.services.dispatch.dispatch_order", return_value=True) as mock_dispatch:
            res = create_order.invoke(
                {
                    "customer_name": "Test Cliente",
                    "customer_phone": "6699887766",
                    "delivery_address": "Av del Mar 100, Mazatlán",
                    "items": [{"product_name": "Cilindro de Gas LP 30 kg", "quantity": 1}],
                    "delivery_schedule": "Lo antes posible",
                    "payment_method": "Efectivo",
                },
                config={"configurable": {"tenant_id": self.tenant_id, "channel": "telegram", "channel_user_id": "12345678"}},
            )
            self.assertIn("confirmado", res.lower())
            mock_dispatch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
