import asyncio
import os
import unittest
from unittest.mock import AsyncMock, PropertyMock, patch

from src.repositories.sqlite_repo import SqliteRepository
from src.services.notifications import notify_delivery_survey
from src.channels.whatsapp.router import process_whatsapp_event
from src.channels.messenger.router import _process_single_messenger_event


class TestSurveyAndRatings(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        os.environ["DATA_SOURCE"] = "sqlite"
        self.repo = SqliteRepository()
        self.tenant_id = "petroil"

    async def test_notify_delivery_survey_5_stars_whatsapp(self):
        """Verify delivery survey sends a 5-star interactive list with compliant button label."""
        order = self.repo.create_order(
            tenant_id=self.tenant_id,
            customer_name="Test Survey Customer",
            customer_phone="6691234567",
            delivery_address="Calle Test 123",
            items=[{"product_name": "Cilindro 30kg", "quantity": 1, "unit_price": 650.0}],
            channel="whatsapp",
        )

        with patch("src.channels.whatsapp.adapter.WhatsAppAdapter.is_configured", new_callable=PropertyMock, return_value=True), \
             patch("src.channels.whatsapp.adapter.WhatsAppAdapter.send_interactive_list", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = True
            ok = notify_delivery_survey(order.id, self.tenant_id)
            self.assertTrue(ok)
            mock_list.assert_called_once()
            call_kwargs = mock_list.call_args.kwargs

            # Check button_label (<= 20 chars, no emojis)
            button_label = call_kwargs["button_label"]
            self.assertLessEqual(len(button_label), 20)
            self.assertNotIn("⭐", button_label)
            self.assertEqual(button_label, "Calificar Chofer")

            # Check sections has 5 stars
            sections = call_kwargs["sections"]
            self.assertEqual(len(sections), 1)
            rows = sections[0]["rows"]
            self.assertEqual(len(rows), 5)
            row_ids = [r["id"] for r in rows]
            for star in range(1, 6):
                self.assertIn(f"rate_driver:{order.id}:{star}", row_ids)

    async def test_whatsapp_survey_text_comment_thanks_user(self):
        """When user rates and then texts their feedback, bot MUST send the completion thank-you message."""
        order = self.repo.create_order(
            tenant_id=self.tenant_id,
            customer_name="Test Rating User",
            customer_phone="6699876543",
            delivery_address="Avenida Test 456",
            items=[{"product_name": "Cilindro 30kg", "quantity": 1, "unit_price": 650.0}],
            channel="whatsapp",
        )
        wa_id = "5216699876543"

        with patch("src.channels.whatsapp.adapter.WhatsAppAdapter.send_interactive_list", new_callable=AsyncMock) as mock_list, \
             patch("src.channels.whatsapp.adapter.WhatsAppAdapter.send_text_message", new_callable=AsyncMock) as mock_text:
            mock_list.return_value = True

            # Step 1: User selects 5 stars via button or list callback
            await process_whatsapp_event({
                "wa_id": wa_id,
                "text": "",
                "interactive_id": f"rate_driver:{order.id}:5",
                "phone_number_id": "123456",
            })
            mock_list.assert_called_once()

            # Step 2: User responds with text details instead of tapping a button
            await process_whatsapp_event({
                "wa_id": wa_id,
                "text": "Llegó super rápido el chofer y fue muy atento",
                "interactive_id": "",
                "phone_number_id": "123456",
            })

            # Bot MUST send the completion thank you message
            mock_text.assert_called_once()
            sent_msg = mock_text.call_args[0][1]
            self.assertIn("ENCUESTA COMPLETADA CON ÉXITO", sent_msg)
            self.assertIn("¡Muchas gracias por tu tiempo y valiosa opinión!", sent_msg)
            self.assertIn("⭐⭐⭐⭐⭐ (5/5)", sent_msg)

    async def test_messenger_survey_text_comment_thanks_user(self):
        """When user rates in Messenger and then texts feedback, bot MUST send completion thank-you message."""
        order = self.repo.create_order(
            tenant_id=self.tenant_id,
            customer_name="Test Messenger User",
            customer_phone="6695551234",
            delivery_address="Calle Messenger 789",
            items=[{"product_name": "Cilindro 30kg", "quantity": 1, "unit_price": 650.0}],
            channel="messenger",
        )
        psid = "fb_user_123456"

        with patch("src.channels.messenger.adapter.MessengerAdapter.send_sender_action", new_callable=AsyncMock), \
             patch("src.channels.messenger.adapter.MessengerAdapter.send_quick_replies", new_callable=AsyncMock) as mock_qr, \
             patch("src.channels.messenger.adapter.MessengerAdapter.send_text_message", new_callable=AsyncMock) as mock_text:
            mock_qr.return_value = True

            # Step 1: User selects 4 stars
            await _process_single_messenger_event({
                "psid": psid,
                "text": "",
                "interactive_id": f"rate:{order.id}:4",
            })
            mock_qr.assert_called_once()

            # Step 2: User sends text feedback
            await _process_single_messenger_event({
                "psid": psid,
                "text": "Todo muy bien, excelente servicio",
                "interactive_id": "",
            })

            mock_text.assert_called_once()
            sent_msg = mock_text.call_args[0][1]
            self.assertIn("ENCUESTA COMPLETADA CON ÉXITO", sent_msg)
            self.assertIn("¡Muchas gracias por tu tiempo y valiosa opinión!", sent_msg)
            self.assertIn("⭐⭐⭐⭐ (4/5)", sent_msg)

    async def test_whatsapp_delivery_sends_ticket_before_survey(self):
        """Verify delivery notification in WhatsApp sends payment receipt before interactive survey."""
        order = self.repo.create_order(
            tenant_id=self.tenant_id,
            customer_name="Oscar Cliente",
            customer_phone="6691234567",
            delivery_address="Calle Test 123",
            items=[{"product_name": "Cilindro 30kg", "quantity": 1, "unit_price": 705.0}],
            channel="whatsapp",
        )

        with patch("src.services.notifications._send_whatsapp_message_sync", return_value=True) as mock_ticket_send, \
             patch("src.channels.whatsapp.adapter.WhatsAppAdapter.is_configured", new_callable=PropertyMock, return_value=True), \
             patch("src.channels.whatsapp.adapter.WhatsAppAdapter.send_interactive_list", new_callable=AsyncMock, return_value=True) as mock_survey:
            ok = notify_delivery_survey(order.id, self.tenant_id)
            self.assertTrue(ok)

            # Ticket was sent first
            mock_ticket_send.assert_called_once()
            ticket_msg = mock_ticket_send.call_args[0][1]
            self.assertIn("COMPROBANTE DE COMPRA", ticket_msg)
            self.assertIn(f"#{order.id}", ticket_msg)
            self.assertIn("Oscar Cliente", ticket_msg)
            self.assertIn("ticket.pdf", ticket_msg)

            # Survey was also sent
            mock_survey.assert_called_once()

    async def test_messenger_delivery_sends_ticket_before_survey(self):
        """Verify delivery notification in Messenger sends payment receipt before interactive survey."""
        order = self.repo.create_order(
            tenant_id=self.tenant_id,
            customer_name="Oscar Messenger",
            customer_phone="6699887766",
            delivery_address="Calle Test 456",
            items=[{"product_name": "Cilindro 20kg", "quantity": 1, "unit_price": 450.0}],
            channel="messenger",
        )

        with patch("src.services.notifications._send_messenger_message_sync", return_value=True) as mock_ticket_send, \
             patch("src.channels.messenger.adapter.MessengerAdapter.is_configured", new_callable=PropertyMock, return_value=True), \
             patch("src.services.notifications._send_messenger_buttons_sync", return_value=True) as mock_survey:
            ok = notify_delivery_survey(order.id, self.tenant_id)
            self.assertTrue(ok)

            # Ticket was sent first
            mock_ticket_send.assert_called_once()
            ticket_msg = mock_ticket_send.call_args[0][1]
            self.assertIn("COMPROBANTE DE COMPRA", ticket_msg)
            self.assertIn(f"#{order.id}", ticket_msg)
            self.assertIn("Oscar Messenger", ticket_msg)
            self.assertIn("ticket.pdf", ticket_msg)

            # Survey buttons were also sent
            mock_survey.assert_called_once()


if __name__ == "__main__":
    unittest.main()

