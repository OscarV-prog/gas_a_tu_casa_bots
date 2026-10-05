# Arquitectura de Puentes, Webhooks y Guía de Despliegue en Servidor

Este documento describe la arquitectura técnica de comunicación ("puentes"), el flujo de webhooks entre plataformas de mensajería (Meta Messenger, Telegram, PWA Chofer) y los requerimientos de infraestructura necesarios para alojar el servicio en un servidor productivo con disponibilidad 24/7.

---

## 1. Contexto y Arquitectura Actual de los "Puentes"

El núcleo de los bots opera sobre un servidor backend en **FastAPI (Python 3.11+)** escuchando por defecto en el puerto **`3000`** (`http://localhost:3000`).

```
                              ┌──────────────────────────────────────────┐
                              │           PLATAFORMAS EXTERNAS           │
                              └──────────────────────────────────────────┘
                                   │                              │
                     (Mensajes / Webhooks)            (Mensajes / Polling)
                                   ▼                              ▼
                        [ Meta Messenger API ]            [ Telegram API ]
                                   │                              │
                                   │ HTTPS                        │ HTTPS
                                   ▼                              ▼
               ┌──────────────────────────────────────────────────────────────┐
               │              PUERTO PÚBLICO / PROXY INVERSO                  │
               │   (Dominio con SSL: https://<dominio>/webhooks/messenger)    │
               └──────────────────────────────────────────────────────────────┘
                                              │
                                              ▼ (Proxy interno HTTP)
               ┌──────────────────────────────────────────────────────────────┐
               │           BACKEND FASTAPI (PYTHON) - PUERTO 3000             │
               │  - Validación de Webhooks (GET /webhooks/messenger)          │
               │  - Recepción de Mensajes  (POST /webhooks/messenger)         │
               │  - Motor de Tracking      (GET /tracking/{order_id})         │
               │  - API Sincronización PWA (POST /api/pwa/sync-order)         │
               │  - Dispatcher & Estados   (src/app.py)                       │
               └──────────────────────────────────────────────────────────────┘
                                       │                      │
                                       ▼                      ▼
                           [ PWA Chofer / GPS ]       [ ERP / NestJS API ]
```

### Endpoints y Canales Expuestos:
1. **Webhook de Meta Messenger:**
   - **`GET /webhooks/messenger`**: Endpoint de verificación exigido por Meta. Recibe `hub.mode=subscribe`, `hub.verify_token` y responde con `hub.challenge`.
   - **`POST /webhooks/messenger`**: Endpoint que recibe en tiempo real los mensajes entrantes de los usuarios y las respuestas de botones/quick replies.
2. **Servicio de Seguimiento y Tracking Web:**
   - **`GET /tracking/{order_id}`**: Interfaz web dinámica que muestra al cliente el estatus de su pedido, mapa interactivo con la geolocalización del chofer y calificación final.
3. **Integración con PWA Chofer:**
   - Endpoints para notificar asignación de chofer, orden en ruta, actualización de coordenadas GPS y entrega completada con disparo de encuesta de satisfacción.
4. **Bots de Telegram:**
   - Servicios auxiliares (`telegram_bot.py` y `driver_bot.py`) para interacción de clientes y conductores.

---

## 2. Diagnóstico: Causa de Desconexión en Ambiente Local

- **Mecanismo de prueba local:** Durante el desarrollo local, el puerto `3000` se expuso a Internet mediante un túnel temporal de Cloudflare (`cloudflared tunnel`).
- **Problema de disponibilidad:** Dicho túnel depende de la estación de trabajo local. Al suspenderse, cerrarse la sesión o apagarse la máquina, el túnel y el proceso mueren inmediatamente, provocando que Meta marque el webhook como inalcanzable (Error de entrega / Timeout) y los bots queden fuera de línea.
- **Solución requerida:** Alojar el código de los bots directamente en el servidor productivo donde operan los demás sistemas, corriendo bajo un administrador de procesos permanente (systemd, Docker o PM2).

---

## 3. Requerimientos de Infraestructura en Servidor

Para que el sistema funcione de manera continua y autónoma, se requiere habilitar en el servidor:

### A. Ejecución del Servicio Backend
- **Entorno:** Servidor Linux con Python 3.11+.
- **Código Fuente:** Clonar el repositorio del proyecto:
  ```bash
  git clone https://github.com/OscarV-prog/gas_a_tu_casa_bots.git
  cd gas_a_tu_casa_bots
  ```
