"""Unit tests for Dynamic Settings synchronization with NestJS central API."""

import os
import unittest
from unittest.mock import MagicMock, patch

from src.channels.instagram.adapter import InstagramAdapter
from src.channels.messenger.adapter import MessengerAdapter
from src.channels.whatsapp.adapter import WhatsAppAdapter
from src.config.settings import Settings, get_settings
from src.services.dynamic_settings import (
    fetch_remote_settings,
    get_dynamic_setting,
    invalidate_dynamic_settings_cache,
)


class TestDynamicSettings(unittest.TestCase):
    """Test suite for live dynamic settings loading, caching, and adapter integration."""

    def setUp(self):
        invalidate_dynamic_settings_cache()

    def tearDown(self):
        invalidate_dynamic_settings_cache()

    @patch("src.services.api_client.api_get")
    def test_fetch_remote_settings_parses_and_caches(self, mock_api_get):
        mock_api_get.return_value = [
            {"key": "WHATSAPP_TOKEN", "value": "test_wa_token_123"},
            {"key": "MESSENGER_PAGE_ACCESS_TOKEN", "value": "test_fb_token_456"},
            {"key": "GOOGLE_MAPS_API_KEY", "value": "test_maps_key_789"},
        ]

        # First fetch should call api_get
        settings = fetch_remote_settings(force_refresh=True)
        self.assertEqual(settings.get("WHATSAPP_TOKEN"), "test_wa_token_123")
        self.assertEqual(settings.get("MESSENGER_PAGE_ACCESS_TOKEN"), "test_fb_token_456")
        self.assertEqual(settings.get("GOOGLE_MAPS_API_KEY"), "test_maps_key_789")
        self.assertEqual(mock_api_get.call_count, 1)

        # Second fetch within TTL should use cache without calling api_get again
        cached_settings = fetch_remote_settings(force_refresh=False)
        self.assertEqual(cached_settings.get("WHATSAPP_TOKEN"), "test_wa_token_123")
        self.assertEqual(mock_api_get.call_count, 1)

    @patch("src.services.api_client.api_get")
    def test_get_dynamic_setting_prioritizes_remote_over_env(self, mock_api_get):
        mock_api_get.return_value = [
            {"key": "WHATSAPP_TOKEN", "value": "token_from_remote_api"},
        ]

        with patch.dict(os.environ, {"WHATSAPP_TOKEN": "token_from_local_env"}):
            val = get_dynamic_setting("WHATSAPP_TOKEN", force_refresh=True)
            self.assertEqual(val, "token_from_remote_api")

    @patch("src.services.api_client.api_get")
    def test_get_dynamic_setting_fallback_to_env_on_api_error(self, mock_api_get):
        mock_api_get.side_effect = RuntimeError("API Down")

        with patch.dict(os.environ, {"WHATSAPP_TOKEN": "token_from_local_env"}):
            val = get_dynamic_setting("WHATSAPP_TOKEN", force_refresh=True)
            self.assertEqual(val, "token_from_local_env")

    @patch("src.services.api_client.api_get")
    def test_settings_class_evaluates_dynamic_properties(self, mock_api_get):
        mock_api_get.return_value = [
            {"key": "WHATSAPP_TOKEN", "value": "live_wa_token_999"},
            {"key": "MESSENGER_PAGE_ACCESS_TOKEN", "value": "live_msg_token_888"},
            {"key": "GOOGLE_MAPS_API_KEY", "value": "live_maps_777"},
            {"key": "TELEGRAM_BOT_TOKEN", "value": "live_tg_bot_666"},
            {"key": "TELEGRAM_DRIVER_BOT_TOKEN", "value": "live_tg_driver_555"},
        ]

        invalidate_dynamic_settings_cache()
        s = Settings()
        self.assertEqual(s.whatsapp_token, "live_wa_token_999")
        self.assertEqual(s.messenger_page_access_token, "live_msg_token_888")
        self.assertEqual(s.maps_api_key, "live_maps_777")
        self.assertEqual(s.telegram_bot_token, "live_tg_bot_666")
        self.assertEqual(s.telegram_driver_bot_token, "live_tg_driver_555")

    @patch("src.services.api_client.api_get")
    def test_adapters_access_token_resolves_dynamic_tokens(self, mock_api_get):
        mock_api_get.return_value = [
            {"key": "WHATSAPP_TOKEN", "value": "wa_token_adapter_test"},
            {"key": "MESSENGER_PAGE_ACCESS_TOKEN", "value": "msg_token_adapter_test"},
            {"key": "INSTAGRAM_ACCESS_TOKEN", "value": "ig_token_adapter_test"},
        ]

        invalidate_dynamic_settings_cache()
        wa_adapter = WhatsAppAdapter()
        msg_adapter = MessengerAdapter()
        ig_adapter = InstagramAdapter()

        self.assertEqual(wa_adapter.access_token, "wa_token_adapter_test")
        self.assertEqual(msg_adapter.access_token, "msg_token_adapter_test")
        self.assertEqual(ig_adapter.access_token, "ig_token_adapter_test")

    async def _async_test_post_meta_retry(self, mock_api_get):
        from unittest.mock import AsyncMock
        import httpx

        mock_api_get.return_value = [
            {"key": "WHATSAPP_TOKEN", "value": "refreshed_wa_token_after_401"},
        ]

        wa = WhatsAppAdapter()
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        resp_401 = MagicMock(status_code=401)
        resp_200 = MagicMock(status_code=200)
        mock_client.post.side_effect = [resp_401, resp_200]

        final_resp = await wa._post_meta(mock_client, "https://graph.facebook.com/v21.0/test", {"test": "data"})
        self.assertEqual(final_resp.status_code, 200)
        self.assertEqual(mock_client.post.call_count, 2)
        # Verify that second call used the refreshed token in Authorization header
        second_call_headers = mock_client.post.call_args_list[1].kwargs.get("headers", {})
        self.assertIn("refreshed_wa_token_after_401", second_call_headers.get("Authorization", ""))

    @patch("src.services.api_client.api_get")
    def test_post_meta_401_triggers_refresh_and_retry(self, mock_api_get):
        import asyncio
        asyncio.run(self._async_test_post_meta_retry(mock_api_get))


if __name__ == "__main__":
    unittest.main()

