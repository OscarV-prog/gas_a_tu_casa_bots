"""Unit tests for Driver Real-Time Live Location logic."""

import unittest
from unittest.mock import MagicMock, patch
from src.repositories.sqlite_repo import SqliteRepository
from driver_bot import recibir_ubicacion_tiempo_real


class TestDriverLiveLocation(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.repo = SqliteRepository()
        self.tenant_id = "petroil"
        self._patcher = patch("driver_bot.get_repository", return_value=self.repo)
        self._patcher.start()

        # Create or fetch a test driver
        self.driver = self.repo.register_or_link_driver_telegram(
            tenant_id=self.tenant_id,
            phone="6699991122",
            telegram_user_id="test_driver_live_tg_123",
            name="Chofer Test Live Location",
        )
        from src.database.connection import get_db_connection
        with get_db_connection() as conn:
            conn.execute("DELETE FROM orders WHERE driver_id = ?", (self.driver.id,))

    def tearDown(self):
        self._patcher.stop()
        from src.database.connection import get_db_connection
        with get_db_connection() as conn:
            conn.execute("DELETE FROM orders WHERE driver_id = ?", (self.driver.id,))

    async def test_live_location_updates_on_gps_message_and_edited_message(self):
        # Create an order in route for this driver
        order = self.repo.create_order(
            tenant_id=self.tenant_id,
            customer_name="Cliente Test Live",
            customer_phone="6698887766",
            delivery_address="Calle Del Mar 999, Mazatlan",
            items=[{"product_name": "Cilindro de Gas LP 30 kg", "quantity": 1, "unit_price": 670.0}],
            channel="telegram",
            channel_user_id="test_client_chat_456",
            delivery_lat=23.2345,
            delivery_lng=-106.4567,
        )
        self.repo.assign_order_to_driver(self.tenant_id, order.id, self.driver.id)
        self.repo.update_order_status(self.tenant_id, order.id, "in_route")

        # Mock Telegram update with real driver location (different from customer delivery_lat)
        driver_real_lat = 23.2891
        driver_real_lng = -106.3912

        mock_update = MagicMock()
        mock_update.effective_user.id = "test_driver_live_tg_123"
        mock_update.message = MagicMock()
        from unittest.mock import AsyncMock
        mock_update.message.reply_text = AsyncMock()
        mock_update.message.location.latitude = driver_real_lat
        mock_update.message.location.longitude = driver_real_lng
        mock_update.edited_message = None

        mock_context = MagicMock()

        with patch("driver_bot.send_client_live_location", return_value=998877) as mock_send_live, \
             patch("driver_bot.edit_client_live_location", return_value=True) as mock_edit_live, \
             patch("driver_bot.notify_client") as mock_notify, \
             patch("driver_bot.reverse_geocode", return_value="Carretera al Norte, Mazatlán"):

            # 1. Driver shares GPS
            await recibir_ubicacion_tiempo_real(mock_update, mock_context)

            # Verify driver location in DB was updated to real GPS
            updated_driver = self.repo.get_driver(self.driver.id)
            self.assertAlmostEqual(updated_driver.current_lat, driver_real_lat, places=4)
            self.assertAlmostEqual(updated_driver.current_lng, driver_real_lng, places=4)

            # Verify send_client_live_location was called with DRIVER's coordinates, NOT customer's coordinates
            mock_send_live.assert_called_once_with(
                "test_client_chat_456", driver_real_lat, driver_real_lng, live_period=7200, channel="telegram", order_id=order.id
            )

            # Verify order saved live_location_message_id
            updated_order = self.repo.get_order_by_id(self.tenant_id, order.id)
            self.assertEqual(updated_order.live_location_message_id, 998877)

            # 2. Driver moves (Telegram sends update.edited_message)
            new_lat = 23.2895
            new_lng = -106.3918

            mock_update_live = MagicMock()
            mock_update_live.effective_user.id = "test_driver_live_tg_123"
            mock_update_live.message = None  # None on live edits!
            mock_update_live.edited_message = MagicMock()
            mock_update_live.edited_message.location.latitude = new_lat
            mock_update_live.edited_message.location.longitude = new_lng

            await recibir_ubicacion_tiempo_real(mock_update_live, mock_context)

            # Verify edit_client_live_location was called
            mock_edit_live.assert_called_once_with(
                "test_client_chat_456", 998877, new_lat, new_lng, channel="telegram"
            )

    async def test_accept_order_sends_driver_gps_or_waits(self):
        from driver_bot import manejar_callback_pedidos
        from unittest.mock import AsyncMock

        # Order with client delivery coordinates
        order = self.repo.create_order(
            tenant_id=self.tenant_id,
            customer_name="Cliente Destino",
            customer_phone="6691112233",
            delivery_address="Av Camaron Sabalo 100, Mazatlan",
            items=[{"product_name": "Cilindro 30kg", "quantity": 1, "unit_price": 670.0}],
            channel="telegram",
            channel_user_id="client_chat_789",
            delivery_lat=23.2500,
            delivery_lng=-106.4600,
        )

        # 1. Driver has NO GPS yet (current_lat = None)
        from src.database.connection import get_db_connection
        with get_db_connection() as conn:
            conn.execute("UPDATE drivers SET current_lat = NULL, current_lng = NULL WHERE id = ?", (self.driver.id,))

        mock_update = MagicMock()
        mock_update.effective_user.id = "test_driver_live_tg_123"
        mock_update.callback_query = MagicMock()
        mock_update.callback_query.data = f"accept_order:{order.id}"
        mock_update.callback_query.from_user.id = "test_driver_live_tg_123"
        mock_update.callback_query.answer = AsyncMock()
        mock_update.callback_query.edit_message_text = AsyncMock()

        mock_context = MagicMock()
        mock_context.bot.send_message = AsyncMock()

        with patch("driver_bot.send_client_live_location") as mock_send_live, \
             patch("driver_bot.notify_client") as mock_notify:

            await manejar_callback_pedidos(mock_update, mock_context)

            # Assert send_client_live_location was NOT called because driver has no GPS!
            # Must NOT send client delivery coordinates as fake driver GPS
            mock_send_live.assert_not_called()

            # Client was notified that order is on the way
            mock_notify.assert_called_once()
            self.assertIn("va en camino", mock_notify.call_args[0][1])

            # Driver received prompt to transmit real GPS
            mock_context.bot.send_message.assert_called_once()

            # Order status is in_route and assigned to this driver
            updated_order = self.repo.get_order_by_id(self.tenant_id, order.id)
            self.assertEqual(updated_order.status, "in_route")
            self.assertEqual(updated_order.driver_id, self.driver.id)

    async def test_expired_live_location_is_cleared_and_renewed(self):
        """When editMessageLiveLocation fails because pin expired, clear old ID and renew pin."""
        from unittest.mock import AsyncMock
        from driver_bot import _failed_live_location_orders

        _failed_live_location_orders.clear()

        order = self.repo.create_order(
            tenant_id=self.tenant_id,
            customer_name="Cliente Expirado",
            customer_phone="6691234567",
            delivery_address="Av Mazatlan 123",
            items=[{"product_name": "Cilindro 30kg", "quantity": 1, "unit_price": 670.0}],
            channel="telegram",
            channel_user_id="client_chat_expired_1",
            delivery_lat=23.2200,
            delivery_lng=-106.4200,
        )
        self.repo.assign_order_to_driver(self.tenant_id, order.id, self.driver.id)
        self.repo.update_order_status(self.tenant_id, order.id, "in_route")
        self.repo.set_order_live_location(self.tenant_id, order.id, "client_chat_expired_1", 111111)

        mock_update = MagicMock()
        mock_update.effective_user.id = "test_driver_live_tg_123"
        mock_update.message = MagicMock()
        mock_update.message.reply_text = AsyncMock()
        mock_update.message.location.latitude = 23.2300
        mock_update.message.location.longitude = -106.4300
        mock_update.edited_message = None

        mock_context = MagicMock()

        # edit_client_live_location fails (returns False due to expired/uneditable pin)
        # send_client_live_location succeeds with a new pin
        with patch("driver_bot.edit_client_live_location", return_value=False) as mock_edit, \
             patch("driver_bot.send_client_live_location", return_value=222222) as mock_send, \
             patch("driver_bot.reverse_geocode", return_value="Mazatlán Centro"):

            await recibir_ubicacion_tiempo_real(mock_update, mock_context)

            mock_edit.assert_called_once()
            # Must renew with a fresh live location pin
            mock_send.assert_called_once_with("client_chat_expired_1", 23.2300, -106.4300, live_period=7200, channel="telegram", order_id=order.id)

            # Order in DB must have new message ID 222222
            updated_order = self.repo.get_order_by_id(self.tenant_id, order.id)
            self.assertEqual(updated_order.live_location_message_id, 222222)

    async def test_stale_order_from_yesterday_cleared_without_spam(self):
        """When an order is older than 6 hours and live location expired, do NOT spam client with a new pin."""
        from unittest.mock import AsyncMock
        from datetime import datetime, timedelta, timezone
        from driver_bot import _failed_live_location_orders
        from src.database.connection import get_db_connection

        _failed_live_location_orders.clear()

        order = self.repo.create_order(
            tenant_id=self.tenant_id,
            customer_name="Cliente Ayer",
            customer_phone="6691234567",
            delivery_address="Av Mazatlan 123",
            items=[{"product_name": "Cilindro 30kg", "quantity": 1, "unit_price": 670.0}],
            channel="telegram",
            channel_user_id="client_chat_stale_2",
            delivery_lat=23.2200,
            delivery_lng=-106.4200,
        )
        self.repo.assign_order_to_driver(self.tenant_id, order.id, self.driver.id)
        self.repo.update_order_status(self.tenant_id, order.id, "in_route")
        self.repo.set_order_live_location(self.tenant_id, order.id, "client_chat_stale_2", 333333)

        # Force order updated_at to 12 hours ago
        stale_time = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
        with get_db_connection() as conn:
            conn.execute("UPDATE orders SET updated_at = ?, created_at = ? WHERE id = ?", (stale_time, stale_time, order.id))

        mock_update = MagicMock()
        mock_update.effective_user.id = "test_driver_live_tg_123"
        mock_update.message = MagicMock()
        mock_update.message.reply_text = AsyncMock()
        mock_update.message.location.latitude = 23.2300
        mock_update.message.location.longitude = -106.4300
        mock_update.edited_message = None

        mock_context = MagicMock()

        with patch("driver_bot.edit_client_live_location", return_value=False) as mock_edit, \
             patch("driver_bot.send_client_live_location") as mock_send, \
             patch("driver_bot.reverse_geocode", return_value="Mazatlán Centro"):

            await recibir_ubicacion_tiempo_real(mock_update, mock_context)

            mock_edit.assert_called_once()
            # Must NOT call send_client_live_location for stale orders
            mock_send.assert_not_called()

            # Order in DB must have cleared live_location_message_id (None)
            updated_order = self.repo.get_order_by_id(self.tenant_id, order.id)
            self.assertIsNone(updated_order.live_location_message_id)

    async def test_multiple_orders_same_client_sends_only_one_map_pin(self):
        """When driver has multiple active orders for the same client, send only ONE map pin."""
        from unittest.mock import AsyncMock

        # Create two orders for the same client chat
        order1 = self.repo.create_order(
            tenant_id=self.tenant_id,
            customer_name="Cliente Dedup",
            customer_phone="6691122334",
            delivery_address="Calle 1",
            items=[{"product_name": "Cilindro 30kg", "quantity": 1, "unit_price": 670.0}],
            channel="telegram",
            channel_user_id="client_chat_dedup_1",
            delivery_lat=23.2100,
            delivery_lng=-106.4100,
        )
        self.repo.assign_order_to_driver(self.tenant_id, order1.id, self.driver.id)
        self.repo.update_order_status(self.tenant_id, order1.id, "in_route")

        order2 = self.repo.create_order(
            tenant_id=self.tenant_id,
            customer_name="Cliente Dedup",
            customer_phone="6691122334",
            delivery_address="Calle 2",
            items=[{"product_name": "Cilindro 20kg", "quantity": 1, "unit_price": 450.0}],
            channel="telegram",
            channel_user_id="client_chat_dedup_1",
            delivery_lat=23.2100,
            delivery_lng=-106.4100,
        )
        self.repo.assign_order_to_driver(self.tenant_id, order2.id, self.driver.id)
        self.repo.update_order_status(self.tenant_id, order2.id, "in_route")

        mock_update = MagicMock()
        mock_update.effective_user.id = "test_driver_live_tg_123"
        mock_update.message = MagicMock()
        mock_update.message.reply_text = AsyncMock()
        mock_update.message.location.latitude = 23.2200
        mock_update.message.location.longitude = -106.4200
        mock_update.edited_message = None

        mock_context = MagicMock()

        with patch("driver_bot.send_client_live_location", return_value=888999) as mock_send, \
             patch("driver_bot.notify_client") as mock_notify, \
             patch("driver_bot.reverse_geocode", return_value="Mazatlán"):

            await recibir_ubicacion_tiempo_real(mock_update, mock_context)

            # Assert send_client_live_location was called exactly ONCE for client_chat_dedup_1!
            mock_send.assert_called_once_with(
                "client_chat_dedup_1", 23.2200, -106.4200, live_period=7200, channel="telegram", order_id=order2.id
            )

            # Both orders must be linked to the single pin
            o1_updated = self.repo.get_order_by_id(self.tenant_id, order1.id)
            o2_updated = self.repo.get_order_by_id(self.tenant_id, order2.id)
            self.assertEqual(o1_updated.live_location_message_id, 888999)
            self.assertEqual(o2_updated.live_location_message_id, 888999)

            # Notification includes the Cancel button
            mock_notify.assert_called_once()
            call_args = mock_notify.call_args[0]
            self.assertIn("ha comenzado a compartir su ubicación en tiempo real", call_args[1])
            reply_markup = mock_notify.call_args[0][2]
            self.assertIsNotNone(reply_markup)
            self.assertIn("cancel_order_client", str(reply_markup))


if __name__ == "__main__":
    unittest.main()
