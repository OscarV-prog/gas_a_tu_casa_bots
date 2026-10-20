"""Script to adapt telegram_bot.py for Gas a tu Puerta Hermosillo (Hermosillo, Sonora)."""

import re

with open("telegram_bot.py", "r", encoding="utf-8") as f:
    code = f.read()

# 1. Update docstring
code = code.replace(
    '"""Telegram Bot de Producción para Mazatlán (Petroil Gas)."""',
    '"""Telegram Bot adapter for Gas a tu Puerta Hermosillo (Hermosillo, Sonora)."""'
)

# 2. Update dynamic settings import at top level
old_top_import = "from src.services.notifications import notify_driver\nfrom src.tools.get_order_status import format_clean_driver_status"
new_top_import = "from src.services.notifications import notify_driver\nfrom src.services.dynamic_settings import get_dynamic_setting\nfrom src.tools.get_order_status import format_clean_driver_status"
code = code.replace(old_top_import, new_top_import)

# 3. Update TENANT_ID and Token Resolution
old_tenant_token_block = '''# Configuración del tenant
TENANT_ID = "petroil"
tenant = get_tenant(TENANT_ID)
graph = compile_sales_graph()

# Token del bot de clientes Mazatlán (Producción)
settings = get_settings()
TELEGRAM_BOT_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN")
    or settings.telegram_bot_token
    or ""
).strip()
os.environ["IS_PRODUCTION_RUNNER"] = "true"'''

new_tenant_token_block = '''# Configuración del tenant
TENANT_ID = "blue_propane"
tenant = get_tenant(TENANT_ID)
graph = compile_sales_graph()

# Token del bot de clientes (Hermosillo - Sonora / Blue Propane)
settings = get_settings()


def resolve_hermosillo_token() -> str:
    """Resuelve el token de Hermosillo / Blue Propane buscando en variables de entorno, settings o backend remoto."""
    return str(
        os.getenv("TELEGRAM_BOT_HERMOSILLO_TOKEN", "")
        or os.getenv("TELEGRAM_HERMOSILLO", "")
        or os.getenv("TELEGRAM_BOT_BLUE_PROPANE_TOKEN", "")
        or os.getenv("TELEGRAM_BLUE_PROPANE", "")
        or get_dynamic_setting("TELEGRAM_BOT_HERMOSILLO_TOKEN", tenant_id=TENANT_ID, force_refresh=True)
        or get_dynamic_setting("TELEGRAM_HERMOSILLO", tenant_id=TENANT_ID, force_refresh=True)
        or get_dynamic_setting("TELEGRAM_BOT_BLUE_PROPANE_TOKEN", tenant_id=TENANT_ID, force_refresh=True)
        or settings.telegram_bot_hermosillo_token
        or ""
    ).strip()


TELEGRAM_BOT_TOKEN = resolve_hermosillo_token()
os.environ["IS_PRODUCTION_RUNNER"] = "true"'''

code = code.replace(old_tenant_token_block, new_tenant_token_block)

# 4. Update default products catalog
code = code.replace(
    'def get_catalogo_productos_db(tenant_id: str = "petroil") -> list:',
    'def get_catalogo_productos_db(tenant_id: str = "blue_propane") -> list:'
)
code = code.replace(
    'tenant_id="petroil"',
    'tenant_id="blue_propane"'
)

# 4.1 Fallback products for blue_propane
old_fallback_prods = '''    # Fallback predeterminado de cilindros estándar
    from src.models.product import Product
    return [
        Product(id="gas-lp-10kg", tenant_id="blue_propane", name="Cilindro 10 kg", price=230.0, description="Cilindro 10 kg", category="CILINDRO", unit="pieza"),
        Product(id="gas-lp-20kg", tenant_id="blue_propane", name="Cilindro 20 kg", price=450.0, description="Cilindro 20 kg", category="CILINDRO", unit="pieza"),
        Product(id="gas-lp-30kg", tenant_id="blue_propane", name="Cilindro 30 kg", price=670.0, description="Cilindro 30 kg", category="CILINDRO", unit="pieza"),
        Product(id="gas-lp-45kg", tenant_id="blue_propane", name="Cilindro 45 kg", price=990.0, description="Cilindro 45 kg", category="CILINDRO", unit="pieza"),
    ]'''

