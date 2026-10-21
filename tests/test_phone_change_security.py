import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.abspath("."))

from src.database import init_db
from src.repositories import get_repository
from src.repositories.identity_store import identity_store
from src.services.flow_router import (
    flow_router,
    clear_session,
    FlowState,
    is_plausible_person_name,
    check_phone_change_attempt_deterministic,
    is_phone_change_attempt_semantic,
)
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
        reply_markup = update_mock.message.reply_text.call_args[1].get("reply_markup")
        assert "no permitida por seguridad" in reply_text.lower()
        assert registered_phone in reply_text
        assert reply_markup is not None
        assert reply_markup.inline_keyboard[0][0].callback_data == "menu:main"
        assert "regresar" in reply_markup.inline_keyboard[0][0].text.lower()

        # Verify identity store phone did NOT change
        bound_p = identity_store.get_phone_for_channel_user("telegram", str(test_uid))
        assert bound_p == registered_phone

        # Attempt 2: "cambiar mi numero de celular"
        update_mock.message.reply_text.reset_mock()
        update_mock.message.text = "cambiar mi numero de celular"
        await bot.responder(update_mock, context_mock)

        reply_text = update_mock.message.reply_text.call_args[0][0]
        reply_markup = update_mock.message.reply_text.call_args[1].get("reply_markup")
        assert "no permitida por seguridad" in reply_text.lower()
        assert reply_markup is not None
        assert reply_markup.inline_keyboard[0][0].callback_data == "menu:main"
        bound_p = identity_store.get_phone_for_channel_user("telegram", str(test_uid))
        assert bound_p == registered_phone

        # Attempt 3: Sending a raw 10-digit phone number different from registered phone
        update_mock.message.reply_text.reset_mock()
        update_mock.message.text = "6699123509"
        await bot.responder(update_mock, context_mock)

        reply_text = update_mock.message.reply_text.call_args[0][0]
        reply_markup = update_mock.message.reply_text.call_args[1].get("reply_markup")
        assert "no permitida por seguridad" in reply_text.lower()
        assert reply_markup is not None
        assert reply_markup.inline_keyboard[0][0].callback_data == "menu:main"
        bound_p = identity_store.get_phone_for_channel_user("telegram", str(test_uid))
        assert bound_p == registered_phone

        # Attempt 4: "nuevo celular" (User reported variation)
        update_mock.message.reply_text.reset_mock()
        update_mock.message.text = "nuevo celular"
        await bot.responder(update_mock, context_mock)

        reply_text = update_mock.message.reply_text.call_args[0][0]
        reply_markup = update_mock.message.reply_text.call_args[1].get("reply_markup")
        assert "no permitida por seguridad" in reply_text.lower()
        assert reply_markup is not None
        assert reply_markup.inline_keyboard[0][0].callback_data == "menu:main"
        bound_p = identity_store.get_phone_for_channel_user("telegram", str(test_uid))
        assert bound_p == registered_phone

        # Attempt 5: "nuevo telefono" (User reported variation)
        update_mock.message.reply_text.reset_mock()
        update_mock.message.text = "nuevo telefono"
        await bot.responder(update_mock, context_mock)

        reply_text = update_mock.message.reply_text.call_args[0][0]
        reply_markup = update_mock.message.reply_text.call_args[1].get("reply_markup")
        assert "no permitida por seguridad" in reply_text.lower()
        assert reply_markup is not None
        assert reply_markup.inline_keyboard[0][0].callback_data == "menu:main"
        bound_p = identity_store.get_phone_for_channel_user("telegram", str(test_uid))
        assert bound_p == registered_phone

        # Test callback query: user clicks "⬅️ Regresar al Menú Principal"
        cb_update = MagicMock()
        cb_update.effective_user.id = test_uid
        cb_update.effective_chat.id = test_uid
        cb_update.callback_query.data = "menu:main"
        cb_update.callback_query.message = MagicMock()
        cb_update.callback_query.message.reply_text = AsyncMock()
        cb_update.callback_query.edit_message_text = AsyncMock()
        cb_update.callback_query.answer = AsyncMock()

        await bot.manejar_callback_cliente(cb_update, context_mock)
        assert cb_update.callback_query.edit_message_text.called
        cb_edit_call = cb_update.callback_query.edit_message_text.call_args
        menu_text = cb_edit_call[0][0]
        menu_markup = cb_edit_call[1].get("reply_markup")
        assert "qué deseas hacer hoy" in menu_text.lower() or "hola" in menu_text.lower()
        # Ensure menu has Hacer un Pedido and Mi Cuenta
        menu_callbacks = [btn.callback_data for row in menu_markup.inline_keyboard for btn in row]
        assert "menu:hacer_pedido" in menu_callbacks
        assert "menu:mi_cuenta" in menu_callbacks

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
        assert res2.action_performed == "show_security_return_menu"
        # State should not become WAITING_FOR_PHONE
        assert res2.state != FlowState.WAITING_FOR_PHONE

        # Verify markup generated for flow response
        markup = bot.get_markup_for_flow_response(res2)
        assert markup is not None
        assert markup.inline_keyboard[0][0].callback_data == "menu:main"

        session = flow_router.get_session(session_id)
        assert session.draft_order.customer_phone == registered_phone

        # Cleanup
        identity_store.unbind_channel_user("telegram", "user_sec_999", phone=registered_phone)
        clear_session(session_id)

    asyncio.run(_run())


