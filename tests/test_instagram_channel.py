"""Unit and integration tests for the Instagram Direct messaging channel."""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from src.app import app
from src.channels.instagram.adapter import InstagramAdapter
from src.channels.instagram.router import (
    _active_order_sessions,
    _process_single_instagram_event,
    add_to_cart,
    clear_cart,
    format_cart_summary,
    get_user_cart,
    ig_carts,
)
from src.models.customer import CustomerAddress


class TestInstagramChannel(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.adapter = InstagramAdapter()
        self.client = TestClient(app)
        self.igsid = "test_instagram_user_888"
        clear_cart(self.igsid)
        _active_order_sessions.pop(self.igsid, None)

    def test_webhook_verification_success(self):
        """Test GET webhook verification with valid token returns challenge."""
        response = self.client.get(
            "/webhooks/instagram",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": self.adapter.verify_token,
                "hub.challenge": "challenge_code_12345",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "challenge_code_12345")

        # Test alias route /webhook/instagram
        response_alias = self.client.get(
            "/webhook/instagram",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": self.adapter.verify_token,
                "hub.challenge": "challenge_code_67890",
            },
        )
        self.assertEqual(response_alias.status_code, 200)
        self.assertEqual(response_alias.text, "challenge_code_67890")

    def test_webhook_verification_failure(self):
        """Test GET webhook verification with invalid token returns 403."""
        response = self.client.get(
            "/webhooks/instagram",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong_token",
                "hub.challenge": "challenge_code_12345",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_parse_webhook_events_text_and_quick_reply(self):
        """Test parsing text message and quick reply events."""
        raw_payload = {
            "object": "instagram",
            "entry": [
                {
                    "id": "ig_page_100",
                    "time": 1711800000,
                    "messaging": [
                        {
                            "sender": {"id": self.igsid},
                            "recipient": {"id": "ig_page_100"},
                            "timestamp": 1711800000,
                            "message": {
                                "mid": "mid_ig_test_1",
                                "text": "Hola, necesito gas",
                            },
                        },
                        {
                            "sender": {"id": self.igsid},
                            "recipient": {"id": "ig_page_100"},
                            "timestamp": 1711800001,
                            "message": {
                                "mid": "mid_ig_test_2",
                                "text": "Cilindro de Gas",
                                "quick_reply": {"payload": "client_svc:cilindro"},
                            },
                        },
                    ],
                }
            ],
        }

        events = self.adapter.parse_webhook_events(raw_payload)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["type"], "text")
        self.assertEqual(events[0]["text"], "Hola, necesito gas")
        self.assertEqual(events[0]["igsid"], self.igsid)

        self.assertEqual(events[1]["interactive_id"], "client_svc:cilindro")
        self.assertEqual(events[1]["text"], "client_svc:cilindro")

    def test_cart_management(self):
        """Test adding, formatting, and clearing cart items."""
        from src.repositories import get_repository
        prods = get_repository().get_all_products("petroil")
        prod_id = prods[0].id if prods else "test-prod-1"

        cart = add_to_cart(self.igsid, prod_id, 2)
        self.assertEqual(cart[prod_id], 2)

        summary, total, qty = format_cart_summary(cart, "petroil")
        self.assertEqual(qty, 2)
        self.assertGreater(total, 0)
        self.assertIn("Total acumulado", summary)

        clear_cart(self.igsid)
        self.assertEqual(get_user_cart(self.igsid), {})

    def test_interactive_helpers(self):
        """Test interactive helpers return appropriate structures."""
        services = self.adapter.get_service_quick_replies()
        self.assertTrue(any(s["id"] == "client_svc:cilindro" for s in services))
        self.assertTrue(any(s["id"] == "client_svc:estacionario" for s in services))

        payments = self.adapter.get_payment_method_quick_replies()
        self.assertTrue(any(p["id"] == "client_pay:efectivo" for p in payments))
        self.assertTrue(any(p["id"] == "client_pay:terminal" for p in payments))

        ratings = self.adapter.get_rating_quick_replies(123)
        self.assertEqual(len(ratings), 5)
        self.assertTrue(any("rate:123:5" in r["id"] for r in ratings))

    async def test_process_carousel_event(self):
        """Test processing client_svc:cilindro sends product catalog generic template."""
        event = {
            "igsid": self.igsid,
            "tenant_id": "petroil",
            "type": "postback",
            "interactive_id": "client_svc:cilindro",
        }

        with patch("src.channels.instagram.router.adapter.send_generic_template", new_callable=AsyncMock) as mock_carousel, \
             patch("src.channels.instagram.router.adapter.send_sender_action", new_callable=AsyncMock) as mock_action:

            await _process_single_instagram_event(event)

            self.assertTrue(mock_carousel.called)
            elements = mock_carousel.call_args[1]["elements"]
            self.assertGreater(len(elements), 0)
            self.assertIn(self.igsid, _active_order_sessions)

    async def test_process_csat_rating_event(self):
        """Test processing CSAT rating saves rating and asks for feedback."""
        event = {
            "igsid": self.igsid,
            "tenant_id": "petroil",
            "interactive_id": "rate:456:5",
        }

        with patch("src.channels.instagram.router.adapter.send_quick_replies", new_callable=AsyncMock) as mock_qr, \
             patch("src.channels.instagram.router.get_repository") as mock_get_repo:

            repo_mock = MagicMock()
            mock_get_repo.return_value = repo_mock

            await _process_single_instagram_event(event)

            self.assertTrue(repo_mock.save_order_rating.called)
            repo_mock.save_order_rating.assert_called_with(
                tenant_id="petroil",
                order_id=456,
                rating=5,
            )
            self.assertTrue(mock_qr.called)

    def test_parse_webhook_events_changes_schema(self):
        """Test parsing Instagram events delivered under changes array schema."""
        raw_payload = {
            "object": "instagram",
            "entry": [
                {
                    "id": "28569676576032086",
                    "time": 1711800000,
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "sender": {"id": "ig_user_444"},
                                "recipient": {"id": "28569676576032086"},
                                "message": {
                                    "mid": "mid_changes_123",
                                    "text": "Hola, necesito gas estacionario",
                                },
                            },
                        }
                    ],
                }
            ],
        }
        events = self.adapter.parse_webhook_events(raw_payload)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["igsid"], "ig_user_444")
        self.assertEqual(events[0]["text"], "Hola, necesito gas estacionario")
        self.assertEqual(events[0]["msg_id"], "mid_changes_123")


if __name__ == "__main__":
    unittest.main()
