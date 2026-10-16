"""Script to adapt telegram_bot.py for Gas a tu Puerta Gascytsa (Culiacán)."""

import re

with open("telegram_bot.py", "r", encoding="utf-8") as f:
    code = f.read()

# 1. Update docstring
code = code.replace(
    '"""Telegram Bot de Producción para Mazatlán (Petroil Gas)."""',
    '"""Telegram Bot adapter for Gas a tu Puerta Gascytsa (Culiacán)."""'
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
).strip()'''

new_tenant_token_block = '''# Configuración del tenant
TENANT_ID = "gascytsa"
tenant = get_tenant(TENANT_ID)
graph = compile_sales_graph()

# Token del bot de clientes (Gascytsa - Culiacán)
settings = get_settings()


def resolve_gascytsa_token() -> str:
    """Resuelve el token de Gascytsa buscando en variables de entorno, settings o backend remoto."""
    return str(
        os.getenv("TELEGRAM_BOT_GASCYTSA_TOKEN", "")
        or os.getenv("TELEGRAM_GASCYTSA", "")
        or get_dynamic_setting("TELEGRAM_BOT_GASCYTSA_TOKEN", tenant_id=TENANT_ID, force_refresh=True)
        or get_dynamic_setting("TELEGRAM_GASCYTSA", tenant_id=TENANT_ID, force_refresh=True)
        or settings.telegram_bot_gascytsa_token
        or ""
    ).strip()


TELEGRAM_BOT_TOKEN = resolve_gascytsa_token()'''

code = code.replace(old_tenant_token_block, new_tenant_token_block)

# 4. Update default products catalog
code = code.replace(
    'def get_catalogo_productos_db(tenant_id: str = "petroil") -> list:',
    'def get_catalogo_productos_db(tenant_id: str = "gascytsa") -> list:'
)
code = code.replace(
    'tenant_id="petroil"',
    'tenant_id="gascytsa"'
)

# 5. Update welcome and branding messages
code = code.replace(
    '👋 ¡Bienvenido a **Gas a Tu Puerta - Petroil**! 🛻💨\n\n',
    '👋 ¡Bienvenido a **Gas a tu Puerta Gascytsa** (Culiacán)! 🛻💨\n\n'
)
code = code.replace(
    'Mi función como asistente de **Gas a Tu Puerta - Petroil** es únicamente de atención al cliente:\n\n',
    'Mi función como asistente de **Gas a tu Puerta Gascytsa** es únicamente de atención al cliente:\n\n'
)
code = code.replace(
    'calidad de Petroil. ¡Que tengas un excelente día! 🌟',
    'calidad de Gascytsa. ¡Que tengas un excelente día! 🌟'
)
code = code.replace(
    'Bienvenido a **Gas a Tu Puerta** 🛻💨',
    'Bienvenido a **Gas a tu Puerta Gascytsa** (Culiacán) 🛻💨'
)

# 6. Update geocoding / distance check from Mazatlan to Culiacan
code = code.replace(
    'from src.services.geocoding import calculate_distance_km, DEFAULT_LAT, DEFAULT_LNG',
    'from src.services.geocoding import calculate_distance_km, CULIACAN_LAT, CULIACAN_LNG'
)
code = code.replace(
    'calculate_distance_km(geo_lat, geo_lng, DEFAULT_LAT, DEFAULT_LNG)',
    'calculate_distance_km(geo_lat, geo_lng, CULIACAN_LAT, CULIACAN_LNG)'
)
code = code.replace(
    'calculate_distance_km(lat, lng, DEFAULT_LAT, DEFAULT_LNG)',
    'calculate_distance_km(lat, lng, CULIACAN_LAT, CULIACAN_LNG)'
)

# 7. Update coverage messages
code = code.replace(
    '⚠️ Por el momento nuestro servicio de Gas a tu Puerta tiene cobertura exclusivamente en la ciudad de Mazatlán, Sinaloa. Por favor proporciona una dirección o ubicación dentro de Mazatlán 📍:',
    '⚠️ Por el momento nuestro servicio de Gas a tu Puerta Gascytsa tiene cobertura exclusivamente en la ciudad de Culiacán, Sinaloa. Por favor proporciona una dirección o ubicación dentro de Culiacán 📍:'
)
code = code.replace(
    'Por favor proporciona una ubicación o dirección dentro de Mazatlán 📍:',
    'Por favor proporciona una ubicación o dirección dentro de Culiacán 📍:'
)
code = code.replace(
    'Validación de distancia física a Mazatlán (< 35km)',
    'Validación de distancia física a Culiacán (< 35km)'
)

# 8. Update main() with Gascytsa branding & dynamic token resolution loop
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

    builder = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .request(request_config)
        .get_updates_request(request_config)
    )
    if telegram_base_url:
        builder = builder.base_url(telegram_base_url)

    application = builder.build()

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
    """Iniciar el bot de Telegram para Gascytsa (Culiacán) con auto-recuperación continua y supervisor de polling."""
    global TELEGRAM_BOT_TOKEN
    import time

    print("=" * 60)
    print("🤖 Iniciando Bot de Telegram de PRODUCCIÓN - Gascytsa (Culiacán)")
    print(f"🏪 Tenant: {tenant.business_name} ({tenant.tenant_id})")
    print(f"🧠 Agente: {tenant.agent.name}")
    print("=" * 60)

    consecutive_errors = 0
    while True:
        try:
            # 1. Resolver token dinámicamente si aún no está disponible
            while not TELEGRAM_BOT_TOKEN:
                TELEGRAM_BOT_TOKEN = resolve_gascytsa_token()
                if TELEGRAM_BOT_TOKEN:
                    logger.info("✅ Token de Telegram Gascytsa detectado y configurado exitosamente.")
                    break
                logger.info(
                    "[Gascytsa] Esperando configuración de token (TELEGRAM_GASCYTSA) en Dashboard o .env (reintentando en 15s)..."
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

            builder = (
                Application.builder()
                .token(TELEGRAM_BOT_TOKEN)
                .request(request_config)
                .get_updates_request(request_config)
            )
            if telegram_base_url:
                builder = builder.base_url(telegram_base_url)

            application = builder.build()

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

            print("✅ Bot Gascytsa (Culiacán) conectado con Telegram. Esperando mensajes y pedidos...")
            application.run_polling(
                bootstrap_retries=10,
                poll_interval=1.0,
                timeout=30,
            )
            consecutive_errors = 0

        except KeyboardInterrupt:
            print("\\n🛑 Bot de Gascytsa detenido correctamente por el usuario (Ctrl+C).")
            break
        except Exception as e:
            consecutive_errors += 1
            err_str = str(e)
            if "InvalidToken" in err_str or "Unauthorized" in err_str:
                logger.error("❌ Token de Telegram para Gascytsa no autorizado o inválido (%s). Reintentando obtenerlo del Dashboard...", e)
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
                logger.error("Error en polling de Telegram Gascytsa: %s. Reintentando en 5s...", e)
                time.sleep(min(30, 5 * consecutive_errors))'''

code = code.replace(old_main_block, new_main_block)

with open("telegram_bot_gascytsa.py", "w", encoding="utf-8") as f:
    f.write(code)

print("telegram_bot_gascytsa.py adaptado exitosamente.")
