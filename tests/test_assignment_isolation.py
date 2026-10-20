"""Test end-to-end driver assignment notification isolation across test bot, production petroil, and gascytsa."""

import unittest
from unittest.mock import patch, MagicMock
from src.repositories.identity_store import identity_store
from src.services.notifications import resolve_telegram_client_token, notify_client
from src.services.order_events import notify_order_assigned

TEST_BOT_TOKEN = "8913254382:AAE3FCTlrU0EYiFGdNMsRBxCifTIfh_nba0"
PROD_PETROIL_TOKEN = "8714339361:AAGaICfqNVkv3Vk5hYRqcmqUt_0kjD4XH2U"
GASCYTSA_TOKEN = "8376224866:AAGyLKjKreB4gDUkYI1IGnCBVah3kfM4A-o"
HERMOSILLO_TOKEN = "8633811568:AAH2qf9biMHCdEM_5_rg1eN8P-6HzZduEJ8"

class TestAssignmentIsolation(unittest.TestCase):
    def setUp(self):
        identity_store._load()

    def test_luke_skywalker_order_uuid_assignment_uses_test_token(self):
        """When an order is created in Luke GasSkywalker test bot, driver assignment via UUID must use test bot token."""
        order_uuid = "a1b2c3d4-e5f6-7a8b-9c0d-112233445566"
        order_num = "ORD-PETR-9991"
        order_int_id = 9991
        user_id = "777888999"
        phone = "6699112233"

        # Register channel info as done upon order creation
        for k in (order_int_id, str(order_int_id), order_uuid, order_num):
            identity_store.save_order_channel_info(
                k,
                channel="telegram",
                channel_user_id=user_id,
                phone=phone,
                tenant_id="petroil",
                bot_token=TEST_BOT_TOKEN,
            )

        # 1. Resolve by UUID alone
        tok_uuid = resolve_telegram_client_token(order_id=order_uuid)
        self.assertEqual(tok_uuid, TEST_BOT_TOKEN, "UUID resolution must yield Luke Skywalker test bot token")

        # 2. Resolve by orderNumber alone
        tok_num = resolve_telegram_client_token(order_id=order_num)
        self.assertEqual(tok_num, TEST_BOT_TOKEN, "OrderNumber resolution must yield Luke Skywalker test bot token")

        # 3. Resolve by integer ID
        tok_int = resolve_telegram_client_token(order_id=order_int_id)
        self.assertEqual(tok_int, TEST_BOT_TOKEN, "Integer ID resolution must yield Luke Skywalker test bot token")

        # 4. Resolve by UUID + channel_user_id
        tok_full = resolve_telegram_client_token(order_id=order_uuid, tenant_id="petroil", channel_user_id=user_id)
        self.assertEqual(tok_full, TEST_BOT_TOKEN, "Full context resolution must yield Luke Skywalker test bot token")

    def test_production_petroil_order_assignment_uses_prod_token(self):
        """When an order is created in Production Petroil bot, driver assignment must use production token."""
        order_uuid = "b2c3d4e5-f6a7-8b9c-0d1e-223344556677"
        order_num = "ORD-PETR-9992"
        order_int_id = 9992
        user_id = "555444333"
        phone = "6699445566"

        for k in (order_int_id, str(order_int_id), order_uuid, order_num):
            identity_store.save_order_channel_info(
                k,
                channel="telegram",
                channel_user_id=user_id,
                phone=phone,
                tenant_id="petroil",
                bot_token=PROD_PETROIL_TOKEN,
            )

        tok = resolve_telegram_client_token(order_id=order_uuid)
        self.assertEqual(tok, PROD_PETROIL_TOKEN, "Production Petroil order must yield production token")

    def test_gascytsa_order_assignment_uses_gascytsa_token(self):
        """When an order is created in Gascytsa bot, driver assignment must use gascytsa token."""
        order_uuid = "c3d4e5f6-a7b8-9c0d-1e2f-334455667788"
        order_num = "ORD-CYTS-9993"
        order_int_id = 9993
        user_id = "444333222"
        phone = "6677112233"

        for k in (order_int_id, str(order_int_id), order_uuid, order_num):
            identity_store.save_order_channel_info(
                k,
                channel="telegram",
                channel_user_id=user_id,
                phone=phone,
                tenant_id="gascytsa",
                bot_token=GASCYTSA_TOKEN,
            )

        tok = resolve_telegram_client_token(order_id=order_uuid)
        self.assertEqual(tok, GASCYTSA_TOKEN, "Gascytsa order must yield Gascytsa token")

    @patch("src.services.notifications._send_telegram_api_call")
    def test_notify_client_dispatches_to_correct_bot_token(self, mock_tg_call):
        """notify_client must pass the exact bot token resolved for the order to Telegram API."""
        mock_tg_call.return_value = {"ok": True, "result": {"message_id": 12345}}

        order_uuid = "d4e5f6a7-b8c9-0d1e-2f3a-445566778899"
        user_id = "999111222"

        identity_store.save_order_channel_info(
            order_uuid,
            channel="telegram",
            channel_user_id=user_id,
            phone="6699001122",
            tenant_id="petroil",
            bot_token=TEST_BOT_TOKEN,
        )

        ok = notify_client(
            channel_user_id=user_id,
            message="🛻 ¡Tu pedido ha sido asignado!",
            order_id=order_uuid,
            tenant_id="petroil",
            channel="telegram",
        )
        self.assertTrue(ok)
        mock_tg_call.assert_called()
        call_token = mock_tg_call.call_args[0][0]
        self.assertEqual(call_token, TEST_BOT_TOKEN, "Telegram API must be called with Luke Skywalker test bot token")

    @patch("src.repositories.get_repository")
    def test_create_order_does_not_raise_unbound_local_error_os(self, mock_get_repo):
        """create_order must execute without UnboundLocalError when bot_token is present in configurable."""
        from src.tools.create_order import create_order
        mock_repo = MagicMock()
        mock_order = MagicMock()
        mock_order.id = "test-order-123"
        mock_order.total_amount = 1057.50
        mock_order.currency = "MXN"
        mock_order.payment_method = "Efectivo"
        mock_order.delivery_address = "Calle Cedro 5205, Las Brisas, Mazatlán, Sinaloa"
        mock_order.delivery_schedule = "Lo antes posible"
        mock_order.items = [{"product_name": "Cilindro de Gas 45 kg", "quantity": 1}]
        mock_order.status = "pending"
        mock_repo.create_order.return_value = mock_order
        mock_repo.get_order_by_id.return_value = mock_order
        mock_repo.get_customer_by_phone.return_value = None
        mock_get_repo.return_value = mock_repo

        config = {
            "configurable": {
                "bot_token": TEST_BOT_TOKEN,
                "channel": "telegram",
                "channel_user_id": "12345",
                "tenant_id": "petroil",
            }
        }
        res = create_order.invoke(
            {
                "customer_name": "Oscar Vi",
                "customer_phone": "6699123501",
                "delivery_address": "Calle Cedro 5205, Las Brisas, Mazatlán, Sinaloa",
                "items": [{"product_name": "Cilindro de Gas 45 kg", "quantity": 1}],
                "delivery_schedule": "Lo antes posible",
                "payment_method": "Efectivo",
            },
            config=config,
        )
        self.assertIn("✅", res)

    @patch("src.repositories.get_repository")
    def test_test_order_with_notes_never_resolves_to_production_token(self, mock_get_repo):
        """An order with [TEST_BOT] notes must NEVER resolve to the production token."""
        import os
        mock_repo = MagicMock()
        mock_order = MagicMock()
        mock_order.id = "ORD-TEST-888"
        mock_order.orderNumber = "ORD-TEST-888"
        mock_order.notes = "[TEST_BOT] Casa azul"
        mock_order.channel = "telegram"
        mock_order.channel_user_id = "2109588241"
        mock_order.tenant_id = "petroil"
        mock_repo.get_order_by_id.return_value = mock_order
        mock_get_repo.return_value = mock_repo

        with patch.dict(os.environ, {"TELEGRAM_TEST_BOT_TOKEN": TEST_BOT_TOKEN, "TELEGRAM_BOT_TOKEN": PROD_PETROIL_TOKEN}):
            tok = resolve_telegram_client_token(order_id="ORD-TEST-888")
            self.assertEqual(tok, TEST_BOT_TOKEN)
            self.assertNotEqual(tok, PROD_PETROIL_TOKEN)

    def test_runner_admissibility_strict_isolation(self):
        """Production runner must reject test orders; test runner must reject production orders."""
        import os
        from src.services.order_events import _is_order_admissible_for_runner
        test_order = MagicMock()
        test_order.notes = "[TEST_BOT] Urgente"
        test_order.channel = "telegram"

        prod_order = MagicMock()
        prod_order.notes = "Casa blanca con portón"
        prod_order.channel = "telegram"

        # 1. Proceso de producción (no tiene IS_TEST_BOT_PROCESS)
        with patch.dict(os.environ, {"IS_TEST_BOT_PROCESS": "false"}):
            self.assertFalse(_is_order_admissible_for_runner(test_order, "999"))
            self.assertTrue(_is_order_admissible_for_runner(prod_order, "1000"))

        # 2. Proceso de pruebas (tiene IS_TEST_BOT_PROCESS = true)
        with patch.dict(os.environ, {"IS_TEST_BOT_PROCESS": "true"}):
            self.assertTrue(_is_order_admissible_for_runner(test_order, "999"))
            self.assertFalse(_is_order_admissible_for_runner(prod_order, "1000"))

    def test_hermosillo_order_assignment_uses_hermosillo_token(self):
        """When an order is created in Hermosillo bot, driver assignment must use Hermosillo token."""
        order_uuid = "e5f6a7b8-9c0d-1e2f-3a4b-556677889900"
        order_num = "ORD-HERM-1001"
        order_int_id = 1001
        user_id = "662999888"
        phone = "6629998888"

        for k in (order_int_id, str(order_int_id), order_uuid, order_num):
            identity_store.save_order_channel_info(
                k,
                channel="telegram",
                channel_user_id=user_id,
                phone=phone,
                tenant_id="blue_propane",
                bot_token=HERMOSILLO_TOKEN,
            )

        tok_uuid = resolve_telegram_client_token(order_id=order_uuid)
        self.assertEqual(tok_uuid, HERMOSILLO_TOKEN)

        tok_ctx = resolve_telegram_client_token(tenant_id="blue_propane")
        self.assertEqual(tok_ctx, HERMOSILLO_TOKEN)

        tok_herm = resolve_telegram_client_token(tenant_id="hermosillo")
        self.assertEqual(tok_herm, HERMOSILLO_TOKEN)

if __name__ == "__main__":
    unittest.main()