new_fallback_prods = '''    # Fallback predeterminado de cilindros Blue Propane (Hermosillo)
    from src.models.product import Product
    return [
        Product(id="d5fe2759-a3a1-4fe4-95e9-48ad0f7209a2", tenant_id="blue_propane", name="Cilindro de Gas 20 kg", price=455.0, description="Cilindro 20 kg", category="CILINDRO", unit="pieza"),
        Product(id="11013011-8a51-4602-8824-a6bf7d80426d", tenant_id="blue_propane", name="Cilindro de Gas 30 kg", price=712.5, description="Cilindro 30 kg", category="CILINDRO", unit="pieza"),
        Product(id="390f09c5-3f21-4d72-b5c9-b9c4199ed7db", tenant_id="blue_propane", name="Cilindro de Gas 45 kg", price=1068.0, description="Cilindro 45 kg", category="CILINDRO", unit="pieza"),
    ]'''
code = code.replace(old_fallback_prods, new_fallback_prods)

# 5. Update welcome and branding messages
code = code.replace(
    '👋 ¡Bienvenido a **Gas a Tu Puerta - Petroil**! 🛻💨\n\n',
    '👋 ¡Bienvenido a **Gas a tu Puerta Hermosillo**! 🛻💨\n\n'
)
code = code.replace(
    'Mi función como asistente de **Gas a Tu Puerta - Petroil** es únicamente de atención al cliente:\n\n',
    'Mi función como asistente de **Gas a tu Puerta Hermosillo** es únicamente de atención al cliente:\n\n'
)
code = code.replace(
    'calidad de Petroil. ¡Que tengas un excelente día! 🌟',
    'calidad de Gas a tu Puerta Hermosillo. ¡Que tengas un excelente día! 🌟'
)
code = code.replace(
    'Bienvenido a **Gas a Tu Puerta** 🛻💨',
    'Bienvenido a **Gas a tu Puerta Hermosillo** 🛻💨'
)

# 6. Update geocoding / distance check from Mazatlan to Hermosillo
code = code.replace(
    'from src.services.geocoding import calculate_distance_km, DEFAULT_LAT, DEFAULT_LNG',
    'from src.services.geocoding import calculate_distance_km, HERMOSILLO_LAT, HERMOSILLO_LNG'
)
code = code.replace(
    'calculate_distance_km(geo_lat, geo_lng, DEFAULT_LAT, DEFAULT_LNG)',
    'calculate_distance_km(geo_lat, geo_lng, HERMOSILLO_LAT, HERMOSILLO_LNG)'
)
code = code.replace(
    'calculate_distance_km(lat, lng, DEFAULT_LAT, DEFAULT_LNG)',
    'calculate_distance_km(lat, lng, HERMOSILLO_LAT, HERMOSILLO_LNG)'
)

# 7. Update coverage messages
code = code.replace(
    '⚠️ Por el momento nuestro servicio de Gas a tu Puerta tiene cobertura exclusivamente en la ciudad de Mazatlán, Sinaloa. Por favor proporciona una dirección o ubicación dentro de Mazatlán 📍:',
    '⚠️ Por el momento nuestro servicio de Gas a tu Puerta Hermosillo tiene cobertura exclusivamente en la ciudad de Hermosillo, Sonora. Por favor proporciona una dirección o ubicación dentro de Hermosillo 📍:'
)
code = code.replace(
    'Por favor proporciona una ubicación o dirección dentro de Mazatlán 📍:',
    'Por favor proporciona una ubicación o dirección dentro de Hermosillo 📍:'
)
code = code.replace(
    'Validación de distancia física a Mazatlán (< 35km)',
    'Validación de distancia física a Hermosillo (< 35km)'
)

