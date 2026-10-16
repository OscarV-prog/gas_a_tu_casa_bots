"""Test GPS and text address handling both in 'Mi Cuenta' and in the active order flow."""

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
import telegram_bot_test as bot


async def run():
    print("=" * 60)
    print("🧪 Verificando flujo GPS y Direcciones en Mi Cuenta y Pedido")
    print("=" * 60)

    init_db()
    repo = get_repository()
    tenant_id = "petroil"
    test_uid = 999123456
    test_phone = "6699887766"

    # Preparar cliente registrado
    identity_store.bind_channel_user_phone("telegram", str(test_uid), test_phone)
    cust = repo.save_or_update_customer(
        tenant_id=tenant_id,
        channel="telegram",
        channel_user_id=str(test_uid),
        name="Tester Gas",
        phone=test_phone,
    )
    thread_id = f"telegram:{tenant_id}:{test_uid}"
    clear_session(thread_id)

    # 0. Rechazar ubicación GPS FUERA de Mazatlán en Mi Cuenta (ej. Culiacán)
    print("\n[TEST 0.1] Intentar agregar GPS fuera de Mazatlán en Mi Cuenta (debe rechazarse)...")
    context_out_gps = MagicMock()
    context_out_gps.user_data = {"awaiting_account_new_address": True, "phone": test_phone}
    update_out_gps = MagicMock()
    update_out_gps.effective_user.id = test_uid
    update_out_gps.effective_chat.id = test_uid
    update_out_gps.message.location.latitude = 24.8090  # Culiacán
    update_out_gps.message.location.longitude = -107.3940
    update_out_gps.message.reply_text = AsyncMock()

    await bot.recibir_ubicacion_cliente(update_out_gps, context_out_gps)
    assert context_out_gps.user_data.get("awaiting_account_new_address") is True, "Bandera debe mantenerse activa si fue rechazada"
    call_args_gps = [str(arg) for call in update_out_gps.message.reply_text.call_args_list for arg in call[0]]
    assert any("cobertura exclusivamente en la ciudad de Mazatlán" in a for a in call_args_gps), "Debe advertir falta de cobertura en Mazatlán"
    print("✅ GPS fuera de Mazatlán rechazado exitosamente con mensaje de cobertura.")

    # 0.2 Rechazar dirección de TEXTO FUERA de Mazatlán en Mi Cuenta (ej. Culiacán)
    print("\n[TEST 0.2] Intentar agregar texto fuera de Mazatlán en Mi Cuenta (debe rechazarse)...")
    context_out_txt = MagicMock()
    context_out_txt.user_data = {"awaiting_account_new_address": True, "phone": test_phone}
    update_out_txt = MagicMock()
    update_out_txt.effective_user.id = test_uid
    update_out_txt.effective_chat.id = test_uid
    update_out_txt.message.text = "Blvd. Pedro Infante 2200, Desarrollo Urbano Tres Ríos, Culiacán"
    update_out_txt.message.reply_text = AsyncMock()

    await bot.responder(update_out_txt, context_out_txt)
    assert context_out_txt.user_data.get("awaiting_account_new_address") is True, "Bandera debe mantenerse activa si fue rechazada por texto"
    call_args_txt = [str(arg) for call in update_out_txt.message.reply_text.call_args_list for arg in call[0]]
    assert any("cobertura exclusivamente en la ciudad de Mazatlán" in a for a in call_args_txt), "Debe advertir falta de cobertura en Mazatlán"
    print("✅ Dirección de texto fuera de Mazatlán rechazada exitosamente con mensaje de cobertura.")

    # 1. Agregar dirección por GPS en Mi Cuenta (DENTRO de Mazatlán)
    print("\n[TEST 1] Agregar dirección por GPS en Mi Cuenta (válida en Mazatlán)...")
    context_mock = MagicMock()
    context_mock.user_data = {"awaiting_account_new_address": True, "phone": test_phone}
    update_mock = MagicMock()
    update_mock.effective_user.id = test_uid
    update_mock.effective_chat.id = test_uid
    update_mock.message.location.latitude = 23.2389
    update_mock.message.location.longitude = -106.4173
    update_mock.message.reply_text = AsyncMock()

    await bot.recibir_ubicacion_cliente(update_mock, context_mock)
    assert not context_mock.user_data.get("awaiting_account_new_address"), "Bandera awaiting_account_new_address debe ser retirada"
    
    cust_updated = repo.get_customer_by_phone(tenant_id, test_phone)
    assert cust_updated and cust_updated.addresses, "El cliente debe tener al menos una dirección guardada por GPS"
    print(f"✅ Dirección agregada por GPS: {cust_updated.addresses[-1].address}")

    # 2. Agregar dirección por TEXTO en Mi Cuenta
    print("\n[TEST 2] Agregar dirección por TEXTO en Mi Cuenta...")
    context_mock.user_data = {"awaiting_account_new_address": True, "phone": test_phone}
    update_text = MagicMock()
    update_text.effective_user.id = test_uid
    update_text.effective_chat.id = test_uid
    update_text.message.text = "Av. Del Mar 1200, Col. Palos Prietos"
    update_text.message.reply_text = AsyncMock()

    await bot.responder(update_text, context_mock)
    assert not context_mock.user_data.get("awaiting_account_new_address"), "Bandera awaiting_account_new_address debe ser retirada tras texto"
    cust_updated2 = repo.get_customer_by_phone(tenant_id, test_phone)
    assert len(cust_updated2.addresses) >= 2, "Debe tener al menos 2 direcciones guardadas"
    print(f"✅ Dirección agregada por TEXTO: {cust_updated2.addresses[-1].address}")

    # 3. Flujo de Pedido: Enviar ubicación GPS y verificar avance directo a selección de horario
    print("\n[TEST 3] Enviar ubicación GPS en flujo de pedido (WAITING_FOR_ADDRESS_SELECTION)...")
    clear_session(thread_id)
    from src.services.flow_router import get_or_create_session
    session = get_or_create_session(thread_id, tenant_id=tenant_id, channel="telegram", channel_user_id=str(test_uid))
    session.draft_order.customer_name = "Tester Gas"
    session.draft_order.customer_phone = test_phone
    session.draft_order.items = [MagicMock(product_id="gas-lp-30kg", quantity=1, unit_price=670.0)]
    session.state = FlowState.WAITING_FOR_ADDRESS_SELECTION

    context_order = MagicMock()
    context_order.user_data = {"phone": test_phone}
    update_order = MagicMock()
    update_order.effective_user.id = test_uid
    update_order.effective_chat.id = test_uid
    update_order.message.location.latitude = 23.2450
    update_order.message.location.longitude = -106.4200
    update_order.message.reply_text = AsyncMock()

    await bot.recibir_ubicacion_cliente(update_order, context_order)
    
    # Verificar que el flow avanzó a WAITING_FOR_SCHEDULE
    sess_after = flow_router.get_session(thread_id)
    assert sess_after.state == FlowState.WAITING_FOR_SCHEDULE, f"El estado debe ser WAITING_FOR_SCHEDULE, fue: {sess_after.state}"
    print(f"✅ Estado del pedido tras enviar GPS: {sess_after.state}")
    assert sess_after.draft_order.delivery_lat == 23.2450
    assert sess_after.draft_order.delivery_lng == -106.4200
    print(f"✅ Dirección de entrega guardada en draft: {sess_after.draft_order.delivery_address}")

    # Verificar que reply_text fue llamado con botones de horario
    called_markup = update_order.message.reply_text.call_args[1].get("reply_markup")
    assert called_markup is not None, "Debe enviar botones interactivos para horario"
    markup_str = str(called_markup)
    assert "client_sch:asap" in markup_str, "Debe incluir botón 'Lo antes posible'"
    print("✅ Botones de horario ('⚡ Lo antes posible' / '📅 Programar entrega') enviados correctamente.")

    # 4. Eliminar dirección en Mi Cuenta
    print("\n[TEST 4] Eliminar una dirección en Mi Cuenta...")
    addr_to_del = cust_updated2.addresses[0]
    query_mock = MagicMock()
    query_mock.data = f"account_addr:del_confirm:{addr_to_del.id}:1"
    query_mock.from_user.id = test_uid
    query_mock.message.reply_text = AsyncMock()
    query_mock.edit_message_text = AsyncMock()
    query_mock.answer = AsyncMock()
    update_del = MagicMock()
    update_del.callback_query = query_mock
    update_del.effective_user.id = test_uid
    update_del.effective_chat.id = test_uid

    await bot.manejar_callback_cliente(update_del, context_mock)
    assert identity_store.is_address_deleted(test_phone, addr_to_del.address), "La dirección debe estar marcada como eliminada"
    print(f"✅ Dirección eliminada exitosamente: {addr_to_del.address}")

    print("\n" + "=" * 60)
    print("🎉 TODAS LAS PRUEBAS DE GPS Y DIRECCIONES PASARON AL 100%")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run())
