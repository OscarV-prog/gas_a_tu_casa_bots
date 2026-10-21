"""
Herramienta de restauración interactiva para el Bot de WhatsApp.
Permite seleccionar cualquiera de los respaldos disponibles en la carpeta backups/
y restaurarlo directamente sobre el proyecto.
"""

import os
import shutil
import sys
import glob

if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def main():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    backups_dir = os.path.join(root_dir, "backups")

    print("=========================================================")
    print("  🔄 RESTAURADOR DEL BOT DE WHATSAPP (METAPROTOCOL)     ")
    print("=========================================================")

    # Buscar respaldos de WhatsApp disponibles
    whatsapp_dirs = sorted(glob.glob(os.path.join(backups_dir, "backup_whatsapp_2*")), reverse=True)

    if not whatsapp_dirs:
        print("❌ No se encontraron respaldos de WhatsApp en:", backups_dir)
        return

    print("Respaldos de WhatsApp encontrados:")
    for idx, path in enumerate(whatsapp_dirs, 1):
        name = os.path.basename(path)
        print(f"  [{idx}] {name}")

    selected_idx = 1
    if len(whatsapp_dirs) > 1:
        try:
            choice = input(f"Selecciona un respaldo para restaurar (1-{len(whatsapp_dirs)}) [1 por defecto]: ").strip()
            if choice:
                selected_idx = int(choice)
        except Exception:
            selected_idx = 1

    selected_backup = whatsapp_dirs[selected_idx - 1]
    print(f"\nHas seleccionado: {os.path.basename(selected_backup)}")
    confirm = input("¿Confirmas restaurar esta versión sobre el código actual? (s/N): ").strip().lower()

    if confirm not in ('s', 'si', 'y', 'yes'):
        print("Restauración cancelada.")
        return

    exclude_files = {'restaurar_whatsapp.py', 'INSTRUCCIONES_RESTAURAR_WHATSAPP.md', 'checksums.sha256'}
    restored_count = 0

    for root, dirs, files in os.walk(selected_backup):
        rel_root = os.path.relpath(root, selected_backup)
        for f in files:
            if f in exclude_files:
                continue
            src_f = os.path.join(root, f)
            rel_path = os.path.normpath(os.path.join(rel_root, f))
            if rel_path.startswith("."):
                rel_path = rel_path[1:].lstrip("/\\\\")
            dst_f = os.path.join(root_dir, rel_path)
            os.makedirs(os.path.dirname(dst_f), exist_ok=True)
            shutil.copy2(src_f, dst_f)
            restored_count += 1
            print(f"  ✓ Restaurado: {rel_path}")

    print("---------------------------------------------------------")
    print(f"✅ ¡Restauración completada con éxito! ({restored_count} archivos restaurados).")
    print("=========================================================")

if __name__ == "__main__":
    main()
