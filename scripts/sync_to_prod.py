"""Script to sync the tested and perfected logic from telegram_bot_test.py to telegram_bot.py."""

with open("telegram_bot_test.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Update docstring
content = content.replace(
    '"""Telegram Bot de Pruebas (Copia exacta de Mazatlán para pruebas locales)."""',
    '"""Telegram Bot de Producción para Mazatlán (Petroil Gas)."""'
)

# 2. Update Token resolution and process runner flag
old_token_block = '''# Token del bot de pruebas (Copia exacta de Mazatlán para entorno de pruebas)
settings = get_settings()
TELEGRAM_BOT_TOKEN = (
    os.getenv("TELEGRAM_TEST_BOT_TOKEN")
    or os.getenv("TELEGRAM_BOT_TOKEN")
    or settings.telegram_bot_token
    or ""
).strip()
os.environ["IS_TEST_BOT_PROCESS"] = "true"'''

new_token_block = '''# Token del bot de clientes Mazatlán (Producción)
settings = get_settings()
TELEGRAM_BOT_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN")
    or settings.telegram_bot_token
    or ""
).strip()
os.environ["IS_PRODUCTION_RUNNER"] = "true"'''

content = content.replace(old_token_block, new_token_block)

# 3. Update main() messages
content = content.replace(
    '"""Iniciar el bot de Telegram de pruebas."""',
    '"""Iniciar el bot de Telegram de producción para Mazatlán."""'
)

content = content.replace(
    'print("❌ ERROR: TELEGRAM_TEST_BOT_TOKEN no está configurado.")',
    'print("❌ ERROR: TELEGRAM_BOT_TOKEN no está configurado.")'
)

content = content.replace(
    'print("🤖 Iniciando Bot de Telegram de PRUEBAS (Copia Mazatlán)")',
    'print("🤖 Iniciando Bot de Telegram de PRODUCCIÓN - Mazatlán (Petroil Gas)")'
)

content = content.replace(
    'print(f"🔑 Token de Pruebas: {TELEGRAM_BOT_TOKEN[:10]}...")',
    'print(f"🔑 Token de Mazatlán: {TELEGRAM_BOT_TOKEN[:10]}...")'
)

content = content.replace(
    'print("✅ Bot de Pruebas conectado con Telegram. Esperando mensajes y pedidos...")',
    'print("✅ Bot de Mazatlán conectado con Telegram. Esperando mensajes y pedidos...")'
)

# 4. Update background sync worker
content = content.replace(
    '_start_test_bot_sync',
    '_start_prod_bot_sync'
)
content = content.replace(
    'Sincronizador en segundo plano para escuchar asignaciones de chofer y GPS en Luke GasSkywalker.',
    'Sincronizador en segundo plano para escuchar asignaciones de chofer y GPS en Mazatlán.'
)
content = content.replace(
    '📡 [TestBot] Sincronizador de pedidos PWA iniciado para Luke GasSkywalker...',
    '📡 [ProdBot] Sincronizador de pedidos PWA iniciado para Mazatlán...'
)
content = content.replace(
    '[TestBot Sync]',
    '[ProdBot Sync]'
)

with open("telegram_bot.py", "w", encoding="utf-8") as f:
    f.write(content)

print("Sincronización completada exitosamente a telegram_bot.py")

