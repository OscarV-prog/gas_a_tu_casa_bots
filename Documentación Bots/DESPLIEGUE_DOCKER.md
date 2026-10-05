# Guía Rápida: Despliegue con Docker

Esta configuración orquesta **todo el sistema de bots en un solo contenedor Docker**:
1. **API FastAPI (Puerto 3000):** Maneja los Webhooks de Meta Messenger, la sincronización de la PWA del Chofer y la página de Tracking del cliente.
2. **Bot de Telegram Clientes:** Atiende pedidos de venta por Telegram (usando `TELEGRAM_BOT_TOKEN`).
3. **Bot de Telegram Choferes:** Atiende despacho y coordenadas por Telegram (usando `DRIVER_BOT_TOKEN`).

---

## 1. Despliegue en el Servidor con Docker Compose (Recomendado)

En el servidor, dentro de la carpeta del proyecto clonado:

1. Asegúrate de tener el archivo `.env` configurado con los tokens y variables.
2. Ejecuta un solo comando:
```bash
docker compose up -d --build
```

### Comandos útiles:
- **Ver logs en tiempo real:**
  ```bash
  docker compose logs -f
  ```
- **Ver estado del contenedor:**
  ```bash
  docker compose ps
  ```
- **Reiniciar el servicio:**
  ```bash
  docker compose restart
  ```
- **Detener el servicio:**
  ```bash
  docker compose down
  ```

---

## 2. Despliegue con Docker CLI directo (Alternativa)

Si prefieres construir y correr la imagen manualmente sin Docker Compose:

1. **Construir la imagen:**
   ```bash
   docker build -t gas-a-tu-casa-bots .
   ```

2. **Ejecutar el contenedor:**
   ```bash
   docker run -d \
     --name gas_a_tu_casa_bots \
     --restart always \
     -p 3000:3000 \
     --env-file .env \
     -v $(pwd)/data:/app/data \
     -v $(pwd)/petroil.db:/app/petroil.db \
     gas-a-tu-casa-bots
   ```
