"""Database schema definitions, migrations, and seeding for SQLite."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.config.settings import get_settings
from src.database.connection import get_db_connection


CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    channel_user_id TEXT NOT NULL,
    name TEXT,
    phone TEXT,
    address TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(tenant_id, channel, channel_user_id)
);

CREATE TABLE IF NOT EXISTS customer_addresses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    address TEXT NOT NULL,
    alias TEXT DEFAULT 'Principal',
    notes TEXT DEFAULT '',
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL DEFAULT 'petroil',
    unit_identifier TEXT NOT NULL,
    plate TEXT NOT NULL,
    model TEXT NOT NULL,
    vehicle_type TEXT NOT NULL DEFAULT 'camioneta',
    pipa_capacity_liters REAL,
    cylinder_capacity_count INTEGER,
    status TEXT NOT NULL DEFAULT 'active',
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS drivers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL DEFAULT 'petroil',
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    telegram_user_id TEXT UNIQUE,
    vehicle_id INTEGER REFERENCES vehicles(id) ON DELETE SET NULL,
    vehicle_type TEXT DEFAULT 'cilindros',
    vehicle_plate TEXT DEFAULT '',
    zone TEXT DEFAULT 'General',
    is_available INTEGER NOT NULL DEFAULT 1,
    current_lat REAL,
    current_lng REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    price REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'MXN',
    category TEXT NOT NULL DEFAULT '',
    image_url TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    in_stock INTEGER NOT NULL DEFAULT 1,
    is_promoted INTEGER NOT NULL DEFAULT 0,
    promotion_text TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
    customer_name TEXT NOT NULL,
    customer_phone TEXT NOT NULL,
    delivery_address TEXT NOT NULL,
    delivery_schedule TEXT NOT NULL DEFAULT 'Lo antes posible',
    total_amount REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'MXN',
    status TEXT NOT NULL DEFAULT 'confirmed',
    payment_method TEXT DEFAULT 'Efectivo',
    notes TEXT DEFAULT '',
    channel TEXT DEFAULT '',
    channel_user_id TEXT DEFAULT '',
    driver_id INTEGER REFERENCES drivers(id) ON DELETE SET NULL,
    delivery_lat REAL,
    delivery_lng REAL,
    live_location_message_id INTEGER,
    live_location_chat_id TEXT,
    driver_message_ids TEXT,
    assigned_at TEXT,
    delivered_at TEXT,
    scheduled_for TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id TEXT NOT NULL,
    product_name TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    unit_price REAL NOT NULL,
    subtotal REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS order_rejections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL DEFAULT 'petroil',
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    driver_id INTEGER REFERENCES drivers(id) ON DELETE SET NULL,
    driver_name TEXT NOT NULL,
    reason TEXT NOT NULL,
    is_resolved INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS driver_tank_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL DEFAULT 'petroil',
    driver_id INTEGER NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
    driver_name TEXT,
    vehicle_plate TEXT,
    reading_type TEXT NOT NULL, -- 'initial', 'final', 'refill'
    reading_value TEXT NOT NULL,
    photo_path TEXT,
    photo_telegram_id TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    shift_date TEXT NOT NULL DEFAULT (date('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS driver_shifts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL DEFAULT 'petroil',
    driver_id INTEGER NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
    driver_name TEXT,
    vehicle_plate TEXT,
    shift_date TEXT NOT NULL DEFAULT (date('now', 'localtime')),
    check_in_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    check_out_at TEXT,
    duration_minutes INTEGER,
    status TEXT NOT NULL DEFAULT 'active', -- 'active', 'completed'
    initial_reading TEXT,
    final_reading TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS order_ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL DEFAULT 'petroil',
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    driver_id INTEGER REFERENCES drivers(id) ON DELETE SET NULL,
    customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
    rating INTEGER NOT NULL CHECK(rating >= 1 AND rating <= 5),
    feedback_tag TEXT DEFAULT '',
    comment TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE(tenant_id, order_id)
);
"""

