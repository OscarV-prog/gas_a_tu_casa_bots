#!/bin/bash
set -e

echo "====================================================="
echo "  🚀 Desplegando actualización de Gas a tu Casa Bots "
echo "====================================================="

# 1. Descargar los últimos cambios desde GitHub
echo "📥 [1/4] Descargando últimos cambios desde GitHub..."
git pull origin main

# 2. Asegurar permisos en entrypoint.sh y scripts
chmod +x entrypoint.sh 2>/dev/null || true
chmod +x deploy.sh 2>/dev/null || true

# 3. Reconstruir la imagen de Docker sin caché e iniciar servicios
echo "🔨 [2/4] Reconstruyendo imagen de Docker con el código nuevo..."
docker compose down
docker compose build --no-cache
docker compose up -d

# 4. Limpiar imágenes huérfanas en desuso para cuidar espacio en disco
echo "🧹 [3/4] Limpiando imágenes residuales de Docker..."
docker image prune -f

# 5. Mostrar estado final
echo "✅ [4/4] ¡Despliegue completado con éxito!"
echo "-----------------------------------------------------"
docker compose ps
echo "-----------------------------------------------------"
echo "👉 Para monitorear los bots en vivo ejecuta:"
echo "   docker compose logs -f"
echo "====================================================="
