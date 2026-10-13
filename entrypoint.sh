#!/bin/bash
set -e

# Si el comando es "all", levantamos todos los servicios de forma orquestada
if [ "$1" = "all" ]; then
    echo "========================================================="
    echo "  Iniciando Suite de Bots Gas a Tu Puerta (Docker)       "
    echo "========================================================="

    # 0. Configurar API_BASE_URL por defecto si no viene en el .env
    export API_BASE_URL="${API_BASE_URL:-https://petrogas-api.petroil.dev/api}"

    # 1. API FastAPI (Webhooks de Meta Messenger, PWA Sync, Tracking)
    echo "[1/4] Iniciando API FastAPI en http://0.0.0.0:3000..."
    uvicorn src.app:app --host 0.0.0.0 --port 3000 &
    API_PID=$!

    # Sincronizar configuraciones remotas desde el backend central y cargarlas en el entorno de Bash
    echo "[Info] Sincronizando configuraciones dinámicas desde el backend central..."
    python -c "from src.services.dynamic_settings import export_env_file; export_env_file('/tmp/dynamic_env.sh')" 2>/dev/null || true
    if [ -f /tmp/dynamic_env.sh ]; then
        # shellcheck disable=SC1090
        source /tmp/dynamic_env.sh
        echo "[Info] Configuraciones remotas cargadas exitosamente en el entorno del contenedor."
    fi

    # 2. Bot de Telegram para Clientes (Ventas / Pedidos Mazatlán)
    if [ -n "$TELEGRAM_BOT_TOKEN" ] || [ -n "$API_BASE_URL" ]; then
        echo "[2/4] Iniciando Bot de Telegram para Clientes (Mazatlán)..."
        python telegram_bot.py &
        TELEGRAM_PID=$!
    else
        echo "[2/4] TELEGRAM_BOT_TOKEN no configurado (omitido)."
    fi

    # 3. Bot de Telegram para Choferes (Despacho / GPS)
    if [ -n "$DRIVER_BOT_TOKEN" ] || [ -n "$TELEGRAM_DRIVER_BOT_TOKEN" ] || [ -n "$API_BASE_URL" ]; then
        echo "[3/4] Iniciando Bot de Telegram para Choferes..."
        python driver_bot.py &
        DRIVER_PID=$!
    else
        echo "[3/4] TELEGRAM_DRIVER_BOT_TOKEN no configurado (omitido)."
    fi

    # 4. Bot de Telegram para Gascytsa (Culiacán)
    echo "[4/4] Iniciando Bot de Telegram Gascytsa (Culiacán)..."
    python telegram_bot_gascytsa.py &
    GASCYTSA_PID=$!

    # Manejar señales de apagado limpio
    trap "echo 'Deteniendo servicios...'; kill -TERM ${API_PID:-} ${TELEGRAM_PID:-} ${DRIVER_PID:-} ${GASCYTSA_PID:-} 2>/dev/null || true; exit 0" SIGTERM SIGINT

    # Mantener el contenedor vivo mientras corra la API principal
    wait "$API_PID"
    exit $?
fi

# Si se pasó otro comando manual, ejecutarlo
exec "$@"
