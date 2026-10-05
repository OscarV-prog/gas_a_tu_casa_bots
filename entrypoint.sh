#!/bin/bash
set -e

# Si el comando es "all", levantamos todos los servicios de forma orquestada
if [ "$1" = "all" ]; then
    echo "========================================================="
    echo "  Iniciando Suite de Bots Gas a Tu Puerta (Docker)       "
    echo "========================================================="

    # 1. API FastAPI (Webhooks de Meta Messenger, PWA Sync, Tracking)
    echo "[1/3] Iniciando API FastAPI en http://0.0.0.0:3000..."
    uvicorn src.app:app --host 0.0.0.0 --port 3000 &
    API_PID=$!

    # Intentar sincronizar configuraciones remotas desde el backend central
    echo "[Info] Verificando configuraciones dinámicas desde el backend central..."
    python -c "from src.services.dynamic_settings import fetch_remote_settings; fetch_remote_settings(force_refresh=True)" 2>/dev/null || true

    # 2. Bot de Telegram para Clientes (Ventas / Pedidos)
    HAS_CLIENT_TOKEN=$(python -c "import os; from src.config.settings import get_settings; print('1' if (os.getenv('TELEGRAM_BOT_TOKEN') or get_settings().telegram_bot_token) else '0')" 2>/dev/null || echo "0")
    if [ "$HAS_CLIENT_TOKEN" = "1" ]; then
        echo "[2/3] Iniciando Bot de Telegram para Clientes..."
        python telegram_bot.py &
        TELEGRAM_PID=$!
    else
        echo "[2/3] TELEGRAM_BOT_TOKEN no configurado en .env ni en el backend (omitido)."
    fi

    # 3. Bot de Telegram para Choferes (Despacho / GPS)
    HAS_DRIVER_TOKEN=$(python -c "import os; from src.config.settings import get_settings; s=get_settings(); print('1' if (os.getenv('TELEGRAM_DRIVER_BOT_TOKEN') or os.getenv('DRIVER_BOT_TOKEN') or s.telegram_driver_bot_token or s.telegram_bot_token) else '0')" 2>/dev/null || echo "0")
    if [ "$HAS_DRIVER_TOKEN" = "1" ]; then
        echo "[3/3] Iniciando Bot de Telegram para Choferes..."
        python driver_bot.py &
        DRIVER_PID=$!
    else
        echo "[3/3] TELEGRAM_DRIVER_BOT_TOKEN no configurado en .env ni en el backend (omitido)."
    fi

    # Manejar señales de apagado limpio
    trap "echo 'Deteniendo servicios...'; kill -TERM $API_PID $TELEGRAM_PID $DRIVER_PID 2>/dev/null; exit 0" SIGTERM SIGINT

    # Mantener el contenedor vivo mientras corra la API principal
    wait "$API_PID"
    exit $?
fi

# Si se pasó otro comando manual, ejecutarlo
exec "$@"