CREATE_INDICES_SQL = """
CREATE INDEX IF NOT EXISTS idx_products_tenant ON products(tenant_id);
CREATE INDEX IF NOT EXISTS idx_customers_lookup ON customers(tenant_id, channel, channel_user_id);
CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(tenant_id, phone);
CREATE INDEX IF NOT EXISTS idx_customer_addresses_cust ON customer_addresses(customer_id);
CREATE INDEX IF NOT EXISTS idx_drivers_tenant ON drivers(tenant_id);
CREATE INDEX IF NOT EXISTS idx_drivers_telegram ON drivers(telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_orders_tenant ON orders(tenant_id);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_driver ON orders(driver_id);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_rejections_order ON order_rejections(order_id);
CREATE INDEX IF NOT EXISTS idx_rejections_tenant ON order_rejections(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tank_readings_driver ON driver_tank_readings(driver_id);
CREATE INDEX IF NOT EXISTS idx_tank_readings_date ON driver_tank_readings(shift_date);
CREATE INDEX IF NOT EXISTS idx_tank_readings_tenant ON driver_tank_readings(tenant_id);
CREATE INDEX IF NOT EXISTS idx_driver_shifts_driver ON driver_shifts(driver_id);
CREATE INDEX IF NOT EXISTS idx_driver_shifts_date ON driver_shifts(shift_date);
CREATE INDEX IF NOT EXISTS idx_driver_shifts_tenant ON driver_shifts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_driver_shifts_status ON driver_shifts(status);
CREATE INDEX IF NOT EXISTS idx_order_ratings_order ON order_ratings(order_id);
CREATE INDEX IF NOT EXISTS idx_order_ratings_driver ON order_ratings(driver_id);
CREATE INDEX IF NOT EXISTS idx_order_ratings_tenant ON order_ratings(tenant_id);
CREATE INDEX IF NOT EXISTS idx_vehicles_tenant ON vehicles(tenant_id);
CREATE INDEX IF NOT EXISTS idx_vehicles_type ON vehicles(vehicle_type);
CREATE INDEX IF NOT EXISTS idx_vehicles_identifier ON vehicles(unit_identifier);
"""


def init_db() -> None:
    """Initialize database tables, run migrations, create indices, and auto-seed initial products and drivers only if SQLite is active."""
    import os
    if os.getenv("DATA_SOURCE", "api").lower().strip() != "sqlite":
        # SQLite está completamente desactivado; todo opera contra PostgreSQL
        return

    with get_db_connection() as conn:
        conn.executescript(CREATE_TABLES_SQL)

    migrate_orders_schema()
    migrate_drivers_schema()

    with get_db_connection() as conn:
        conn.executescript(CREATE_INDICES_SQL)

    migrate_customer_addresses()
    seed_products_from_json()
    seed_sample_vehicles()
    seed_sample_drivers()


def migrate_drivers_schema() -> None:
    """Add missing columns to drivers table if existing in older schema."""
    with get_db_connection() as conn:
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(drivers)").fetchall()]
        if "vehicle_id" not in columns:
            conn.execute("ALTER TABLE drivers ADD COLUMN vehicle_id INTEGER REFERENCES vehicles(id) ON DELETE SET NULL")



