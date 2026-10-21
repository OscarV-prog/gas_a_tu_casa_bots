"""
Script especializado para generar una copia de seguridad completa del Bot de WhatsApp (Meta Cloud API).
Respalda:
1. Adaptador y Router de WhatsApp (src/channels/whatsapp/)
2. Base de Canales (src/channels/base.py)
3. Motor Conversacional y Enrutador Omnicanal (src/services/flow_router.py)
4. Servicios clave de soporte (notifications, geocoding, dynamic_settings, order_events, audio_transcription)
5. Repositorios y Modelos (src/repositories/, src/models/)
6. Servidor FastAPI y Rutas (src/app.py, main.py)
7. Configuraciones Multi-Tenant (tenants/)
8. Suite de pruebas de WhatsApp (tests/test_whatsapp_*.py)
9. Script automático de restauración (restaurar_whatsapp.py)
"""

import os
import shutil
import zipfile
import datetime
import hashlib
import sys

if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def get_file_sha256(filepath: str) -> str:
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()

def make_whatsapp_backup():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"backup_whatsapp_{timestamp}"
    backups_dir = os.path.join(root_dir, "backups")
    backup_folder = os.path.join(backups_dir, backup_name)
    backup_zip = os.path.join(backups_dir, f"{backup_name}.zip")
    latest_zip = os.path.join(backups_dir, "backup_whatsapp_latest.zip")

    os.makedirs(backup_folder, exist_ok=True)

    targets = [
        # WhatsApp Core & Base Channel
        "src/channels/whatsapp",
        "src/channels/base.py",
        # Motor y Servicios Omnicanal Completos
        "src/services",
        "src/repositories",
        "src/models",
        "src/tools",
        "src/admin",
        "src/tracking",
        "src/database",
        "src/graphs",
        "src/nodes",
        "src/state",
        # API Webhook de Meta (FastAPI)
        "src/app.py",
        "main.py",
        "src/config",
        # Multitenant
        "tenants",
        # Pruebas automatizadas de WhatsApp
        "tests/test_whatsapp_webhook.py",
        "tests/test_whatsapp_extra_features.py",
        "tests/test_channel_feature_parity.py",
        # Configuración del entorno y despliegue
        ".env.example",
        "requirements.txt",
        "pyproject.toml",
        "Dockerfile",
        "docker-compose.yml",
        "deploy.sh"
    ]

    copied_files = []
    total_bytes = 0

    print(f"📦 Iniciando copia de seguridad del Bot de WhatsApp en: {backup_folder}")

    for target in targets:
        src_path = os.path.join(root_dir, target)
        if not os.path.exists(src_path):
            print(f"⚠️ Aviso: no se encontró {target}, omitiendo...")
            continue

        if os.path.isfile(src_path):
            dst_path = os.path.join(backup_folder, target)
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            shutil.copy2(src_path, dst_path)
            fsize = os.path.getsize(dst_path)
            sha = get_file_sha256(dst_path)
            total_bytes += fsize
            copied_files.append((target, fsize, sha))
        else:
            for dirpath, dirnames, filenames in os.walk(src_path):
                # Filtrar directorios temporales o de compilación
                dirnames[:] = [d for d in dirnames if d not in ('__pycache__', '.pytest_cache')]
                for fname in filenames:
                    if fname.endswith(('.pyc', '.pyo', '.tmp')):
                        continue
                    full_src = os.path.join(dirpath, fname)
                    rel_f = os.path.relpath(full_src, root_dir)
                    full_dst = os.path.join(backup_folder, rel_f)
                    os.makedirs(os.path.dirname(full_dst), exist_ok=True)
                    shutil.copy2(full_src, full_dst)
                    fsize = os.path.getsize(full_dst)
                    sha = get_file_sha256(full_dst)
                    total_bytes += fsize
                    copied_files.append((rel_f, fsize, sha))

    # 1. Crear script automático de restauración dentro de la carpeta
    restore_script_content = """#!/usr/bin/env python3
\"\"\"Script de restauración automática del respaldo de WhatsApp.\"\"\"
import os
import shutil
import sys

def restore():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(script_dir, "..", ".."))

    print("=========================================================")
    print("  ⚠️ RESTAURACIÓN DEL BOT DE WHATSAPP DESDE RESPALDO")
    print("=========================================================")
    print(f"Origen respaldo: {script_dir}")
    print(f"Destino (Proyecto): {project_root}")
    print("---------------------------------------------------------")

    confirm = input("¿Estás seguro de sobrescribir los archivos del bot de WhatsApp? (s/N): ").strip().lower()
    if confirm not in ('s', 'si', 'y', 'yes'):
        print("Restauración cancelada.")
        return

    exclude_files = {'restaurar_whatsapp.py', 'INSTRUCCIONES_RESTAURAR_WHATSAPP.md', 'checksums.sha256'}
    restored_count = 0

    for root, dirs, files in os.walk(script_dir):
        rel_root = os.path.relpath(root, script_dir)
        for f in files:
            if f in exclude_files:
                continue
            src_f = os.path.join(root, f)
            rel_path = os.path.normpath(os.path.join(rel_root, f))
            if rel_path.startswith("."):
                rel_path = rel_path[1:].lstrip("/\\\\")
            dst_f = os.path.join(project_root, rel_path)
            os.makedirs(os.path.dirname(dst_f), exist_ok=True)
            shutil.copy2(src_f, dst_f)
            restored_count += 1
            print(f"  ✓ Restaurado: {rel_path}")

    print("---------------------------------------------------------")
    print(f"✅ Se restauraron exitosamente {restored_count} archivos del Bot de WhatsApp.")
    print("=========================================================")

if __name__ == '__main__':
    restore()
"""
    restore_script_path = os.path.join(backup_folder, "restaurar_whatsapp.py")
    with open(restore_script_path, "w", encoding="utf-8") as f:
        f.write(restore_script_content)

    # 2. Crear archivo de checksums
    checksum_path = os.path.join(backup_folder, "checksums.sha256")
    with open(checksum_path, "w", encoding="utf-8") as f:
        for fpath, fsize, sha in copied_files:
            f.write(f"{sha}  {fpath}\n")

    # 3. Crear INSTRUCCIONES_RESTAURAR_WHATSAPP.md
    instructions_content = f"""# Respaldo Oficial del Bot de WhatsApp (Meta Cloud API)
**Fecha y Hora:** {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**Identificador de Respaldo:** `{backup_name}`
**Total de Archivos:** {len(copied_files)}
**Tamaño Total:** {total_bytes / (1024 * 1024):.2f} MB

---

## 📋 ¿Qué contiene esta copia de seguridad?

1. **Canal WhatsApp Oficial**:
   - `src/channels/whatsapp/adapter.py`: Formateo de plantillas, botones de respuesta rápida, listas interactivas, carruseles de pedidos, manejo de ubicaciones GPS, notas de voz y encuestas de calidad.
   - `src/channels/whatsapp/router.py`: Webhooks de verificación de Meta (`hub.challenge`), recepción y procesamiento de eventos de mensajería entrantes.
2. **Motor de Conversación Omnicanal**:
   - `src/services/flow_router.py`: Lógica conversacional, validación de domicilios, cotización de gas y flujo completo de compra.
3. **Servicios Compartidos**:
   - `src/services/notifications.py`: Envío de notificaciones proactivas vía WhatsApp.
   - `src/services/dynamic_settings.py`: Resolución de credenciales Meta (`WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, etc.).
   - `src/services/geocoding.py` y `address_validator.py`: Normalización y delimitación de cobertura.
4. **Almacenamiento e Identidad**:
   - `src/repositories/`: Conexión con PostgreSQL / SQLite y tabla de mapeo de identidades de WhatsApp.
   - `src/models/`: Estructuras de datos de clientes y pedidos.
5. **Servidor API Webhook**:
   - `src/app.py` y `main.py`: Aplicación FastAPI que expone `/webhooks/whatsapp`.
6. **Pruebas de Validación**:
   - `tests/test_whatsapp_webhook.py` y `tests/test_whatsapp_extra_features.py`.

---

## 🔄 ¿Cómo Restaurar esta Versión si algo sale mal?

### Método 1: Restauración Automática con Python (Recomendado)
Desde la raíz del proyecto, ejecuta:
```bash
python backups/{backup_name}/restaurar_whatsapp.py
```
O usando `uv`:
```bash
uv run python backups/{backup_name}/restaurar_whatsapp.py
```

### Método 2: Restauración Manual desde el archivo ZIP
1. Descomprime `backups/{backup_name}.zip` (o `backups/backup_whatsapp_latest.zip`).
2. Copia las carpetas `src/`, `tenants/` y archivos correspondientes sobre la raíz de tu proyecto, reemplazando los existentes.

### Método 3: En el Servidor de Producción (Docker)
Si desplegaste cambios en tu servidor y necesitas regresar a esta versión:
1. Restaura los archivos en tu servidor usando el método 1 o 2.
2. Ejecuta:
   ```bash
   ./deploy.sh
   # o:
   docker compose up -d --build
   ```
"""
    instructions_path = os.path.join(backup_folder, "INSTRUCCIONES_RESTAURAR_WHATSAPP.md")
    with open(instructions_path, "w", encoding="utf-8") as f:
        f.write(instructions_content)

    # 4. Crear archivo ZIP comprimido
    print(f"🗜️ Comprimiendo respaldo en archivo ZIP: {backup_zip}")
    with zipfile.ZipFile(backup_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(backup_folder):
            for file in files:
                file_full = os.path.join(root, file)
                file_rel = os.path.relpath(file_full, backup_folder)
                zipf.write(file_full, file_rel)

    # 5. Copiar como respaldo más reciente (backup_whatsapp_latest.zip)
    shutil.copy2(backup_zip, latest_zip)

    zip_size = os.path.getsize(backup_zip)
    print("\n================ RESUMEN DE RESPALDO WHATSAPP ================")
    print(f"Carpeta: {backup_folder}")
    print(f"Archivo ZIP: {backup_zip}")
    print(f"Archivo Último ZIP: {latest_zip}")
    print(f"Archivos respaldados: {len(copied_files)}")
    print(f"Tamaño sin comprimir: {total_bytes / (1024 * 1024):.2f} MB")
    print(f"Tamaño ZIP: {zip_size / (1024 * 1024):.2f} MB")
    print("==============================================================")

if __name__ == "__main__":
    make_whatsapp_backup()
