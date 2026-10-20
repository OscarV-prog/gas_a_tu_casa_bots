"""Unit tests for strict bot notification isolation (Petroil, Gascytsa, Test bot)."""

import unittest
from unittest.mock import MagicMock, patch

from src.repositories.identity_store import identity_store
from src.services.notifications import notify_client, resolve_telegram_client_token


class TestBotNotificationIsolation(unittest.TestCase):
    def setUp(self):
        self.petroil_token = "8714339361:AAGaICfqNVkv3Vk5hYRqcmqUt_0kjD4XH2U"
        self.gascytsa_token = "8376224866:AAGyLKjKreB4gDUkYI1IGnCBVah3kfM4A-o"
        self.test_bot_token = "8913254382:AAE3FCTlrU0EYiFGdNMsRBxCifTIfh_nba0"

    def test_token_resolution_by_tenant(self):
        """Verify resolve_telegram_client_token picks Gascytsa vs Petroil based on tenant_id."""
        with patch.dict("os.environ", {
            "TELEGRAM_BOT_TOKEN": self.petroil_token,
            "TELEGRAM_BOT_GASCYTSA_TOKEN": self.gascytsa_token,
        }):
            token_gas = resolve_telegram_client_token(tenant_id="gascytsa")
            self.assertEqual(token_gas, self.gascytsa_token)

            token_pet = resolve_telegram_client_token(tenant_id="petroil")
            self.assertEqual(token_pet, self.petroil_token)

    def test_token_resolution_by_order_identity(self):
        """Verify resolve_telegram_client_token retrieves the exact bot_token stored for an order."""
        order_gas = "order_test_gas_1"
        order_pet = "order_test_pet_1"
        order_test = "order_test_custom_1"

        identity_store.save_order_channel_info(
            order_gas, "telegram", "111111", phone="6671000001", tenant_id="gascytsa", bot_token=self.gascytsa_token
        )
        identity_store.save_order_channel_info(
            order_pet, "telegram", "222222", phone="6691000002", tenant_id="petroil", bot_token=self.petroil_token
        )
        identity_store.save_order_channel_info(
            order_test, "telegram", "333333", phone="6691000003", tenant_id="petroil", bot_token=self.test_bot_token
        )

        res_gas = resolve_telegram_client_token(order_id=order_gas)
        res_pet = resolve_telegram_client_token(order_id=order_pet)
        res_test = resolve_telegram_client_token(order_id=order_test)

        self.assertEqual(res_gas, self.gascytsa_token)
        self.assertEqual(res_pet, self.petroil_token)
        self.assertEqual(res_test, self.test_bot_token)

    def test_token_resolution_by_user_bot_preference(self):
        """Verify user's last-interacted bot determines notification bot if order info is not yet created."""
        user_gas = "999888111"
        user_test = "999888222"

        identity_store.set_user_bot_preference(user_gas, tenant_id="gascytsa", bot_token=self.gascytsa_token)
        identity_store.set_user_bot_preference(user_test, tenant_id="petroil", bot_token=self.test_bot_token)

        res_gas = resolve_telegram_client_token(channel_user_id=user_gas)
        res_test = resolve_telegram_client_token(channel_user_id=user_test)

        self.assertEqual(res_gas, self.gascytsa_token)
        self.assertEqual(res_test, self.test_bot_token)

    @patch("src.services.notifications._send_telegram_api_call")
    def test_notify_client_uses_isolated_token_for_gascytsa(self, mock_api_call):
        """When notifying an order belonging to Gascytsa, it must call the Telegram API with Gascytsa's token."""
        mock_api_call.return_value = {"ok": True, "result": {"message_id": 12345}}
        order_id = "5551"
        identity_store.save_order_channel_info(
            order_id, "telegram", "12345678", phone="6679998877", tenant_id="gascytsa", bot_token=self.gascytsa_token
        )

        msg = f"🛻 **¡Tu pedido #{order_id} ha sido asignado!**"
        ok = notify_client("12345678", msg, tenant_id="gascytsa", order_id=order_id)
        self.assertTrue(ok)

        # Check token used in _send_telegram_api_call
        self.assertTrue(mock_api_call.called)
        call_token = mock_api_call.call_args[0][0]
        self.assertEqual(call_token, self.gascytsa_token)
        self.assertNotEqual(call_token, self.petroil_token)

    @patch("src.services.notifications._send_telegram_api_call")
    def test_notify_client_uses_isolated_token_for_petroil(self, mock_api_call):
        """When notifying an order belonging to Petroil, it must call the Telegram API with Petroil's token."""
        mock_api_call.return_value = {"ok": True, "result": {"message_id": 12346}}
        order_id = "5552"
        identity_store.save_order_channel_info(
            order_id, "telegram", "12345678", phone="6699998877", tenant_id="petroil", bot_token=self.petroil_token
        )

        msg = f"🛻 **¡Tu pedido #{order_id} ha sido asignado!**"
        ok = notify_client("12345678", msg, tenant_id="petroil", order_id=order_id)
        self.assertTrue(ok)

        call_token = mock_api_call.call_args[0][0]
        self.assertEqual(call_token, self.petroil_token)
        self.assertNotEqual(call_token, self.gascytsa_token)


if __name__ == "__main__":
    unittest.main()
