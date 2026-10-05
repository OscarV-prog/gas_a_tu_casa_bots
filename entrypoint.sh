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

    # 2. Bot de Telegram para Clientes (Ventas / Pedidos)
    if [ -n "$TELEGRAM_BOT_TOKEN" ] || [ -n "$API_BASE_URL" ]; then
        echo "[2/3] Iniciando Bot de Telegram para Clientes..."
        python telegram_bot.py &
        TELEGRAM_PID=$!
    else
        echo "[2/3] TELEGRAM_BOT_TOKEN / API_BASE_URL no configurado (omitido)."
    fi

    # 3. Bot de Telegram para Choferes (Despacho / GPS)
    if [ -n "$DRIVER_BOT_TOKEN" ] || [ -n "$TELEGRAM_DRIVER_BOT_TOKEN" ] || [ -n "$API_BASE_URL" ]; then
        echo "[3/3] Iniciando Bot de Telegram para Choferes..."
        python driver_bot.py &
        DRIVER_PID=$!
    else
        echo "[3/3] DRIVER_BOT_TOKEN / API_BASE_URL no configurado (omitido)."
    fi

    # Manejar señales de apagado limpio
    trap "echo 'Deteniendo servicios...'; kill -TERM $API_PID $TELEGRAM_PID $DRIVER_PID 2>/dev/null; exit 0" SIGTERM SIGINT

    # Mantener el contenedor vivo mientras corran los servicios
    wait -n
    exit $?
fi

# Si se pasó otro comando manual, ejecutarlo
exec "$@"
