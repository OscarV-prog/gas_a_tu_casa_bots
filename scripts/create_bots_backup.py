"""
Script to create a complete and clean backup of all bot code:
- Telegram bots (telegram_bot.py, telegram_bot_test.py, telegram_bot_gascytsa.py, driver_bot.py, src/channels/telegram/)
- Meta bots:
  - WhatsApp Cloud API (src/channels/whatsapp/)
  - Facebook Messenger (src/channels/messenger/)
  - Instagram Direct (src/channels/instagram/)
- Core Shared Bot Engine (src/services/flow_router.py, src/repositories, src/models, src/admin, etc.)
- FastAPI Webhook Server (main.py, src/app.py)
- Tenant configurations (tenants/)
- Integration tests (tests/)
- Essential configurations & deployment files (pyproject.toml, requirements.txt, Dockerfile, etc.)
- Technical documentation (bot_integration_guide.md, CHECKLIST_CONFIGURACION_BOTS.md, etc.)
"""

import os
import shutil
import zipfile
import datetime
import hashlib

def should_exclude(rel_path, filename):
    lower_path = rel_path.lower().replace('\\', '/')
    lower_name = filename.lower()

    # Ignore folders
    excluded_dirs = {
        '.venv', 'venv', '.git', '__pycache__', '.pytest_cache',
        '.langgraph', 'data', 'uploads', 'backups', 'scratch',
        '.gemini', '.agent', '.claude', 'lib', 'scripts'
    }
    for part in lower_path.split('/'):
        if part in excluded_dirs:
            return True

    # Ignore file extensions
    excluded_exts = ('.pyc', '.pyo', '.pyd', '.db', '.sqlite', '.sqlite3', '.log', '.tmp', '.lock')
    if lower_name.endswith(excluded_exts):
        return True

    # Ignore specific files
    if lower_name in ('.env', 'channel_identity_cache.json', 'cachedir.tag'):
        return True

    return False