def migrate_orders_schema() -> None:
    """Add missing columns to orders table if existing in older schema."""
    with get_db_connection() as conn:
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(orders)").fetchall()]
        
        if "delivery_schedule" not in columns:
            conn.execute("ALTER TABLE orders ADD COLUMN delivery_schedule TEXT DEFAULT 'Lo antes posible'")
        if "driver_id" not in columns:
            conn.execute("ALTER TABLE orders ADD COLUMN driver_id INTEGER REFERENCES drivers(id) ON DELETE SET NULL")
        if "delivery_lat" not in columns:
            conn.execute("ALTER TABLE orders ADD COLUMN delivery_lat REAL")
        if "delivery_lng" not in columns:
            conn.execute("ALTER TABLE orders ADD COLUMN delivery_lng REAL")
        if "live_location_message_id" not in columns:
            conn.execute("ALTER TABLE orders ADD COLUMN live_location_message_id INTEGER")
        if "live_location_chat_id" not in columns:
            conn.execute("ALTER TABLE orders ADD COLUMN live_location_chat_id TEXT")
        if "assigned_at" not in columns:
            conn.execute("ALTER TABLE orders ADD COLUMN assigned_at TEXT")
        if "delivered_at" not in columns:
            conn.execute("ALTER TABLE orders ADD COLUMN delivered_at TEXT")
        if "scheduled_for" not in columns:
            conn.execute("ALTER TABLE orders ADD COLUMN scheduled_for TEXT")
        if "driver_message_ids" not in columns:
            conn.execute("ALTER TABLE orders ADD COLUMN driver_message_ids TEXT")


def migrate_customer_addresses() -> None:
    """Migrate legacy single addresses from customers table into customer_addresses table."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        customers = conn.execute("SELECT id, address, notes FROM customers WHERE address IS NOT NULL AND address != ''").fetchall()
        for c in customers:
            cust_id = c["id"]
            addr = c["address"].strip()
            notes = c["notes"] or ""
            if not addr:
                continue

            existing = conn.execute(
                "SELECT COUNT(*) as cnt FROM customer_addresses WHERE customer_id = ? AND address = ?",
                (cust_id, addr),
            ).fetchone()["cnt"]

            if existing == 0:
                total_addrs = conn.execute(
                    "SELECT COUNT(*) as cnt FROM customer_addresses WHERE customer_id = ?",
                    (cust_id,),
                ).fetchone()["cnt"]

                is_default = 1 if total_addrs == 0 else 0
                alias = "Principal" if is_default else f"Dirección {total_addrs + 1}"

                conn.execute(
                    """
                    INSERT INTO customer_addresses (
                        customer_id, address, alias, notes, is_default, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (cust_id, addr, alias, notes, is_default, now_iso, now_iso),
                )


def seed_products_from_json() -> None:
    """Auto-seed products table for tenants if their catalog is empty in SQLite."""
    settings = get_settings()
    tenants_dir = Path(settings.tenants_dir)
    if not tenants_dir.exists():
        return

    now_iso = datetime.now(timezone.utc).isoformat()

    with get_db_connection() as conn:
        for tenant_path in tenants_dir.iterdir():
            if not tenant_path.is_dir():
                continue
            tenant_id = tenant_path.name
            products_file = tenant_path / "products.json"
            if not products_file.exists():
                continue

            cur = conn.execute(
                "SELECT COUNT(*) AS cnt FROM products WHERE tenant_id = ?",
                (tenant_id,),
            )
            count = cur.fetchone()["cnt"]

            if count == 0:
                try:
                    with open(products_file, "r", encoding="utf-8") as f:
                        items = json.load(f)
                    
                    for item in items:
                        tags_json = json.dumps(item.get("tags", []), ensure_ascii=False)
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO products (
                                id, tenant_id, name, description, price, currency,
                                category, image_url, tags, in_stock, is_promoted,
                                promotion_text, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                item["id"],
                                tenant_id,
                                item["name"],
                                item.get("description", ""),
                                float(item.get("price", 0.0)),
                                item.get("currency", "MXN"),
                                item.get("category", ""),
                                item.get("image_url", ""),
                                tags_json,
                                1 if item.get("in_stock", True) else 0,
                                1 if item.get("is_promoted", False) else 0,
                                item.get("promotion_text", ""),
                                now_iso,
                            ),
                        )
                    print(f"📦 [SQLite] Auto-seeded {len(items)} products for tenant '{tenant_id}'.")
                except Exception as e:
                    print(f"⚠️ [SQLite] Error seeding products for '{tenant_id}': {e}")