- **Instalación de dependencias:**
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
  ```
- **Comando de arranque (FastAPI):**
  ```bash
  uvicorn src.app:app --host 0.0.0.0 --port 3000
  ```

---

## 4. Opciones de Enrutamiento de Red (Proxy Inverso)

Para que Meta Messenger y los clientes externos puedan alcanzar el puerto `3000` con certificado SSL válido (HTTPS requerido obligatoriamente por Meta), se puede implementar cualquiera de las siguientes alternativas:

### Opción 1: Subdominio Dedicado (Recomendada)
Crear un subdominio específico (por ejemplo `bots.petroil.dev` o `api-bots.petroil.dev`) apuntando directamente al servidor, con terminación SSL (Nginx / Caddy / Cloudflare) redirigiendo todo el tráfico al puerto `3000`.

**Configuración Nginx sugerida para subdominio:**
```nginx
server {
    listen 443 ssl http2;
    server_name bots.petroil.dev;

    ssl_certificate /etc/letsencrypt/live/bots.petroil.dev/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/bots.petroil.dev/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

### Opción 2: Enrutamiento por Ruta en el Dominio Existente
Si se utiliza el dominio principal actual (por ejemplo `https://petrogas.petroil.dev/`), se deben añadir reglas de proxy inverso en Nginx para que las rutas del bot no caigan en la Single Page Application (SPA / Nuxt):

```nginx
# Enrutamiento de Webhooks hacia el backend de los bots
location /webhooks/ {
    proxy_pass http://127.0.0.1:3000/webhooks/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

# Enrutamiento de la pantalla de Tracking y mapa
location /tracking/ {
    proxy_pass http://127.0.0.1:3000/tracking/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

---

### Opción 3: Cloudflare Tunnel Persistente en Servidor
Si el servidor ya gestiona túneles de Cloudflare, se puede definir en el archivo `config.yml` del túnel:
```yaml
ingress:
  - hostname: bots.petroil.dev
    service: http://localhost:3000
  - service: http_status:404
```

---

## 5. Configuración de Variables de Entorno (`.env`)

En la raíz del proyecto en el servidor, crear el archivo `.env` con las credenciales requeridas:

```env
# URL Pública Base (URL con HTTPS donde responderá el bot externamente)
PUBLIC_BASE_URL=https://bots.petroil.dev

# Meta / Messenger API
MESSENGER_VERIFY_TOKEN=petroil_gas_webhook_secret
MESSENGER_PAGE_ACCESS_TOKEN=<PAGE_ACCESS_TOKEN>
MESSENGER_APP_SECRET=<APP_SECRET>

# Telegram API
TELEGRAM_BOT_TOKEN=<TELEGRAM_CLIENT_BOT_TOKEN>
DRIVER_BOT_TOKEN=<TELEGRAM_DRIVER_BOT_TOKEN>

# Inteligencia Artificial / LLM
GEMINI_API_KEY=<GEMINI_API_KEY>

# ERP / Backend API
NEXT_PUBLIC_API_URL=https://petrogas.petroil.dev
```

---

## 6. Parámetros para Meta for Developers (Webhooks)

Una vez habilitado el enrutamiento público en el servidor, los valores a registrar en el panel de **Meta for Developers > Messenger > Webhooks** son:

| Parámetro | Valor Configurado |
| :--- | :--- |
| **URL de devolución de llamada (Callback URL)** | `https://<DOMINIO_PUBLICO>/webhooks/messenger` |
| **Token de verificación (Verify Token)** | `petroil_gas_webhook_secret` |
| **Campos de suscripción requeridos** | `messages`, `messaging_postbacks`, `message_deliveries` |

---

## 7. Configuración como Servicio Persistente (`systemd`)

Para garantizar que el servicio se reinicie automáticamente ante fallos o reinicios del servidor:

Crear archivo `/etc/systemd/system/gas-bots.service`:
```ini
[Unit]
Description=Servicio de Bots y Webhooks Petroil
After=network.target

[Service]
User=www-data
WorkingDirectory=/var/www/gas_a_tu_casa_bots
ExecStart=/var/www/gas_a_tu_casa_bots/.venv/bin/uvicorn src.app:app --host 0.0.0.0 --port 3000
Restart=always
RestartSec=5
EnvironmentFile=/var/www/gas_a_tu_casa_bots/.env

[Install]
WantedBy=multi-user.target
```

Habilitar y arrancar el servicio:
```bash
sudo systemctl daemon-reload
sudo systemctl enable gas-bots
sudo systemctl start gas-bots
sudo systemctl status gas-bots
```