# 8. Update main() with Hermosillo branding, sync worker & dynamic token resolution loop
old_main_block = '''def main() -> None:
    """Iniciar el bot de Telegram de producción para Mazatlán."""
    if not TELEGRAM_BOT_TOKEN:
        print("❌ ERROR: TELEGRAM_BOT_TOKEN no está configurado.")
        sys.exit(1)

    print("=" * 60)
    print("🤖 Iniciando Bot de Telegram de PRODUCCIÓN - Mazatlán (Petroil Gas)")
    print(f"🏪 Tenant: {tenant.business_name} ({tenant.tenant_id})")
    print(f"🧠 Agente: {tenant.agent.name}")
    print(f"🔑 Token de Mazatlán: {TELEGRAM_BOT_TOKEN[:10]}...")
    print("=" * 60)

    telegram_proxy = os.getenv("TELEGRAM_PROXY_URL")
    telegram_base_url = os.getenv("TELEGRAM_BASE_URL")

    request_kwargs: dict[str, Any] = {
        "connect_timeout": 30.0,
        "read_timeout": 30.0,
        "write_timeout": 30.0,
        "pool_timeout": 30.0,
    }
    if telegram_proxy:
        request_kwargs["proxy_url"] = telegram_proxy

    request_config = HTTPXRequest(**request_kwargs)

    async def _start_prod_bot_sync(app: Application) -> None:
        """Sincronizador en segundo plano para escuchar asignaciones de chofer y GPS en Mazatlán."""
        async def _sync_worker():
            import asyncio
            from src.services.pwa_sync_service import poll_order_updates_once
            logger.info("📡 [ProdBot] Sincronizador de pedidos PWA iniciado para Mazatlán...")
            await asyncio.sleep(2.0)
            while True:
                try:
                    await poll_order_updates_once(tenant_id=TENANT_ID)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.debug(f"[ProdBot Sync] Error en ciclo de sincronización: {e}")
                await asyncio.sleep(3.0)

        import asyncio
        asyncio.create_task(_sync_worker())

    builder = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .request(request_config)
        .get_updates_request(request_config)
        .post_init(_start_prod_bot_sync)
    )
    if telegram_base_url:
        builder = builder.base_url(telegram_base_url)

    application = builder.build()

    # Rastrear origen de bot para todas las interacciones de los usuarios
    application.add_handler(TypeHandler(Update, _track_user_bot_pref), group=-1)

    # Comando /start y /menu
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", start))

    # Recepción de contacto para registro de dispositivo
    application.add_handler(MessageHandler(filters.CONTACT, recibir_contacto_cliente))

    # Recepción de ubicación GPS / tiempo real
    application.add_handler(MessageHandler(filters.LOCATION, recibir_ubicacion_cliente))

    # Recepción de notas de voz y archivos de audio
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, recibir_voz_cliente))

    # Botones interactivos (Cancelar pedido)
    application.add_handler(CallbackQueryHandler(manejar_callback_cliente))

    # Mensajes de texto normales
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            responder,
        )
    )

    print("✅ Bot de Mazatlán conectado con Telegram. Esperando mensajes y pedidos...")
    try:
        application.run_polling(
            bootstrap_retries=10,
            poll_interval=1.0,
            timeout=30,
        )
    except Exception as e:
        err_str = str(e)
        if sys.platform == "win32" and ("All connection attempts failed" in err_str or "ConnectError" in err_str or "ConnectTimeout" in err_str):
            print("\\n" + "!" * 70)
            print("🚨 ERROR DE CONEXIÓN: La red Wi-Fi actual está bloqueando Telegram (api.telegram.org).")
            print("👉 Solución rápida: Conecta tu computadora al Punto de Acceso / Datos Móviles de tu celular.")
            print("   Las redes móviles no bloquean Telegram y el bot encenderá de inmediato.")
            print("!" * 70 + "\\n")
        raise'''