def seed_sample_vehicles() -> None:
    """Auto-seed sample vehicles if vehicles table is empty."""
    now_iso = datetime.now(timezone.utc).isoformat()

    sample_vehicles = [
        {
            "unit_identifier": "CAM-04",
            "plate": "VZ-8472-A",
            "model": "Ford F-350 2022",
            "vehicle_type": "camioneta",
            "pipa_capacity_liters": None,
            "cylinder_capacity_count": 40,
            "notes": "Unidad de reparto de cilindros zona centro",
        },
        {
            "unit_identifier": "PIPA-02",
            "plate": "SIN-2023-E",
            "model": "Dodge Ram 4000 2023",
            "vehicle_type": "pipa",
            "pipa_capacity_liters": 5000.0,
            "cylinder_capacity_count": None,
            "notes": "Pipa para tanques estacionarios residenciales",
        },
        {
            "unit_identifier": "CAM-05",
            "plate": "VZ-3321-B",
            "model": "Chevrolet Silverado 3500 2021",
            "vehicle_type": "camioneta",
            "pipa_capacity_liters": None,
            "cylinder_capacity_count": 35,
            "notes": "Unidad de apoyo para cilindros",
        },
        {
            "unit_identifier": "PIPA-01",
            "plate": "SIN-5544-P",
            "model": "International 4300 2020",
            "vehicle_type": "pipa",
            "pipa_capacity_liters": 8000.0,
            "cylinder_capacity_count": None,
            "notes": "Pipa de gran capacidad para empresas y condominios",
        },
    ]

    with get_db_connection() as conn:
        count = conn.execute("SELECT COUNT(*) as cnt FROM vehicles WHERE tenant_id = 'petroil'").fetchone()["cnt"]
        if count == 0:
            for v in sample_vehicles:
                conn.execute(
                    """
                    INSERT INTO vehicles (
                        tenant_id, unit_identifier, plate, model, vehicle_type,
                        pipa_capacity_liters, cylinder_capacity_count, status, notes,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
                    """,
                    (
                        "petroil",
                        v["unit_identifier"],
                        v["plate"],
                        v["model"],
                        v["vehicle_type"],
                        v["pipa_capacity_liters"],
                        v["cylinder_capacity_count"],
                        v["notes"],
                        now_iso,
                        now_iso,
                    ),
                )
            print("[SQLite] Auto-seeded 4 sample fleet vehicles for Petroil.")


def seed_sample_drivers() -> None:
    """Auto-seed sample delivery drivers if drivers table is empty."""
    now_iso = datetime.now(timezone.utc).isoformat()

    sample_drivers = [
        {
            "name": "Juan Pérez (Unidad C-04)",
            "phone": "6691112233",
            "vehicle_type": "cilindros",
            "vehicle_plate": "C-04 (Cilindros)",
            "zone": "Centro / Malecón",
        },
        {
            "name": "Ramón Valdez (Pipa E-02)",
            "phone": "6692223344",
            "vehicle_type": "estacionario",
            "vehicle_plate": "E-02 (Pipa Estacionaria)",
            "zone": "Marina / Zona Dorada",
        },
        {
            "name": "Carlos Mendoza (Unidad Mixta M-01)",
            "phone": "6693334455",
            "vehicle_type": "ambos",
            "vehicle_plate": "M-01 (Mixto)",
            "zone": "Misiones / Real del Valle",
        },
    ]

    with get_db_connection() as conn:
        count = conn.execute("SELECT COUNT(*) as cnt FROM drivers WHERE tenant_id = 'petroil'").fetchone()["cnt"]
        if count == 0:
            for d in sample_drivers:
                conn.execute(
                    """
                    INSERT INTO drivers (
                        tenant_id, name, phone, vehicle_type, vehicle_plate, zone,
                        is_available, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        "petroil",
                        d["name"],
                        d["phone"],
                        d["vehicle_type"],
                        d["vehicle_plate"],
                        d["zone"],
                        now_iso,
                        now_iso,
                    ),
                )
            print("[SQLite] Auto-seeded 3 sample delivery drivers for Petroil.")
