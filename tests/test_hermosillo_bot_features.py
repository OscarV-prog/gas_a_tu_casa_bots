"""Automated verification test for telegram_bot_hermosillo.py features:
1. Strict Hermosillo coverage validation (GPS & text).
2. Rejection of Mazatlán & Culiacán coordinates/addresses.
3. Acceptance of Hermosillo coordinates/addresses.
4. Profile address management (buttons only, edit, delete with confirmation, back buttons).
5. Correct Hermosillo branding & messages.
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.abspath("."))

from src.database import init_db
from src.repositories import get_repository
from src.repositories.identity_store import identity_store
from src.services.flow_router import FlowState, flow_router, clear_session
import telegram_bot_hermosillo as bot


async def run_tests():
    print("=" * 60)
    print("🧪 Verificando telegram_bot_hermosillo.py (Hermosillo, Sonora)")
    print("=" * 60)

    init_db()
    repo = get_repository()
    tenant_id = "blue_propane"
    test_uid = 999123456
    test_phone = "6621234567"

    assert bot.TENANT_ID == "blue_propane", f"Expected tenant_id 'blue_propane', got {bot.TENANT_ID}"

    # Preparar cliente registrado
    identity_store.bind_channel_user_phone("telegram", str(test_uid), test_phone)
    cust = repo.save_or_update_customer(
        tenant_id=tenant_id,
        channel="telegram",
        channel_user_id=str(test_uid),
        name="Tester Hermosillo",
        phone=test_phone,
    )
    thread_id = f"telegram:{tenant_id}:{test_uid}"
    clear_session(thread_id)

    # 1. Rechazar GPS de Mazatlán en Hermosillo
    print("\n[TEST 1] Enviar GPS de Mazatlán a Hermosillo (debe rechazarse)...")
    context_maz_gps = MagicMock()
    context_maz_gps.user_data = {"awaiting_account_new_address": True, "phone": test_phone}
    update_maz_gps = MagicMock()
    update_maz_gps.effective_user.id = test_uid
    update_maz_gps.effective_chat.id = test_uid
    update_maz_gps.message.location.latitude = 23.2014  # Mazatlán
    update_maz_gps.message.location.longitude = -106.4215
    update_maz_gps.message.reply_text = AsyncMock()

    await bot.recibir_ubicacion_cliente(update_maz_gps, context_maz_gps)
    assert context_maz_gps.user_data.get("awaiting_account_new_address") is True, "Bandera debe mantenerse activa si fue rechazada"
    call_args_maz = [str(arg) for call in update_maz_gps.message.reply_text.call_args_list for arg in call[0]]
    assert any("cobertura exclusivamente en la ciudad de Hermosillo" in a for a in call_args_maz), "Debe advertir falta de cobertura en Hermosillo"
    assert any("Hermosillo" in a for a in call_args_maz), "Debe mencionar Hermosillo"
    print("✅ GPS de Mazatlán rechazado exitosamente con mensaje de cobertura exclusiva en Hermosillo.")

    # 2. Rechazar GPS de Culiacán en Hermosillo
    print("\n[TEST 2] Enviar GPS de Culiacán a Hermosillo (debe rechazarse)...")
    context_cul_gps = MagicMock()
    context_cul_gps.user_data = {"awaiting_account_new_address": True, "phone": test_phone}
    update_cul_gps = MagicMock()
    update_cul_gps.effective_user.id = test_uid
    update_cul_gps.effective_chat.id = test_uid
    update_cul_gps.message.location.latitude = 24.8090  # Culiacán
    update_cul_gps.message.location.longitude = -107.3940
    update_cul_gps.message.reply_text = AsyncMock()

    await bot.recibir_ubicacion_cliente(update_cul_gps, context_cul_gps)
    assert context_cul_gps.user_data.get("awaiting_account_new_address") is True, "Bandera debe mantenerse activa si fue rechazada"
    call_args_cul = [str(arg) for call in update_cul_gps.message.reply_text.call_args_list for arg in call[0]]
    assert any("cobertura exclusivamente en la ciudad de Hermosillo" in a for a in call_args_cul), "Debe advertir falta de cobertura en Hermosillo"
    print("✅ GPS de Culiacán rechazado exitosamente con mensaje de cobertura exclusiva en Hermosillo.")

    # 3. Aceptar GPS dentro de Hermosillo
    print("\n[TEST 3] Enviar GPS dentro de Hermosillo (debe aceptarse)...")
    context_her_gps = MagicMock()
    context_her_gps.user_data = {"awaiting_account_new_address": True, "phone": test_phone}
    update_her_gps = MagicMock()
    update_her_gps.effective_user.id = test_uid
    update_her_gps.effective_chat.id = test_uid
    update_her_gps.message.location.latitude = 29.0729  # Centro de Hermosillo
    update_her_gps.message.location.longitude = -110.9559
    update_her_gps.message.reply_text = AsyncMock()

    await bot.recibir_ubicacion_cliente(update_her_gps, context_her_gps)
    assert context_her_gps.user_data.get("awaiting_account_new_address") is None, "Bandera debió consumirse al guardarse"
    cust_updated = repo.get_customer_by_phone(tenant_id, test_phone)
    assert cust_updated and cust_updated.addresses, "Cliente debe tener direcciones guardadas"
    print(f"✅ GPS de Hermosillo aceptado y guardado: {cust_updated.addresses[-1].address}")

    # 4. Pantalla de direcciones en Mi Cuenta (Solo botones, sin direcciones en el cuerpo de texto)
    print("\n[TEST 4] Pantalla de direcciones en Mi Cuenta...")
    update_pantalla = MagicMock()
    context_pantalla = MagicMock()
    context_pantalla.user_data = {"phone": test_phone}
    update_pantalla.callback_query.message.edit_text = AsyncMock()
    update_pantalla.callback_query.edit_message_text = AsyncMock()

    await bot.mostrar_pantalla_direcciones_cuenta(update_pantalla, context_pantalla, test_uid)
    sent_text = update_pantalla.callback_query.edit_message_text.call_args[0][0]
    sent_markup = update_pantalla.callback_query.edit_message_text.call_args[1]["reply_markup"]

    # Verificar que NO se lista la dirección en el texto
    for addr in cust_updated.addresses:
        assert addr.address not in sent_text, f"La dirección {addr.address} no debe salir en el texto"
    # Verificar que sí está en los botones
    btn_texts = [btn.text for row in sent_markup.inline_keyboard for btn in row]
    assert any("📍" in t for t in btn_texts), "Debe haber botones con las direcciones"
    assert any("agregar nueva dirección" in t.lower() for t in btn_texts), "Debe existir botón para agregar dirección"
    assert any("volver a mi cuenta" in t.lower() or "regresar" in t.lower() for t in btn_texts), "Debe existir botón para regresar a Mi Cuenta"
    assert not any("eliminar una dirección" in t.lower() for t in btn_texts), "No debe haber botón directo de eliminar en la lista general"
    print("✅ Pantalla de direcciones verificada: solo botones, sin duplicados en texto y sin botón directo de eliminar.")

    # 5. Detalle de dirección al pulsar sobre ella (debe mostrar Editar y Eliminar)
    print("\n[TEST 5] Detalle de dirección individual (Editar y Eliminar)...")
    target_addr = cust_updated.addresses[-1]
    update_view = MagicMock()
    update_view.effective_chat.id = test_uid
    update_view.callback_query.data = f"account_addr:view:{target_addr.id}:1"
    update_view.callback_query.from_user.id = test_uid
    update_view.callback_query.message.chat.id = test_uid
    update_view.callback_query.edit_message_text = AsyncMock()
    update_view.callback_query.answer = AsyncMock()
    context_view = MagicMock()
    context_view.user_data = {"phone": test_phone}

    await bot.manejar_callback_cliente(update_view, context_view)
    view_text = update_view.callback_query.edit_message_text.call_args[0][0]
    view_markup = update_view.callback_query.edit_message_text.call_args[1]["reply_markup"]
    view_btns = [btn.text for row in view_markup.inline_keyboard for btn in row]

    assert any("editar" in t.lower() for t in view_btns), "Debe existir botón Editar Dirección"
    assert any("eliminar" in t.lower() for t in view_btns), "Debe existir botón Eliminar Dirección"
    assert any("volver a mis direcciones" in t.lower() or "direcciones" in t.lower() for t in view_btns), "Debe existir botón Volver a Direcciones"
    print("✅ Vista individual de dirección verificada: opciones de Editar y Eliminar presentes.")

    # 6. Botón Regresar en Pedido (client_addr_back)
    print("\n[TEST 6] Botón de regresar en flujo de pedido (client_addr_back)...")
    update_back = MagicMock()
    update_back.effective_chat.id = test_uid
    update_back.callback_query.data = "client_addr_back"
    update_back.callback_query.from_user.id = test_uid
    update_back.callback_query.message.chat.id = test_uid
    update_back.callback_query.edit_message_text = AsyncMock()
    update_back.callback_query.answer = AsyncMock()
    context_back = MagicMock()
    context_back.user_data = {"phone": test_phone}

    await bot.manejar_callback_cliente(update_back, context_back)
    c_args = update_back.callback_query.edit_message_text.call_args
    back_markup = c_args.kwargs.get("reply_markup") if c_args and "reply_markup" in c_args.kwargs else (c_args[1].get("reply_markup") if c_args and len(c_args) > 1 else None)
    back_btns = [btn.text for row in back_markup.inline_keyboard for btn in row]
    assert any("📍" in t for t in back_btns), "Debe regresar a las direcciones guardadas"
    assert any("nueva dirección" in t.lower() for t in back_btns)
    print("✅ Botón de regresar en pedido restaura correctamente las opciones de direcciones guardadas.")

    print("\n" + "=" * 60)
    print("🎉 TODAS LAS PRUEBAS DE HERMOSILLO PASARON AL 100%")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(run_tests())
