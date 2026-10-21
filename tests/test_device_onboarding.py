"""Integration test for Account per Device onboarding, main menu, name editing,
seamless ordering without phone prompt, and full account deletion.
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

# Force UTF-8 on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.abspath("."))

from src.database import init_db
from src.models.customer import Customer, CustomerAddress
from src.repositories import get_repository
from src.repositories.identity_store import identity_store
from src.services.flow_router import FlowState, flow_router, clear_session
import telegram_bot_test as bot


async def run_tests():
    print("=" * 60)
    print("🧪 Iniciando pruebas de Onboarding por Dispositivo y Cuenta...")
    print("=" * 60)

    init_db()
    repo = get_repository()
    tenant_id = "petroil"

    import random
    import time
    rnd = random.randint(1000, 9999)
    test_uid = 999000000 + rnd
    test_phone = f"669{int(time.time()) % 1000000:06d}{rnd % 10}"
    test_user_name = "Skywalker Tester"

    # Limpiar estado previo si existía
    repo.delete_customer(tenant_id, phone=test_phone, channel="telegram", channel_user_id=str(test_uid))
    identity_store.unbind_channel_user("telegram", str(test_uid), phone=test_phone)
    clear_session(f"telegram:{tenant_id}:{test_uid}")

    # -------------------------------------------------------------------------
    # TEST 1: Usuario no registrado recibe solicitud de contacto en /start
    # -------------------------------------------------------------------------
    print("\n[TEST 1] /start con usuario no registrado...")
    cust = bot.get_registered_customer(test_uid)
    assert cust is None, "El cliente no debería estar registrado aún"

    update_mock = MagicMock()
    update_mock.effective_user.id = test_uid
    update_mock.effective_user.first_name = "Skywalker"
    update_mock.effective_user.last_name = "Tester"
    update_mock.effective_user.username = "sky_tester"
    update_mock.effective_chat.id = test_uid
    update_mock.message.reply_text = AsyncMock()

    context_mock = MagicMock()
    context_mock.user_data = {}

    await bot.start(update_mock, context_mock)
    update_mock.message.reply_text.assert_called_once()
    args, kwargs = update_mock.message.reply_text.call_args
    sent_text = args[0]
    markup = kwargs.get("reply_markup")
    assert "Compartir mi número" in sent_text or "1 cuenta por dispositivo" in sent_text
    assert markup is not None, "Debe mostrar teclado de registro"
    print("✅ TEST 1 PASÓ: El usuario no registrado recibió la solicitud de vincular su número.")

    # -------------------------------------------------------------------------
    # TEST 2: Usuario no registrado envía texto arbitrario -> teclado bloqueado con persistencia
    # -------------------------------------------------------------------------
    print("\n[TEST 2] Texto arbitrario de usuario no registrado (bloqueo estricto)...")
    update_mock.message.reply_text.reset_mock()
    update_mock.message.text = "Hola quiero pedir gas"

    await bot.responder(update_mock, context_mock)
    args, kwargs = update_mock.message.reply_text.call_args
    sent_text = args[0]
    markup = kwargs.get("reply_markup")
    assert "Vinculación obligatoria de dispositivo" in sent_text or "Compartir mi número" in sent_text
    assert markup.is_persistent is True, "El teclado debe ser persistente (is_persistent=True)"
    assert markup.one_time_keyboard is False
    assert markup.input_field_placeholder is not None
    print("✅ TEST 2 PASÓ: Bloquea texto arbitrario y mantiene el teclado oficial bloqueado y persistente.")

    # -------------------------------------------------------------------------
    # TEST 3: Seguridad anti-spoofing y registro auténtico de contacto
    # -------------------------------------------------------------------------
    print("\n[TEST 3] Validación anti-spoofing de contacto y registro de perfil verificado...")
    # 3.A: Intento de spoofing con tarjeta de contacto de tercero (user_id distinto)
    update_mock.message.reply_text.reset_mock()
    update_mock.message.contact = MagicMock()
    update_mock.message.contact.user_id = 99999999  # Distinto al test_uid
    update_mock.message.contact.phone_number = f"+52 {test_phone}"

    await bot.recibir_contacto_cliente(update_mock, context_mock)
    args, kwargs = update_mock.message.reply_text.call_args
    assert "Contacto no válido por seguridad" in args[0], "Debe rechazar contactos de terceros"
    assert bot.get_registered_customer(test_uid) is None, "No debe registrar si es contacto ajeno"

    # 3.B: Contacto legítimo desde el propio dispositivo (user_id coincide)
    update_mock.message.reply_text.reset_mock()
    update_mock.message.contact.user_id = test_uid
    update_mock.effective_user.full_name = test_user_name

    await bot.recibir_contacto_cliente(update_mock, context_mock)

    # Debe auto-capturar el nombre verificado del perfil de Telegram y registrarlo de inmediato
    saved_cust = bot.get_registered_customer(test_uid)
    assert saved_cust is not None, "El cliente debería estar registrado en la BD"
    assert saved_cust.phone == test_phone
    assert saved_cust.name == test_user_name
    assert context_mock.user_data.get("awaiting_registration_name") is None

    # Verificar que identity_store lo mapeó
    mapped_p = identity_store.get_phone_for_channel_user("telegram", str(test_uid))
    assert mapped_p == test_phone, f"Identity store debería mapear a {test_phone}"
    print(f"✅ TEST 3 PASÓ: Anti-spoofing validado y perfil de Telegram '{saved_cust.name}' ({saved_cust.phone}) registrado automáticamente.")

    # -------------------------------------------------------------------------
    # TEST 4: Usuario registrado envía /start o /menu -> Ve Menú Principal
    # -------------------------------------------------------------------------
    print("\n[TEST 4] /start o /menu con usuario registrado...")
    update_mock.message.contact = None
    update_mock.message.reply_text.reset_mock()

    await bot.start(update_mock, context_mock)
    args, kwargs = update_mock.message.reply_text.call_args
    sent_text = args[0]
    markup = kwargs.get("reply_markup")
    assert test_user_name in sent_text
    assert test_phone in sent_text
    assert markup is not None
    button_texts = [btn.text for row in markup.inline_keyboard for btn in row]
    assert "📦 Hacer un Pedido" in button_texts
    assert "⚙️ Mi Cuenta" in button_texts
    print("✅ TEST 4 PASÓ: Usuario reconocido ve el menú principal con sus botones.")

    # -------------------------------------------------------------------------
    # TEST 5: Menú "Mi Cuenta" y Cambio de Nombre
    # -------------------------------------------------------------------------
    print("\n[TEST 5] Entrar a Mi Cuenta y modificar nombre...")
    # Simular callback menu:mi_cuenta
    query_mock = MagicMock()
    query_mock.data = "menu:mi_cuenta"
    query_mock.from_user.id = test_uid
    query_mock.message = MagicMock()
    query_mock.message.reply_text = AsyncMock()
    query_mock.answer = AsyncMock()
    query_mock.edit_message_text = AsyncMock()

    update_cb = MagicMock()
    update_cb.callback_query = query_mock
    update_cb.effective_user.id = test_uid
    update_cb.effective_chat.id = test_uid

    await bot.manejar_callback_cliente(update_cb, context_mock)
    query_mock.edit_message_text.assert_called_once()
    args, kwargs = query_mock.edit_message_text.call_args
    assert "Gestión de Mi Cuenta" in args[0]
    cb_btns = [btn.callback_data for row in kwargs["reply_markup"].inline_keyboard for btn in row]
    assert "account:edit_name" in cb_btns
    assert "account:manage_addresses" in cb_btns
    assert "account:delete_account" in cb_btns

    # Ahora pulsar "account:edit_name"
    query_mock.edit_message_text.reset_mock()
    query_mock.data = "account:edit_name"
    await bot.manejar_callback_cliente(update_cb, context_mock)
    assert context_mock.user_data.get("awaiting_account_name_edit") is True

    # El usuario escribe su nuevo nombre
    update_mock.message.reply_text.reset_mock()
    update_mock.message.text = "Luke Skywalker Renombrado"
    await bot.responder(update_mock, context_mock)

    # Verificar que el nombre se actualizó en la BD
    updated_cust = bot.get_registered_customer(test_uid)
    assert updated_cust.name == "Luke Skywalker Renombrado", f"Esperado Luke Skywalker Renombrado, obtenido {updated_cust.name}"
    print(f"✅ TEST 5 PASÓ: Nombre actualizado exitosamente en BD a '{updated_cust.name}'.")

    # -------------------------------------------------------------------------
    # TEST 5.5: Gestión de Direcciones desde "Mi Cuenta" (Ver, Agregar, Eliminar)
    # -------------------------------------------------------------------------
    print("\n[TEST 5.5] Gestión de direcciones desde Mi Cuenta...")
    # Abrir pantalla de direcciones
    query_mock.edit_message_text.reset_mock()
    query_mock.data = "account:manage_addresses"
    await bot.manejar_callback_cliente(update_cb, context_mock)
    args, kwargs = query_mock.edit_message_text.call_args
    assert "Mis Direcciones Guardadas" in args[0]
    addr_cb_btns = [btn.callback_data for row in kwargs["reply_markup"].inline_keyboard for btn in row]
    assert "account_addr:add" in addr_cb_btns

    # Pulsar "account_addr:add"
    query_mock.edit_message_text.reset_mock()
    query_mock.data = "account_addr:add"
    await bot.manejar_callback_cliente(update_cb, context_mock)
    assert context_mock.user_data.get("awaiting_account_new_address") is True

    # Enviar texto de nueva dirección
    update_mock.message.reply_text.reset_mock()
    update_mock.message.text = "Av. Insurgentes 789, Col. Centro, Mazatlán"
    await bot.responder(update_mock, context_mock)
    assert context_mock.user_data.get("awaiting_account_new_address") is None

    # Verificar que se guardó en la BD
    cust_with_addr = repo.get_customer_by_phone(tenant_id, test_phone)
    assert any("Insurgentes 789" in a.address for a in cust_with_addr.addresses)
    added_addr = next(a for a in cust_with_addr.addresses if "Insurgentes 789" in a.address)

    # Eliminar la dirección recién agregada
    query_mock.edit_message_text.reset_mock()
    query_mock.data = f"account_addr:del:{added_addr.id}"
    await bot.manejar_callback_cliente(update_cb, context_mock)
    args, kwargs = query_mock.edit_message_text.call_args
    assert "deseas eliminar esta dirección" in args[0].lower()

    # Confirmar eliminación
    query_mock.edit_message_text.reset_mock()
    query_mock.data = f"account_addr:del_confirm:{added_addr.id}"
    await bot.manejar_callback_cliente(update_cb, context_mock)

    # Verificar que la dirección fue eliminada
    cust_after_del = repo.get_customer_by_phone(tenant_id, test_phone)
    assert not any(str(a.id) == str(added_addr.id) for a in (cust_after_del.addresses or []))
    print("✅ TEST 5.5 PASÓ: Gestión completa de direcciones (ver, agregar y eliminar) en Mi Cuenta funcionando.")

    # -------------------------------------------------------------------------
    # TEST 6: Hacer un Pedido sin volver a pedir teléfono
    # -------------------------------------------------------------------------
    print("\n[TEST 6] Flujo de pedido: Seleccionar cilindro y verificar que no pide teléfono...")
    # Guardar una dirección previa para el cliente
    cust_for_addr = repo.get_customer_by_phone(tenant_id, test_phone)
    if cust_for_addr and cust_for_addr.id:
        repo.add_customer_address(cust_for_addr.id, "Av del Mar 123, Mazatlán", alias="Casa")

    # Iniciar pedido desde el menú
    query_mock.edit_message_text.reset_mock()
    query_mock.data = "menu:hacer_pedido"
    await bot.manejar_callback_cliente(update_cb, context_mock)

    # Seleccionar cilindro
    query_mock.data = "client_svc:cilindro"
    context_mock.bot.send_message = AsyncMock()
    await bot.manejar_callback_cliente(update_cb, context_mock)

    # Agregar cilindro 30kg al carrito
    query_mock.data = "cart_add:gas-lp-30kg"
    await bot.manejar_callback_cliente(update_cb, context_mock)

    # Finalizar selección de cilindro (checkout del carrito mediante callback del bot)
    thread_id = f"telegram:{tenant_id}:{test_uid}"
    context_mock.bot.send_message.reset_mock()
    query_mock.data = "cart_checkout"
    await bot.manejar_callback_cliente(update_cb, context_mock)

    sess = flow_router.get_session(thread_id)
    # Debe haber saltado WAITING_FOR_PHONE y haber avanzado a WAITING_FOR_ADDRESS_SELECTION
    assert sess.state == FlowState.WAITING_FOR_ADDRESS_SELECTION, f"Estado esperado WAITING_FOR_ADDRESS_SELECTION, obtenido {sess.state}"

    context_mock.bot.send_message.assert_called_once()
    sent_text = context_mock.bot.send_message.call_args[1]["text"]
    assert "número celular" not in sent_text.lower(), "NO debe solicitar el número de teléfono"
    assert "dirección" in sent_text.lower(), "Debe preguntar a cuál de las direcciones enviar"
    print("✅ TEST 6 PASÓ: El pedido avanzó directamente a selección de dirección sin pedir teléfono.")

    # -------------------------------------------------------------------------
    # TEST 7: Dar de baja la cuenta (Borrado total)
    # -------------------------------------------------------------------------
    print("\n[TEST 7] Dar de baja la cuenta...")
    # Solicitar baja
    query_mock.edit_message_text.reset_mock()
    query_mock.data = "account:delete_account"
    await bot.manejar_callback_cliente(update_cb, context_mock)
    args, kwargs = query_mock.edit_message_text.call_args
    assert "dar de baja tu cuenta" in args[0].lower()

    # Confirmar baja definitiva
    query_mock.edit_message_text.reset_mock()
    query_mock.data = "account:confirm_delete"
    await bot.manejar_callback_cliente(update_cb, context_mock)
    args, kwargs = query_mock.edit_message_text.call_args
    assert "cuenta ha sido eliminada" in args[0].lower()

    # Verificar que el cliente y sus direcciones quedaron borrados
    deleted_cust = bot.get_registered_customer(test_uid)
    assert deleted_cust is None, "El cliente debe ser completamente inexistente tras la baja"

    deleted_cust_by_phone = repo.get_customer_by_phone(tenant_id, test_phone)
    assert deleted_cust_by_phone is None, "El cliente no debe existir en la BD por teléfono"

    unmapped = identity_store.get_phone_for_channel_user("telegram", str(test_uid))
    assert unmapped is None, "La vinculación en identity_store debe haber sido desvinculada"

    # Verificar que si vuelve a mandar /start, se le pide registrarse de nuevo
    update_mock.message.reply_text.reset_mock()
    await bot.start(update_mock, context_mock)
    args, kwargs = update_mock.message.reply_text.call_args
    assert "Compartir mi número" in args[0] or "1 cuenta por dispositivo" in args[0]
    print("✅ TEST 7 PASÓ: La cuenta fue eliminada completamente y el usuario vuelve al estado no registrado.")

    # -------------------------------------------------------------------------
    # TEST 8: Re-registro tras haber dado de baja la cuenta -> Direcciones vacías
    # -------------------------------------------------------------------------
    print("\n[TEST 8] Re-registro tras baja: verificar que la cuenta inicia limpia sin direcciones...")
    update_mock.message.reply_text.reset_mock()
    update_mock.message.contact = MagicMock()
    update_mock.message.contact.user_id = test_uid
    update_mock.message.contact.phone_number = test_phone
    update_mock.effective_user.full_name = "Nuevo Nombre Re-registrado"
    await bot.recibir_contacto_cliente(update_mock, context_mock)

    re_registered_cust = bot.get_registered_customer(test_uid)
    assert re_registered_cust is not None
    assert re_registered_cust.name == "Nuevo Nombre Re-registrado"
    cust_full = repo.get_customer_by_phone(tenant_id, test_phone)
    assert len(cust_full.addresses) == 0, f"Las direcciones deberían estar vacías, pero se encontraron: {cust_full.addresses}"
    print("✅ TEST 8 PASÓ: Al re-registrarse la cuenta inicia 100% limpia sin direcciones previas.")

    # Limpiar al finalizar el test
    repo.delete_customer(tenant_id, phone=test_phone, channel="telegram", channel_user_id=str(test_uid))
    identity_store.unbind_channel_user("telegram", str(test_uid), phone=test_phone)

    print("\n" + "=" * 60)
    print("🎉 TODAS LAS PRUEBAS DE ONBOARDING Y CUENTA PASARON CON ÉXITO")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_tests())