new_main_block = '''def main() -> None:
    """Iniciar el bot de Telegram para Gas a tu Puerta Hermosillo con auto-recuperación continua y supervisor de polling."""
    global TELEGRAM_BOT_TOKEN
    import time

    print("=" * 60)
    print("🤖 Iniciando Bot de Telegram de PRODUCCIÓN - Gas a tu Puerta Hermosillo")
    print(f"🏪 Tenant: {tenant.business_name} ({tenant.tenant_id})")
    print(f"🧠 Agente: {tenant.agent.name}")
    print("=" * 60)

    consecutive_errors = 0
    while True:
        try:
            # 1. Resolver token dinámicamente si aún no está disponible
            while not TELEGRAM_BOT_TOKEN:
                TELEGRAM_BOT_TOKEN = resolve_hermosillo_token()
                if TELEGRAM_BOT_TOKEN:
                    logger.info("✅ Token de Telegram Hermosillo detectado y configurado exitosamente.")
                    break
                logger.info(
                    "[Hermosillo] Esperando configuración de token (TELEGRAM_BOT_HERMOSILLO_TOKEN) en Dashboard o .env (reintentando en 15s)..."
                )
                time.sleep(15)

            telegram_proxy = os.getenv("TELEGRAM_PROXY_URL")
            telegram_base_url = os.getenv("TELEGRAM_BASE_URL")

            request_kwargs: dict[str, Any] = {
                "connect_timeout": 30.0,
                "read_timeout": 30.0,
                "write_timeout": 30.0,
                "pool_timeout": 30.0,
            }
            if telegram_proxy:
                request_kwargs["proxy_url"] = telegram_proxy

            request_config = HTTPXRequest(**request_kwargs)

            async def _start_hermosillo_bot_sync(app: Application) -> None:
                """Sincronizador en segundo plano para escuchar asignaciones de chofer y GPS en Hermosillo."""
                async def _sync_worker():
                    import asyncio
                    from src.services.pwa_sync_service import poll_order_updates_once
                    logger.info("📡 [HermosilloBot] Sincronizador de pedidos PWA iniciado para Hermosillo...")
                    await asyncio.sleep(2.0)
                    while True:
                        try:
                            await poll_order_updates_once(tenant_id=TENANT_ID)
                        except asyncio.CancelledError:
                            break
                        except Exception as e:
                            logger.debug(f"[HermosilloBot Sync] Error en ciclo de sincronización: {e}")
                        await asyncio.sleep(3.0)

                import asyncio
                asyncio.create_task(_sync_worker())

            builder = (
                Application.builder()
                .token(TELEGRAM_BOT_TOKEN)
                .request(request_config)
                .get_updates_request(request_config)
                .post_init(_start_hermosillo_bot_sync)
            )
            if telegram_base_url:
                builder = builder.base_url(telegram_base_url)

            application = builder.build()

            # Rastrear origen de bot para todas las interacciones de los usuarios
            application.add_handler(TypeHandler(Update, _track_user_bot_pref), group=-1)

            # Comando /start y /menu
            application.add_handler(CommandHandler("start", start))
            application.add_handler(CommandHandler("menu", start))

            # Recepción de contacto para registro de dispositivo
            application.add_handler(MessageHandler(filters.CONTACT, recibir_contacto_cliente))

            # Recepción de ubicación GPS / tiempo real
            application.add_handler(MessageHandler(filters.LOCATION, recibir_ubicacion_cliente))

            # Recepción de notas de voz y archivos de audio
            application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, recibir_voz_cliente))

            # Botones interactivos (Cancelar pedido)
            application.add_handler(CallbackQueryHandler(manejar_callback_cliente))

            # Mensajes de texto normales
            application.add_handler(
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    responder,
                )
            )

            print("✅ Bot Gas a tu Puerta Hermosillo conectado con Telegram. Esperando mensajes y pedidos...")
            application.run_polling(
                bootstrap_retries=10,
                poll_interval=1.0,
                timeout=30,
            )
            consecutive_errors = 0

        except KeyboardInterrupt:
            print("\\n🛑 Bot de Hermosillo detenido correctamente por el usuario (Ctrl+C).")
            break
        except Exception as e:
            consecutive_errors += 1
            err_str = str(e)
            if "InvalidToken" in err_str or "Unauthorized" in err_str:
                logger.error("❌ Token de Telegram para Hermosillo no autorizado o inválido (%s). Reintentando obtenerlo del Dashboard...", e)
                TELEGRAM_BOT_TOKEN = ""
                time.sleep(10)
            elif sys.platform == "win32" and ("All connection attempts failed" in err_str or "ConnectError" in err_str or "ConnectTimeout" in err_str):
                print("\\n" + "!" * 70)
                print("🚨 ERROR DE CONEXIÓN: La red Wi-Fi actual está bloqueando Telegram (api.telegram.org).")
                print("👉 Solución rápida: Conecta tu computadora al Punto de Acceso / Datos Móviles de tu celular.")
                print("   Las redes móviles no bloquean Telegram y el bot encenderá de inmediato.")
                print("!" * 70 + "\\n")
                time.sleep(15)
            else:
                logger.error("Error en polling de Telegram Hermosillo: %s. Reintentando en 5s...", e)
                time.sleep(min(30, 5 * consecutive_errors))'''

code = code.replace(old_main_block, new_main_block)

with open("telegram_bot_hermosillo.py", "w", encoding="utf-8") as f:
    f.write(code)

print("telegram_bot_hermosillo.py adaptado exitosamente.")
