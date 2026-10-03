import sys
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# Forzar UTF-8 en terminal de Windows para emojis y caracteres especiales
if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure root directory is on sys.path when running src/app.py directly
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.config.settings import get_settings
from src.channels.web.router import router as web_router
from src.channels.whatsapp.router import router as whatsapp_router
from src.channels.telegram.router import router as telegram_router
from src.channels.instagram.router import router as instagram_router
from src.channels.messenger.router import router as messenger_router
from src.admin.router import router as admin_router
from src.tracking.router import router as tracking_router

app = FastAPI(title="Multi-Channel Sales Agent & Petroil Backoffice")

# Configuración de CORS segura y configurable
settings = get_settings()
raw_cors = settings.cors_origins.strip()
allowed_origins = ["*"] if raw_cors == "*" else [o.strip() for o in raw_cors.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# Static files for Admin Backoffice
ADMIN_STATIC_DIR = Path(__file__).parent / "admin" / "static"
if ADMIN_STATIC_DIR.exists():
    app.mount("/static/admin", StaticFiles(directory=ADMIN_STATIC_DIR), name="admin_static")

# Uploaded media (Tank readings photos, proof of delivery, etc.)
UPLOADS_DIR = Path(__file__).parent.parent / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
(UPLOADS_DIR / "tank_readings").mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

# Admin Backoffice routes (/admin and /api/admin/...)
app.include_router(admin_router, prefix="")

# Web endpoints at root (for the Sales Studio)
app.include_router(web_router, prefix="")

# Tracking endpoints (/tracking/{order_id} and /api/tracking/{order_id})
app.include_router(tracking_router, prefix="")

# Webhooks
app.include_router(whatsapp_router, prefix="/webhooks/whatsapp")
app.include_router(whatsapp_router, prefix="/webhook")
app.include_router(messenger_router, prefix="/webhooks/messenger")
app.include_router(messenger_router, prefix="/webhook/messenger")
app.include_router(telegram_router, prefix="/webhooks/telegram")
app.include_router(instagram_router, prefix="/webhooks/instagram")
app.include_router(instagram_router, prefix="/webhook/instagram")

# Dynamic Settings Synchronization Endpoint (Dashboard webhook or manual trigger)
@app.api_route("/api/settings/sync", methods=["GET", "POST"])
async def sync_platform_settings():
    """Forces synchronization of platform settings from the central NestJS backend."""
    from src.services.dynamic_settings import fetch_remote_settings, invalidate_dynamic_settings_cache
    invalidate_dynamic_settings_cache()
    synced = fetch_remote_settings(force_refresh=True)
    masked = {}
    for k, v in synced.items():
        if len(v) > 10:
            masked[k] = f"{v[:6]}...{v[-4:]}"
        else:
            masked[k] = "***"
    return {
        "status": "ok",
        "message": f"Successfully synchronized {len(synced)} settings from dashboard.",
        "synced_keys": masked,
    }


# Background PWA Driver Orders & GPS Synchronizer
@app.on_event("startup")
async def on_startup():
    """Start background synchronization workers on server startup."""
    from src.services.pwa_sync_service import start_pwa_sync_service
    start_pwa_sync_service(interval_seconds=4.0, tenant_id="petroil")


@app.on_event("shutdown")
async def on_shutdown():
    """Stop background workers gracefully on server shutdown."""
    from src.services.pwa_sync_service import stop_pwa_sync_service
    stop_pwa_sync_service()


@app.get("/api/pwa/sync")
async def manual_pwa_sync():
    """Manual trigger to poll and synchronize PWA driver order updates."""
    from src.services.pwa_sync_service import poll_order_updates_once
    events = await poll_order_updates_once(tenant_id="petroil")
    return {"status": "ok", "events_fired": events}


if __name__ == "__main__":
    import uvicorn
    print("🚀 Sales Agent & Admin Backoffice starting on http://localhost:3000")
    print("👉 Backoffice Administrativo: http://localhost:3000/admin")
    uvicorn.run("src.app:app", host="0.0.0.0", port=3000, reload=False)
