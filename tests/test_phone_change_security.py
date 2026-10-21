import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.database import init_db
from src.repositories import get_repository
from src.repositories.identity_store import identity_store
from src.services.flow_router import flow_router, clear_session, FlowState, is_plausible_person_name
import telegram_bot_test as bot


def setup_module():
    init_db()


def test_is_plausible_person_name_rejects_phone_and_registration_phrases():
    """Verify that phrases attempting to register or change phone numbers are not accepted as valid names."""
    assert not is_plausible_person_name("quiero dar de alta otro numero")
    assert not is_plausible_person_name("dar de alta otro")
    assert not is_plausible_person_name("cambiar mi numero")
    assert not is_plausible_person_name("otro numero")
    assert not is_plausible_person_name("otra linea")
    assert not is_plausible_person_name("cambiar celular")
    assert not is_plausible_person_name("cancelar")
    # Valid names should pass
    assert is_plausible_person_name("Juan Pérez")
    assert is_plausible_person_name("Oscar Vizcarra")
    assert is_plausible_person_name("Francisco Rojo")


def test_onboarding_name_rejects_phone_change_and_invalid_name():
    """During onboarding (awaiting_registration_name), attempts to change phone must be blocked."""
    async def _run():
        repo = get_repository()
        test_uid = 888123456
        test_phone = "6691232448"

        # Cleanup
        repo.delete_customer("petroil", phone=test_phone, channel="telegram", channel_user_id=str(test_uid))
        identity_store.unbind_channel_user("telegram", str(test_uid), phone=test_phone)
        clear_session(f"telegram:petroil:{test_uid}")

        # Set up awaiting_registration_name state
        context_mock = MagicMock()
        context_mock.user_data = {
            "phone": test_phone,
            "awaiting_registration_name": True,
        }
        identity_store.bind_channel_user_phone("telegram", str(test_uid), test_phone)

        update_mock = MagicMock()
        update_mock.effective_user.id = test_uid
        update_mock.effective_chat.id = test_uid
        update_mock.message.text = "quiero dar de alta otro numero"
        update_mock.message.reply_text = AsyncMock()

        await bot.responder(update_mock, context_mock)

        # Bot should stop the user and refuse to change phone or accept it as name
        assert update_mock.message.reply_text.called
        reply_call = update_mock.message.reply_text.call_args[0][0]
        assert "no permitida por seguridad" in reply_call.lower()
        assert context_mock.user_data.get("awaiting_registration_name") is True

        # User enters valid name
        update_mock.message.reply_text.reset_mock()
        update_mock.message.text = "Francisco Rojo"
        await bot.responder(update_mock, context_mock)

        cust = bot.get_registered_customer(test_uid)
        assert cust is not None
        assert cust.name == "Francisco Rojo"
        assert cust.phone == test_phone

        # Cleanup
        repo.delete_customer("petroil", phone=test_phone, channel="telegram", channel_user_id=str(test_uid))
        identity_store.unbind_channel_user("telegram", str(test_uid), phone=test_phone)

    asyncio.run(_run())


def test_registered_user_cannot_change_phone_via_chat():
    """An already registered user cannot change phone or register another number."""
    async def _run():
        repo = get_repository()
        test_uid = 888777666
        registered_phone = "6691232448"

        # Register user
        identity_store.unbind_channel_user("telegram", str(test_uid), phone=registered_phone)
        clear_session(f"telegram:petroil:{test_uid}")

        identity_store.bind_channel_user_phone("telegram", str(test_uid), registered_phone, force=True)
        repo.save_or_update_customer(
            tenant_id="petroil",
            channel="telegram",
            channel_user_id=str(test_uid),
            name="Francisco Rojo",
            phone=registered_phone,
        )

        context_mock = MagicMock()
        context_mock.user_data = {"phone": registered_phone}
        update_mock = MagicMock()
        update_mock.effective_user.id = test_uid
        update_mock.effective_chat.id = test_uid
        update_mock.message.reply_text = AsyncMock()

        # Attempt 1: "quiero dar de alta otro numero"
        update_mock.message.text = "quiero dar de alta otro numero"
        await bot.responder(update_mock, context_mock)

        reply_text = update_mock.message.reply_text.call_args[0][0]
        assert "no permitida por seguridad" in reply_text.lower()
        assert registered_phone in reply_text

        # Verify identity store phone did NOT change
        bound_p = identity_store.get_phone_for_channel_user("telegram", str(test_uid))
        assert bound_p == registered_phone

        # Attempt 2: "cambiar mi numero de celular"
        update_mock.message.reply_text.reset_mock()
        update_mock.message.text = "cambiar mi numero de celular"
        await bot.responder(update_mock, context_mock)

        reply_text = update_mock.message.reply_text.call_args[0][0]
        assert "no permitida por seguridad" in reply_text.lower()
        bound_p = identity_store.get_phone_for_channel_user("telegram", str(test_uid))
        assert bound_p == registered_phone

        # Attempt 3: Sending a raw 10-digit phone number different from registered phone
        update_mock.message.reply_text.reset_mock()
        update_mock.message.text = "6699123509"
        await bot.responder(update_mock, context_mock)

        reply_text = update_mock.message.reply_text.call_args[0][0]
        assert "no permitida por seguridad" in reply_text.lower()
        bound_p = identity_store.get_phone_for_channel_user("telegram", str(test_uid))
        assert bound_p == registered_phone

        # Cleanup
        repo.delete_customer("petroil", phone=registered_phone, channel="telegram", channel_user_id=str(test_uid))
        identity_store.unbind_channel_user("telegram", str(test_uid), phone=registered_phone)

    asyncio.run(_run())


def test_flow_router_blocks_phone_correction_for_registered_user():
    """flow_router._handle_correction_intent stops phone change when session/identity has registered phone."""
    async def _run():
        session_id = "telegram:petroil:user_sec_999"
        clear_session(session_id)
        registered_phone = "6691122334"

        identity_store.bind_channel_user_phone("telegram", "user_sec_999", registered_phone, force=True)

        # Initiate order
        res1 = await flow_router.process_event(
            session_id=session_id,
            text="Quiero un cilindro de 30 kg",
            channel="telegram",
            channel_user_id="user_sec_999",
            tenant_id="petroil",
        )

        # Try to change phone in flow router
        res2 = await flow_router.process_event(
            session_id=session_id,
            text="cambiar de numero",
            channel="telegram",
            channel_user_id="user_sec_999",
            tenant_id="petroil",
        )

        assert "no permitida por seguridad" in res2.text.lower()
        assert registered_phone in res2.text
        # State should not become WAITING_FOR_PHONE
        assert res2.state != FlowState.WAITING_FOR_PHONE

        session = flow_router.get_session(session_id)
        assert session.draft_order.customer_phone == registered_phone

        # Cleanup
        identity_store.unbind_channel_user("telegram", "user_sec_999", phone=registered_phone)
        clear_session(session_id)

    asyncio.run(_run())


if __name__ == "__main__":
    test_is_plausible_person_name_rejects_phone_and_registration_phrases()
    test_onboarding_name_rejects_phone_change_and_invalid_name()
    test_registered_user_cannot_change_phone_via_chat()
    test_flow_router_blocks_phone_correction_for_registered_user()
    print("✅ All security tests passed successfully!")