def test_deterministic_and_semantic_phone_change_detection():
    """Verify that deterministic regex and semantic AI checks catch all variations of phone changes."""
    # 1. Deterministic direct variations (0ms fast path)
    positive_phrases = [
        "nuevo celular",
        "nuevo telefono",
        "nuevo teléfono",
        "mi nuevo cel",
        "nuevo cel",
        "otra linea",
        "otra línea",
        "nueva linea",
        "cambie de chip",
        "cambié de chip",
        "cambio de chip",
        "otro numero",
        "otro número",
        "otro celular",
        "usar otro celular",
        "quiero dar de alta otro",
        "dar de alta otro",
        "modificar mi numero",
        "actualizar celular",
        "actualizar mi contacto",
        "este ya no es mi numero",
        "este ya no es mi número",
        "este no es mi cel",
        "ya cambie de numero",
        "ya cambié de celular",
        "puedo cambiar de celular?",
        "se puede cambiar mi numero?",
        "te paso mi nuevo cel",
        "anota mi nuevo telefono",
    ]
    for phrase in positive_phrases:
        assert check_phone_change_attempt_deterministic(phrase) is True, f"Failed to detect: '{phrase}'"

    # 2. Legitimate user phrases that MUST NOT be detected as phone changes
    negative_phrases = [
        "Quiero un cilindro de 30 kg",
        "Hola buenas tardes",
        "Calle Benito Juarez 405",
        "Pago con tarjeta terminal",
        "A qué hora llega mi pedido",
        "Cuánto cuesta el gas",
        "Tanque estacionario 500 pesos",
    ]
    for phrase in negative_phrases:
        assert check_phone_change_attempt_deterministic(phrase) is False, f"False positive on: '{phrase}'"

    # 3. Semantic validation async tests
    async def _run_semantic():
        # Deterministic phrase returns True immediately
        assert await is_phone_change_attempt_semantic("nuevo celular") is True

        # Non-clue phrase returns False immediately without LLM
        assert await is_phone_change_attempt_semantic("Quiero un cilindro de 30 kg") is False

        # Novel semantic phrasing evaluated via LLM / mock
        from unittest.mock import patch
        with patch("src.services.flow_router.execute_minimal_llm_fallback", return_value='{"is_phone_change": true, "confidence": 0.95}'):
            # Text has phone/account clue "linea", triggers LLM
            res = await is_phone_change_attempt_semantic("tengo una linea distinta ahora")
            assert res is True

        with patch("src.services.flow_router.execute_minimal_llm_fallback", return_value='{"is_phone_change": false, "confidence": 0.9}'):
            # Text asking for company phone
            res = await is_phone_change_attempt_semantic("cuál es su teléfono para dudas")
            assert res is False

    asyncio.run(_run_semantic())


