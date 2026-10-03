"""Tests for Messenger-specific enhancements: full addresses, delete address, live tracking web route."""

import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import asyncio

from fastapi.testclient import TestClient

from src.app import app
from src.channels.messenger.adapter import MessengerAdapter
from src.models.customer import CustomerAddress


class TestMessengerUpdates(unittest.TestCase):

    def setUp(self):
        self.adapter = MessengerAdapter()
        self.client = TestClient(app)

    def test_address_buttons_and_quick_replies_include_delete(self):
        """Test that address quick replies and buttons display street name and delete button."""
        addrs = [
            CustomerAddress(id=1, address="Misión San Javier 5246, Las Misiones", alias="Principal"),
            CustomerAddress(id=2, address="Av del Mar 100, Flamingos", alias="Casa Playa"),
        ]
        replies = self.adapter.get_customer_addresses_quick_replies(addrs)
        self.assertTrue(any(r["id"] == "client_addr:del_menu" for r in replies))
        self.assertTrue(any("Misión" in r["title"] for r in replies))
        self.assertTrue(any("Av del Mar" in r["title"] for r in replies))

        buttons = self.adapter.get_customer_addresses_buttons(addrs)
        self.assertTrue(any(b["id"] == "client_addr:del_menu" for b in buttons))

    def test_live_tracking_endpoints(self):
        """Test that /tracking/{order_id} and /api/tracking/{order_id} respond correctly."""
        # Using mock order
        mock_order = MagicMock()
        mock_order.id = 123
        mock_order.status = "in_route"
        mock_order.customer_name = "Oscar Cliente"
        mock_order.delivery_address = "Misión San Javier 5246, Mazatlán"
        mock_order.total_amount = 705.0
        mock_order.payment_method = "Efectivo"
        mock_order.delivery_lat = 23.2647
        mock_order.delivery_lng = -106.4076
        mock_order.driver_id = "drv-test-1"

        mock_driver = MagicMock()
        mock_driver.name = "Oscar Vizcarra"
        mock_driver.phone = "6699123501"
        mock_driver.vehicle_plate = "V-102"
        mock_driver.current_lat = 23.2500
        mock_driver.current_lng = -106.4200

        with patch("src.tracking.router.get_repository") as mock_get_repo:
            repo_mock = MagicMock()
            repo_mock.get_order_by_id.return_value = mock_order
            repo_mock.get_driver.return_value = mock_driver
            mock_get_repo.return_value = repo_mock

            # 1. HTML tracking page
            resp_html = self.client.get("/tracking/123")
            self.assertEqual(resp_html.status_code, 200)
            self.assertIn("Rastreo en Tiempo Real", resp_html.text)
            self.assertIn("Oscar Vizcarra", resp_html.text)
            self.assertIn("Misión San Javier", resp_html.text)
            self.assertIn("leaflet", resp_html.text.lower())

            # 2. JSON API
            resp_api = self.client.get("/api/tracking/123")
            self.assertEqual(resp_api.status_code, 200)
            data = resp_api.json()
            self.assertTrue(data["ok"])
            self.assertEqual(data["driver"]["name"], "Oscar Vizcarra")
            self.assertEqual(data["driver"]["lat"], 23.2500)
            self.assertIn("google_maps_url", data)

    def test_live_tracking_delivered_view(self):
        """Test that /tracking/{order_id} renders delivered completion view when order is finished."""
        mock_order = MagicMock()
        mock_order.id = 456
        mock_order.status = "delivered"
        mock_order.customer_name = "Cliente Feliz"
        mock_order.delivery_address = "Av del Mar 100, Mazatlán"
        mock_order.total_amount = 705.0
        mock_order.currency = "MXN"
        mock_order.driver_id = "drv-test-1"

        with patch("src.tracking.router.get_repository") as mock_get_repo:
            repo_mock = MagicMock()
            repo_mock.get_order_by_id.return_value = mock_order
            repo_mock.get_driver.return_value = None
            mock_get_repo.return_value = repo_mock

            resp_html = self.client.get("/tracking/456")
            self.assertEqual(resp_html.status_code, 200)
            self.assertIn("Pedido Entregado con Éxito", resp_html.text)
            self.assertIn("Servicio Finalizado", resp_html.text)
            self.assertNotIn("leaflet", resp_html.text.lower())

    def test_cylinder_catalog_elements_with_buttons(self):
        """Test that cylinder catalog elements include active Comprar buttons by default."""
        elements = self.adapter.get_cylinder_catalog_elements("petroil", include_buttons=True)
        self.assertTrue(len(elements) > 0)
        for el in elements:
            self.assertIn("buttons", el)
            self.assertTrue(any("Comprar" in b.get("title", "") for b in el["buttons"]))

    def test_identity_store_get_phone_for_channel_user(self):
        """Test that identity_store.get_phone_for_channel_user does not raise AttributeError."""
        from src.repositories.identity_store import identity_store
        phone = identity_store.get_phone_for_channel_user("messenger", "unknown_user_123")
        # Should return None without raising error
        self.assertIsNone(phone)

    def test_high_precision_geocoding(self):
        """Test that geocode_address resolves Mexican addresses with street number accuracy."""
        from src.services.geocoding import geocode_address
        lat, lng, match_addr = geocode_address("Av. Ejercito Mexicano 2004, Palos Prietos, Mazatlan")
        self.assertAlmostEqual(lat, 23.23, delta=0.1)
        self.assertAlmostEqual(lng, -106.41, delta=0.1)
        self.assertIn("2004", match_addr)


if __name__ == "__main__":
    unittest.main()

