"""Unit tests for 2FA OTP Account Linking across WhatsApp, Messenger, and Instagram.

Verifies:
1. Creation of linking requests and code generation.
2. Verification of code -> binds user in IdentityStore and Repository.
3. WhatsApp owner clicks "No soy esta persona" (otp_reject) -> request invalidated, Messenger/Instagram blocked.
4. User writes "cambiar número" -> cancels request and resets.
5. Inbound WhatsApp button and text handling for OTP.
6. Messenger/Instagram onboarding flows (asking for phone, waiting for code, verifying).
"""

import unittest
from unittest.mock import AsyncMock, patch
from src.repositories.identity_store import identity_store
from src.services.otp_service import OTPService, otp_service


class TestOTPandSocialLinking(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Clean up any test mappings
        identity_store.unbind_channel_user("messenger", "msgr_test_user_123")
        identity_store.unbind_channel_user("instagram", "ig_test_user_456")
        otp_service._requests.clear()
        otp_service._save()

    def tearDown(self):
        identity_store.unbind_channel_user("messenger", "msgr_test_user_123")
        identity_store.unbind_channel_user("instagram", "ig_test_user_456")
        otp_service._requests.clear()
        otp_service._save()

    def test_create_linking_request(self):
        req = otp_service.create_linking_request(
            channel="messenger",
            channel_user_id="msgr_test_user_123",
            phone="6691234567",
            profile_name="Oscar Test",
        )
        self.assertIsNotNone(req)
        self.assertEqual(req["channel"], "messenger")
        self.assertEqual(req["channel_user_id"], "msgr_test_user_123")
        self.assertEqual(req["phone"], "6691234567")
        self.assertEqual(len(req["code"]), 6)
        self.assertEqual(req["status"], "pending")

    def test_verify_correct_code_binds_identity(self):
        req = otp_service.create_linking_request(
            channel="messenger",
            channel_user_id="msgr_test_user_123",
            phone="6691234567",
            profile_name="Oscar Test",
        )
        code = req["code"]

        ok, reason, req_data = otp_service.verify_code("messenger", "msgr_test_user_123", code)
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

        # IdentityStore must now have this binding
        bound_phone = identity_store.get_phone_for_channel_user("messenger", "msgr_test_user_123")
        self.assertEqual(bound_phone, "6691234567")

    def test_reject_by_whatsapp_user_blocks_verification(self):
        req = otp_service.create_linking_request(
            channel="messenger",
            channel_user_id="msgr_test_user_123",
            phone="6691234567",
            profile_name="Imposter Name",
        )
        code = req["code"]

        # Real WhatsApp user clicks "No soy esta persona"
        rejected = otp_service.reject_linking_request(phone="6691234567", req_id=req["id"])
        self.assertIsNotNone(rejected)
        self.assertEqual(rejected["status"], "rejected")

        # Imposter in Messenger attempts to input the code
        ok, reason, req_data = otp_service.verify_code("messenger", "msgr_test_user_123", code)
        self.assertFalse(ok)
        self.assertEqual(reason, "rejected")

        # IdentityStore must NOT be bound
        bound_phone = identity_store.get_phone_for_channel_user("messenger", "msgr_test_user_123")
        self.assertIsNone(bound_phone)

    def test_invalid_code_decrements_attempts(self):
        req = otp_service.create_linking_request(
            channel="instagram",
            channel_user_id="ig_test_user_456",
            phone="6699887766",
            profile_name="IG Customer",
        )

        ok, reason, _ = otp_service.verify_code("instagram", "ig_test_user_456", "000000")
        self.assertFalse(ok)
        self.assertEqual(reason, "invalid_code")

        ok, reason, _ = otp_service.verify_code("instagram", "ig_test_user_456", "111111")
        self.assertFalse(ok)
        self.assertEqual(reason, "invalid_code")

        ok, reason, _ = otp_service.verify_code("instagram", "ig_test_user_456", "222222")
        self.assertFalse(ok)
        self.assertEqual(reason, "max_attempts")

    def test_confirm_by_whatsapp_direct(self):
        req = otp_service.create_linking_request(
            channel="messenger",
            channel_user_id="msgr_test_user_123",
            phone="6691234567",
            profile_name="Direct WA Confirm",
        )

        ok, reason, data = otp_service.confirm_by_whatsapp("6691234567", req_id=req["id"])
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")
        self.assertEqual(identity_store.get_phone_for_channel_user("messenger", "msgr_test_user_123"), "6691234567")

    def test_cancel_request(self):
        otp_service.create_linking_request(
            channel="messenger",
            channel_user_id="msgr_test_user_123",
            phone="6691234567",
            profile_name="Oscar Test",
        )
        cancelled = otp_service.cancel_request("messenger", "msgr_test_user_123")
        self.assertTrue(cancelled)

        pending = otp_service.get_pending_request("messenger", "msgr_test_user_123")
        self.assertIsNone(pending)

    @patch("src.channels.whatsapp.adapter.WhatsAppAdapter.send_text_message", new_callable=AsyncMock)
    async def test_whatsapp_router_handles_otp_reject_button(self, mock_send_text):
        from src.channels.whatsapp.router import process_whatsapp_event

        req = otp_service.create_linking_request(
            channel="messenger",
            channel_user_id="msgr_test_user_123",
            phone="6691234567",
            profile_name="Equivocado Test",
        )

        event = {
            "msg_id": "wa_msg_101",
            "wa_id": "5216691234567",
            "tenant_id": "petroil",
            "text": "❌ No soy esta persona",
            "type": "interactive",
            "interactive_id": f"otp_reject:{req['id']}",
        }

        await process_whatsapp_event(event)

        # OTP request must be marked rejected
        target = otp_service.get_request_by_id(req["id"])
        self.assertEqual(target["status"], "rejected")

        # Bot must have replied confirming cancellation
        mock_send_text.assert_called()
        call_text = mock_send_text.call_args[0][1]
        self.assertIn("Solicitud Cancelada", call_text)
        self.assertIn("Messenger", call_text)

    @patch("src.channels.whatsapp.adapter.WhatsAppAdapter.send_text_message", new_callable=AsyncMock)
    async def test_whatsapp_router_handles_otp_reject_text(self, mock_send_text):
        from src.channels.whatsapp.router import process_whatsapp_event

        req = otp_service.create_linking_request(
            channel="instagram",
            channel_user_id="ig_test_user_456",
            phone="6691234567",
            profile_name="Random IG User",
        )

        event = {
            "msg_id": "wa_msg_102",
            "wa_id": "5216691234567",
            "tenant_id": "petroil",
            "text": "no soy yo se equivocaron",
            "type": "text",
        }

        await process_whatsapp_event(event)

        # OTP request must be marked rejected
        target = otp_service.get_request_by_id(req["id"])
        self.assertEqual(target["status"], "rejected")

        mock_send_text.assert_called()
        call_text = mock_send_text.call_args[0][1]
        self.assertIn("Solicitud Cancelada", call_text)

    @patch("src.channels.messenger.adapter.MessengerAdapter.send_text_message", new_callable=AsyncMock)
    @patch("src.channels.messenger.adapter.MessengerAdapter.get_user_profile", new_callable=AsyncMock)
    @patch("src.services.otp_service.send_whatsapp_otp_challenge", new_callable=AsyncMock)
    async def test_messenger_onboarding_e2e_flow(self, mock_wa_challenge, mock_profile, mock_send_text):
        from src.channels.messenger.router import _process_single_messenger_event

        mock_profile.return_value = {"first_name": "Oscar", "last_name": "Vizcarra"}
        mock_wa_challenge.return_value = True

        # 1. Unbound user says 'Hola' -> bot asks for 10-digit phone
        event_1 = {
            "msg_id": "msgr_msg_1",
            "psid": "msgr_test_user_123",
            "text": "Hola buenas tardes",
            "type": "text",
        }
        await _process_single_messenger_event(event_1)
        mock_send_text.assert_called()
        self.assertIn("número celular a 10 dígitos", mock_send_text.call_args[0][1])

        # 2. User inputs 10-digit phone -> OTP generated and challenge sent to WhatsApp
        event_2 = {
            "msg_id": "msgr_msg_2",
            "psid": "msgr_test_user_123",
            "text": "6691234567",
            "type": "text",
        }
        await _process_single_messenger_event(event_2)
        mock_wa_challenge.assert_called_once()
        self.assertIn("Código de Verificación Enviado", mock_send_text.call_args[0][1])

        # Retrieve generated code
        pending = otp_service.get_pending_request("messenger", "msgr_test_user_123")
        self.assertIsNotNone(pending)
        code = pending["code"]

        # 3. User inputs 6-digit code in Messenger -> verification succeeds!
        with patch("src.channels.messenger.adapter.MessengerAdapter.send_quick_replies", new_callable=AsyncMock) as mock_quick:
            event_3 = {
                "msg_id": "msgr_msg_3",
                "psid": "msgr_test_user_123",
                "text": code,
                "type": "text",
            }
            await _process_single_messenger_event(event_3)
            mock_quick.assert_called_once()
            self.assertIn("Cuenta vinculada y verificada con éxito", mock_quick.call_args[1]["text"])

        # Check binding exists
        self.assertEqual(identity_store.get_phone_for_channel_user("messenger", "msgr_test_user_123"), "6691234567")


if __name__ == "__main__":
    unittest.main()