def test_validate_person_name_semantic_comprehensive():
    """Verify that profanities, objects, and nonsensical words are rejected,
    while rare, indigenous, foreign, and unusual names are accepted."""
    from src.services.flow_router import validate_person_name_semantic
    from unittest.mock import patch

    async def _run():
        # 1. Deterministic profanity rejection
        profanities = [
            "el vergas",
            "puto",
            "pendejo",
            "chinga tu madre",
            "alv",
            "mierda",
            "hdp",
            "culero",
        ]
        for bad_word in profanities:
            is_valid, reason = await validate_person_name_semantic(bad_word)
            assert not is_valid, f"Expected '{bad_word}' to be rejected"
            assert reason == "groseria", f"Expected reason 'groseria' for '{bad_word}', got '{reason}'"

        # 2. Obvious single-word non-names / objects / commands
        non_names = ["mesa", "silla", "pizza", "cilindro", "gas", "quiero gas", "tanque"]
        for non_name in non_names:
            is_valid, reason = await validate_person_name_semantic(non_name)
            assert not is_valid, f"Expected '{non_name}' to be rejected"
            assert reason == "no_es_nombre", f"Expected reason 'no_es_nombre' for '{non_name}', got '{reason}'"

        # 3. Digits, phone numbers, special characters
        invalid_chars = ["6691234567", "Juan 123", "Pedro#", "Ana_12", "<script>"]
        for inv in invalid_chars:
            is_valid, reason = await validate_person_name_semantic(inv)
            assert not is_valid, f"Expected '{inv}' to be rejected"

        # 4. Standard and rare names accepted (via phonetic fallback or mocked LLM)
        names_to_test = [
            "Juan Pérez",
            "Oscar Vizcarra",
            "Carlos Mesa",
            "Francisco Rojo",
            "Hermenegildo López",
            "Xóchitl Gálvez",
            "Cuauhtémoc Blanco",
            "Brayan Martínez",
        ]
        with patch(
            "src.services.flow_router.execute_minimal_llm_fallback",
            return_value='{"is_valid": true, "reason": "nombre_valido"}',
        ):
            for name in names_to_test:
                is_valid, reason = await validate_person_name_semantic(name)
                assert is_valid, f"Expected rare/standard name '{name}' to be accepted"
                assert reason == "nombre_valido"

        # 5. LLM rejecting subtle insults or fictional/troll characters
        with patch(
            "src.services.flow_router.execute_minimal_llm_fallback",
            return_value='{"is_valid": false, "reason": "troll"}',
        ):
            is_valid, reason = await validate_person_name_semantic("Batman")
            assert not is_valid
            assert reason == "troll"

    asyncio.run(_run())


def test_onboarding_name_rejects_profanity_and_accepts_rare_names():
    """Test onboarding workflow in telegram_bot_test: profanities are rejected with custom message,
    and rare/indigenous names successfully register the user."""
    from unittest.mock import patch

    async def _run():
        repo = get_repository()
        test_uid = 999111222
        test_phone = "6699887766"

        # Cleanup
        repo.delete_customer("petroil", phone=test_phone, channel="telegram", channel_user_id=str(test_uid))
        identity_store.unbind_channel_user("telegram", str(test_uid))
        identity_store.unmark_customer_deleted(test_phone)
        clear_session(f"telegram:petroil:{test_uid}")

        context_mock = MagicMock()
        context_mock.user_data = {
            "phone": test_phone,
            "awaiting_registration_name": True,
        }
        identity_store.bind_channel_user_phone("telegram", str(test_uid), test_phone, force=True)

        update_mock = MagicMock()
        update_mock.effective_user.id = test_uid
        update_mock.effective_chat.id = test_uid
        update_mock.message.reply_text = AsyncMock()

        # Step 1: User enters profanity
        update_mock.message.text = "el vergas"
        await bot.responder(update_mock, context_mock)
        assert update_mock.message.reply_text.called
        reply_call = update_mock.message.reply_text.call_args[0][0]
        assert "no permitido" in reply_call.lower() or "groserías" in reply_call.lower()
        assert context_mock.user_data.get("awaiting_registration_name") is True

        # Step 2: User enters an object
        update_mock.message.reply_text.reset_mock()
        update_mock.message.text = "mesa"
        await bot.responder(update_mock, context_mock)
        assert update_mock.message.reply_text.called
        reply_call = update_mock.message.reply_text.call_args[0][0]
        assert "no parece ser un nombre propio" in reply_call.lower() or "nombre no válido" in reply_call.lower()
        assert context_mock.user_data.get("awaiting_registration_name") is True

        # Step 3: User enters a rare indigenous name (e.g., Cuauhtémoc Blanco)
        with patch(
            "src.services.flow_router.execute_minimal_llm_fallback",
            return_value='{"is_valid": true, "reason": "nombre_valido"}',
        ):
            update_mock.message.reply_text.reset_mock()
            update_mock.message.text = "Cuauhtémoc Blanco"
            await bot.responder(update_mock, context_mock)

        # Successfully registered
        cust = bot.get_registered_customer(test_uid)
        assert cust is not None
        assert cust.name == "Cuauhtémoc Blanco"
        assert cust.phone == test_phone

        # Cleanup
        repo.delete_customer("petroil", phone=test_phone, channel="telegram", channel_user_id=str(test_uid))
        identity_store.unbind_channel_user("telegram", str(test_uid), phone=test_phone)

    asyncio.run(_run())


if __name__ == "__main__":
    test_is_plausible_person_name_rejects_phone_and_registration_phrases()
    test_onboarding_name_rejects_phone_change_and_invalid_name()
    test_registered_user_cannot_change_phone_via_chat()
    test_flow_router_blocks_phone_correction_for_registered_user()
    test_deterministic_and_semantic_phone_change_detection()
    test_validate_person_name_semantic_comprehensive()
    test_onboarding_name_rejects_profanity_and_accepts_rare_names()
    print("✅ All security and AI name validation tests passed successfully!")