def make_backup():
    root_dir = os.path.abspath(os.getcwd())
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_base_name = f"backup_bots_{timestamp}"
    backups_dir = os.path.join(root_dir, "backups")
    backup_folder = os.path.join(backups_dir, backup_base_name)
    backup_zip = os.path.join(backups_dir, f"{backup_base_name}.zip")
    latest_zip = os.path.join(backups_dir, "backup_bots_latest.zip")

    os.makedirs(backup_folder, exist_ok=True)

    copied_files = []
    total_bytes = 0

    print(f"Iniciando respaldo en: {backup_folder}")

    # Specific folders and files to include
    targets = [
        "src",
        "tenants",
        "tests",
        "Documentación",
        "Documentación Bots",
        "telegram_bot_test.py",
        "telegram_bot.py",
        "telegram_bot_gascytsa.py",
        "driver_bot.py",
        "main.py",
        "graph.py",
        "reset_db.py",
        "test_api.py",
        "test_optimization_scenarios.py",
        "view_api_db.py",
        "view_db.py",
        "entrypoint.sh",
        "requirements.txt",
        "pyproject.toml",
        ".env.example",
        "Dockerfile",
        "docker-compose.yml",
        ".dockerignore",
        ".gitignore",
        "bot_integration_guide.md",
        "CHECKLIST_CONFIGURACION_BOTS.md",
        "DOCUMENTACION_COMPLETA_BOTS_USUARIO.md",
        "DOCUMENTACION_COMPLETA_PROYECTO.md",
        "LOGICA_PROGRAMACION_PEDIDOS.md",
        "CONTEXTO_SISTEMA_PETROGAS.md",
        "README.md",
        "LICENSE"
    ]

    for target in targets:
        src_path = os.path.join(root_dir, target)
        if not os.path.exists(src_path):
            continue

        if os.path.isfile(src_path):
            filename = os.path.basename(src_path)
            if not should_exclude(target, filename):
                dst_path = os.path.join(backup_folder, target)
                os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                shutil.copy2(src_path, dst_path)
                fsize = os.path.getsize(dst_path)
                total_bytes += fsize
                copied_files.append((target, fsize))
        else:
            for dirpath, dirnames, filenames in os.walk(src_path):
                # Filter out excluded directory names in-place
                dirnames[:] = [d for d in dirnames if not should_exclude(os.path.relpath(os.path.join(dirpath, d), root_dir), d)]
                for fname in filenames:
                    rel_f = os.path.relpath(os.path.join(dirpath, fname), root_dir)
                    if should_exclude(rel_f, fname):
                        continue
                    full_src = os.path.join(dirpath, fname)
                    full_dst = os.path.join(backup_folder, rel_f)
                    os.makedirs(os.path.dirname(full_dst), exist_ok=True)
                    shutil.copy2(full_src, full_dst)
                    fsize = os.path.getsize(full_dst)
                    total_bytes += fsize
                    copied_files.append((rel_f, fsize))

    # Create README_BACKUP.md inside the backup folder
    manifest_path = os.path.join(backup_folder, "README_BACKUP.md")
    manifest_content = f"""# Copia de Seguridad - Código de Bots Multi-Plataforma
**Fecha y Hora de Generación:** {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**Total de Archivos:** {len(copied_files)}
**Tamaño Descomprimido:** {total_bytes / (1024 * 1024):.2f} MB

---

## 1. Contenido y Canales Respaldados

### 🤖 Bots de Telegram
- `telegram_bot_test.py`: Bot de pruebas Gasskywalker (`@gasskywalker_bot`), con las últimas mejoras de selección y edición de direcciones, limitación geográfica a Mazatlán, botones de regresar y navegación en perfil y pedido.
- `telegram_bot.py`: Bot principal de Telegram para la marca Petroil.
- `telegram_bot_gascytsa.py`: Bot de Telegram para la marca Gas Cytsa.
- `driver_bot.py`: Bot para repartidores/choferes (recepción de pedidos y telemetría en tiempo real).
- `src/channels/telegram/`: Adaptador y router de Telegram para la API de FastAPI.

### 🌐 Bots de Meta
- **WhatsApp Cloud API**:
  - `src/channels/whatsapp/adapter.py`: Serialización de mensajes, botones interactivos, listas, ubicación y cards de pedidos.
  - `src/channels/whatsapp/router.py`: Webhooks de entrada (`GET`/`POST`) y validación de tokens.
  - Pruebas: `tests/test_whatsapp_webhook.py`, `tests/test_whatsapp_extra_features.py`.
- **Facebook Messenger**:
  - `src/channels/messenger/adapter.py`: Plantillas genéricas, carruseles de productos/direcciones, quick replies y postbacks.
  - `src/channels/messenger/router.py`: Verificación de firma SHA256 y webhooks de Messenger.
  - Pruebas: `tests/test_messenger_addresses.py`, `tests/test_messenger_carousel_lifecycle.py`, `tests/test_messenger_updates.py`.
- **Instagram Direct**:
  - `src/channels/instagram/adapter.py`: Adaptador de mensajería para Instagram Direct vía Meta Graph API.
  - `src/channels/instagram/router.py`: Webhook y enrutamiento de mensajes de Instagram.
  - Pruebas: `tests/test_instagram_channel.py`.

### 🧠 Motor Central y Lógica de Negocio Compartida
- `src/services/flow_router.py`: Máquina de estados conversacional y enrutador universal que atiende a Telegram, WhatsApp, Messenger e Instagram.
- `src/repositories/`:
  - `api_repo.py`: Conexión con el backend central (NestJS / PostgreSQL).
  - `sqlite_repo.py`: Base de datos local / de contingencia.
  - `identity_store.py`: Mapeo de identidad omnicanal para usuarios entre plataformas.
- `src/models/`: Modelos de datos unificados (`order.py`, `customer.py`, `account.py`, `state.py`).
- `tenants/`: Configuraciones multitenant (`petroil`, `gascytsa`, etc.).
- `main.py`: Servidor central FastAPI donde se montan todos los routers de Meta y Telegram.

---

## 2. Instrucciones de Restauración y Ejecución

1. **Crear entorno virtual**:
   ```bash
   python -m venv .venv
   # En Windows:
   .\\.venv\\Scripts\\activate
   # En Linux/macOS:
   source .venv/bin/activate
   ```
2. **Instalar dependencias**:
   ```bash
   pip install -r requirements.txt
   ```
3. **Configurar variables de entorno**:
   Copiar `.env.example` a `.env` y configurar tokens de Telegram y Meta.
4. **Ejecutar Bots**:
   - **Telegram**: `python telegram_bot_test.py` o `python telegram_bot.py`
   - **Servidor Webhooks Meta (WhatsApp/Messenger/Instagram)**: `uvicorn main:app --host 0.0.0.0 --port 8000`
"""
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(manifest_content)

    print(f"Manifest creado en: {manifest_path}")

    # Create ZIP archive
    print(f"Comprimiendo respaldo en: {backup_zip}")
    with zipfile.ZipFile(backup_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(backup_folder):
            for file in files:
                file_full = os.path.join(root, file)
                file_rel = os.path.relpath(file_full, backup_folder)
                zipf.write(file_full, file_rel)

    # Copy as latest zip
    shutil.copy2(backup_zip, latest_zip)

    zip_size = os.path.getsize(backup_zip)
    print("\n================ RESUMEN DE RESPALDO ================")
    print(f"Directorio: {backup_folder}")
    print(f"Archivo ZIP: {backup_zip}")
    print(f"Archivo ZIP Último: {latest_zip}")
    print(f"Archivos copiados: {len(copied_files) + 1}")
    print(f"Tamaño sin comprimir: {total_bytes / (1024 * 1024):.2f} MB")
    print(f"Tamaño archivo ZIP: {zip_size / (1024 * 1024):.2f} MB")
    print("=====================================================")

if __name__ == "__main__":
    make_backup()
