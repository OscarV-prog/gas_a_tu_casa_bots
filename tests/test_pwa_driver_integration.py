"""Unit tests for Driver PWA Integration and Real-Time Omnichannel Customer Notifications."""

import unittest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from src.app import app
from src.repositories.sqlite_repo import SqliteRepository


class TestPwaDriverIntegration(unittest.TestCase):
    def setUp(self):
        self.repo = SqliteRepository()
        self.tenant_id = "petroil"

        # Patch get_repository across all modules to use local SqliteRepository
        self._patch_repo_admin = patch("src.admin.router.get_repository", return_value=self.repo)
        self._patch_repo_events = patch("src.services.order_events.get_repository", return_value=self.repo)
        self._patch_repo_sync = patch("src.services.pwa_sync_service.get_repository", return_value=self.repo)

        self._patch_repo_admin.start()
        self._patch_repo_events.start()
        self._patch_repo_sync.start()

        # Stop any background task loop from interfering with isolated tests
        from src.services.pwa_sync_service import stop_pwa_sync_service
        stop_pwa_sync_service()

        self.client = TestClient(app, raise_server_exceptions=False)

        import time
        import uuid
        from src.services.order_events import _EVENT_DEDUP_CACHE, _LAST_DRIVER_GPS_NOTIF
        _EVENT_DEDUP_CACHE.clear()
        _LAST_DRIVER_GPS_NOTIF.clear()

        # Create a test driver with unique phone/id
        uid = uuid.uuid4().hex[:8]
        self.driver = self.repo.register_or_link_driver_telegram(
            tenant_id=self.tenant_id,
            phone=f"669{int(time.time()*1000)%10000000:07d}",
            telegram_user_id=f"tg_{uid}",
            name=f"Chofer PWA {uid}",
        )
        self.repo.update_driver(self.driver.id, {
            "vehicle_plate": "PWA-GAS-01",
        })
        self.repo.update_driver_location(self.driver.id, 23.2300, -106.4200)

        # Create a test customer order
        self.order = self.repo.create_order(
            tenant_id=self.tenant_id,
            customer_name="Cliente PWA Test",
            customer_phone="6695551234",
            delivery_address="Av. Costera 1234, Mazatlán",
            items=[{"product_name": "Cilindro de Gas LP 30 kg", "quantity": 1, "unit_price": 670.0}],
            channel="telegram",
            channel_user_id="client_tg_chat_777",
            delivery_lat=23.2350,
            delivery_lng=-106.4250,
        )

    def tearDown(self):
        self._patch_repo_admin.stop()
        self._patch_repo_events.stop()
        self._patch_repo_sync.stop()

    def test_pwa_driver_get_orders(self):
        """PWA Driver fetches active assigned orders."""
        self.repo.assign_order_to_driver(self.tenant_id, self.order.id, self.driver.id)
        res = self.client.get(f"/api/admin/drivers/{self.driver.id}/orders")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsInstance(data, list)
        self.assertTrue(any(o["id"] == self.order.id for o in data))

    @patch("src.services.order_events.send_client_live_location", return_value=554433)
    @patch("src.services.order_events.notify_client", return_value=True)
    def test_pwa_driver_set_status_in_route(self, mock_notify, mock_live):
        """When PWA driver presses 'Voy en Camino' (EN_RUTA), customer receives live GPS tracking."""
        self.repo.assign_order_to_driver(self.tenant_id, self.order.id, self.driver.id)

        res = self.client.put(
            f"/api/admin/drivers/{self.driver.id}/orders/{self.order.id}/status",
            json={"status": "EN_RUTA"},
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["status"], "IN_ROUTE")

        # Verify DB status
        ord_db = self.repo.get_order_by_id(self.tenant_id, self.order.id)
        self.assertEqual(ord_db.status, "in_route")

        # Verify customer received live location tracking
        mock_live.assert_called_once()
        call_kwargs = mock_live.call_args[1]
        self.assertEqual(call_kwargs["order_id"], self.order.id)

    @patch("src.services.order_events.notify_delivery_survey", return_value=True)
    def test_pwa_driver_set_status_delivered(self, mock_survey):
        """When PWA driver marks order as 'ENTREGADO', customer receives 5-star survey."""
        self.repo.assign_order_to_driver(self.tenant_id, self.order.id, self.driver.id)
        self.repo.update_order_status(self.tenant_id, self.order.id, "in_route")

        res = self.client.put(
            f"/api/admin/drivers/{self.driver.id}/orders/{self.order.id}/status",
            json={"status": "ENTREGADO", "signature": "data:image/png;base64,mocked"},
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["status"], "DELIVERED")

        # Verify DB status
        ord_db = self.repo.get_order_by_id(self.tenant_id, self.order.id)
        self.assertEqual(ord_db.status, "delivered")

        # Verify customer delivery survey was triggered
        mock_survey.assert_called_once_with(self.order.id, self.tenant_id)

    @patch("src.services.order_events.edit_client_live_location", return_value=True)
    def test_pwa_driver_gps_location_update(self, mock_edit_live):
        """When PWA driver transmits GPS coordinates, active order tracking is updated."""
        self.repo.assign_order_to_driver(self.tenant_id, self.order.id, self.driver.id)
        self.repo.update_order_status(self.tenant_id, self.order.id, "in_route")
        self.repo.set_order_live_location(self.tenant_id, self.order.id, "client_tg_chat_777", 554433)

        new_lat = 23.2388
        new_lng = -106.4299
        res = self.client.post(
            f"/api/admin/drivers/{self.driver.id}/location",
            json={"lat": new_lat, "lng": new_lng},
        )
        self.assertEqual(res.status_code, 200)

        # Verify driver location in DB was updated
        drv_db = self.repo.get_driver(self.driver.id)
        self.assertAlmostEqual(drv_db.current_lat, new_lat, places=3)
        self.assertAlmostEqual(drv_db.current_lng, new_lng, places=3)

        # Verify customer's live map pin was edited
        mock_edit_live.assert_called_once_with(
            channel_user_id="client_tg_chat_777",
            message_id=554433,
            latitude=new_lat,
            longitude=new_lng,
            channel="telegram",
        )

    @patch("src.services.order_events.notify_order_assigned", return_value=True)
    @patch("src.services.order_events.notify_order_in_route", return_value=True)
    @patch("src.services.order_events.notify_order_delivered", return_value=True)
    def test_background_pwa_sync_service_transitions(self, mock_deliv, mock_route, mock_assign):
        """Background synchronizer detects external changes from NestJS/PostgreSQL and fires alerts."""
        import asyncio
        from src.services.pwa_sync_service import poll_order_updates_once, _KNOWN_ORDER_STATES
        import src.services.pwa_sync_service as sync_mod

        # Reset known states and force initialized
        _KNOWN_ORDER_STATES.clear()
        sync_mod._INITIALIZED = True

        # 1. Snapshot existing orders in repository
        orders = self.repo.get_all_orders_admin(self.tenant_id, "all")
        for o in orders:
            _KNOWN_ORDER_STATES[str(o.get("id"))] = {"status": str(o.get("status")), "driver_id": o.get("driver_id")}

        oid = str(self.order.id)
        _KNOWN_ORDER_STATES[oid] = {"status": "pending", "driver_id": None}

        # Order assigned in DB
        self.repo.assign_order_to_driver(self.tenant_id, self.order.id, self.driver.id)
        events = asyncio.run(poll_order_updates_once(self.tenant_id))
        self.assertGreaterEqual(events, 1)
        mock_assign.assert_called_with(self.tenant_id, oid, self.driver.id)

        # Order goes in route in DB (by PWA driver)
        self.repo.update_order_status(self.tenant_id, self.order.id, "in_route")
        events2 = asyncio.run(poll_order_updates_once(self.tenant_id))
        self.assertGreaterEqual(events2, 1)
        mock_route.assert_called_with(self.tenant_id, oid, self.driver.id)

        # Order delivered in DB (by PWA driver)
        self.repo.update_order_status(self.tenant_id, self.order.id, "delivered")
        events3 = asyncio.run(poll_order_updates_once(self.tenant_id))
        self.assertGreaterEqual(events3, 1)
        mock_deliv.assert_called_with(self.tenant_id, oid)


if __name__ == "__main__":
    unittest.main()
