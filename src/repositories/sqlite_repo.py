"""SQLite-backed repository for Products, Customers, Customer Addresses, Drivers, and Orders."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)

from src.database.connection import get_db_connection
from src.models.customer import Customer, CustomerAddress
from src.models.driver import Driver
from src.models.order import Order, OrderItem
from src.models.product import Product
from src.models.vehicle import Vehicle
from src.repositories.base import ProductRepository
from src.services.geocoding import resolve_gps_address_to_name, reverse_geocode

# Stemming suffixes for RU / EN / ES
_RU_SUFFIXES = (
    "ами", "ями", "ому", "ого", "ему", "его",
    "ов", "ев", "ей", "ий", "ый", "ой",
    "ам", "ям", "ах", "ях",
    "ы", "и", "а", "я", "у", "ю", "е", "о",
)
_EN_SUFFIXES = ("ing", "tion", "ies", "es", "ed", "ly", "er", "s")
_ES_SUFFIXES = ("ando", "iendo", "ados", "adas", "idos", "idas", "ción", "siones", "es", "as", "os", "a", "o", "s")
_MIN_STEM = 3


def _stem(word: str) -> str:
    """Suffix stripping for ES/RU/EN."""
    w = word.lower().strip()
    for sfx in _RU_SUFFIXES + _EN_SUFFIXES + _ES_SUFFIXES:
        if w.endswith(sfx) and len(w) - len(sfx) >= _MIN_STEM:
            return w[: -len(sfx)]
    return w


def _tokenize(text: str) -> set[str]:
    """Split text into stemmed tokens."""
    words = re.findall(r"[a-zA-ZáéíóúÁÉÍÓÚñÑа-яА-ЯёЁ0-9]+", text.lower())
    return {_stem(w) for w in words if len(w) >= 2}


def parse_schedule_deadline(schedule: str, ref_time: datetime | None = None) -> datetime | None:
    """Parse natural language Spanish delivery schedule into a target datetime.
    
    Understands:
    - 'Hoy a las 4:00 PM', 'Hoy 16:30', '4:00 PM', '17:00', 'a las 5 pm'
    - 'Mañana a las 10:00 AM', 'Mañana 11:30', 'Pasado mañana 9:00 am'
    - '2026-09-04 15:00', '2026-09-04T15:00:00', '2026-10-05T17:00:00.000Z'
    - Ignores 'Lo antes posible', 'Inmediato', 'Ahorita', 'Urgente' -> returns None.
    """
    if not schedule:
        return None
    s = schedule.strip().lower()
    if any(w in s for w in ["lo antes posible", "inmediato", "urgente", "ahorita", "ahora"]):
        return None

    if ref_time is None:
        ref_time = datetime.now()

    # 1. Try direct ISO format (including UTC Z and offsets)
    clean_iso = schedule.strip()
    if clean_iso.endswith("Z"):
        clean_iso = clean_iso[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(clean_iso)
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except Exception:
        pass

    for iso_fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(schedule.strip(), iso_fmt)
        except ValueError:
            pass

    # 2. Check day offset
    day_offset = 0
    is_explicit_today = bool(re.search(r'\b(?:hoy|el\s+d[ií]a\s+de\s+hoy)\b', s, re.I))
    if "pasado mañana" in s or "pasado manana" in s:
        day_offset = 2
    elif "mañana" in s or "manana" in s:
        day_offset = 1

    # Special mediodia / mediodía
    if "mediodia" in s or "mediodía" in s:
        target_date = ref_time.date() + timedelta(days=day_offset)
        return datetime.combine(target_date, datetime.min.time()).replace(hour=12, minute=0)

    # Contextual meridiem from phrases
    forced_pm = bool(re.search(r'\b(?:de\s+la|en\s+la|por\s+la)\s*(?:tarde|noche)\b', s, re.I))
    forced_am = bool(re.search(r'\b(?:de\s+la|en\s+la|por\s+la)\s*(?:mañana|manana)\b', s, re.I))

    # Match time expressions:
    hour, minute, meridiem = None, 0, None

    # 3a. Colon format: 5:30, 16:30, 4:00 pm, 5.30
    m_colon = re.search(r'\b(\d{1,2})[:\.](\d{2})\s*(am|pm|a\.m\.|p\.m\.)?\b', s, re.I)
    # 3b. Direct meridiem: 5 pm, 11 am, 5pm
    m_meridiem = re.search(r'\b(\d{1,2})\s*(am|pm|a\.m\.|p\.m\.)\b', s, re.I)
    # 3c. Spanish time phrase: '6 de la tarde', '11 de la mañana', '8 de la noche', '12 del dia'
    m_span_meridiem = re.search(r'\b(\d{1,2})(?::(\d{2}))?\s*(?:de\s+la|en\s+la|por\s+la|del)\s*(tarde|noche|mañana|manana|d[ií]a)\b', s, re.I)
    # 3d. Prefix with article: 'a las 5', 'para las 4', 'las 5', 'como a las 6', 'a la 1', 'la 1', 'tipo las 4'
    m_prefix = re.search(r'(?:(?:como\s+a|a\s+eso\s+de|tipo|alrededor\s+de|para|a)\s+)?(?:las?|la)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?', s, re.I)
    # 3e. Suffix: '17 hrs', '5 horas'
    m_suffix = re.search(r'\b(\d{1,2})\s*(?:hrs?|horas?)\b', s, re.I)

    if m_colon:
        hour = int(m_colon.group(1))
        minute = int(m_colon.group(2))
        meridiem = m_colon.group(3)
    elif m_meridiem:
        hour = int(m_meridiem.group(1))
        minute = 0
        meridiem = m_meridiem.group(2)
    elif m_span_meridiem:
        hour = int(m_span_meridiem.group(1))
        minute = int(m_span_meridiem.group(2)) if m_span_meridiem.group(2) else 0
        p_word = m_span_meridiem.group(3).lower()
        if "tarde" in p_word or "noche" in p_word:
            meridiem = "pm"
        elif "mañana" in p_word or "manana" in p_word:
            meridiem = "am"
        elif "d" in p_word:  # 'del dia'
            meridiem = "pm" if hour == 12 else ("am" if hour < 12 else "pm")
    elif m_prefix:
        hour = int(m_prefix.group(1))
        minute = int(m_prefix.group(2)) if m_prefix.group(2) else 0
        meridiem = m_prefix.group(3)
    elif m_suffix:
        hour = int(m_suffix.group(1))
        minute = 0
        meridiem = None
    elif s.strip().isdigit() and 1 <= int(s.strip()) <= 23:
        hour = int(s.strip())
        minute = 0
        meridiem = None
    elif day_offset > 0:
        m_day = re.search(r'(?:mañana|manana)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?', s, re.I)
        if m_day:
            hour = int(m_day.group(1))
            minute = int(m_day.group(2)) if m_day.group(2) else 0
            meridiem = m_day.group(3)
        elif forced_pm:
            hour, minute, meridiem = 16, 0, "pm"
        elif forced_am:
            hour, minute, meridiem = 10, 0, "am"
        else:
            return None
    elif forced_pm:
        hour, minute, meridiem = 16, 0, "pm"
    elif forced_am:
        hour, minute, meridiem = 10, 0, "am"
    else:
        return None

    if hour is None:
        return None

    if forced_pm and not meridiem:
        meridiem = "pm"
    elif forced_am and not meridiem:
        meridiem = "am"

    if meridiem:
        meridiem = meridiem.lower().replace(".", "")
        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
    elif hour < 7:  # When user says 'a las 4' or 'a las 5', work hours mean PM (13:00 to 18:00)
        hour += 12
    elif hour == 7:
        # If user says 'a las 7', in afternoon or if 7am passed, means 19:00 (closing hour)
        if ref_time.hour >= 12 or hour < ref_time.hour or forced_pm:
            hour = 19
        else:
            hour = 7
    elif hour in (8, 9, 10, 11):
        # 8, 9, 10, 11 are morning operating hours (8:00 to 11:00 AM).
        if forced_pm:
            hour += 12

    if not (0 <= hour <= 23) or not (0 <= minute <= 59):
        return None

    target_date = ref_time.date() + timedelta(days=day_offset)
    res = datetime.combine(target_date, datetime.min.time()).replace(hour=hour, minute=minute)

    # Regla de Horario de Operación de la Gasera (8:00 AM a 7:00 PM / 19:00 hrs):
    # - Si el pedido cae a las 7:00 PM o después (ref_time.hour >= 19), la gasera ya cerró: se va al día siguiente a las 8:00 AM.
    # - Si la hora solicitada es a las 7:00 PM o posterior (res.hour >= 19), se va al día siguiente a las 8:00 AM.
    # - Si la hora solicitada es antes de las 8:00 AM (res.hour < 8), se programa a partir de las 8:00 AM.
    # - Si el pedido se hace para hoy antes de las 7:00 PM (ej. hoy a las 5:00 PM = 17:00), se mantiene para HOY.
    if day_offset == 0:
        if ref_time.hour >= 19 or res.hour >= 19:
            res = datetime.combine(ref_time.date() + timedelta(days=1), datetime.min.time()).replace(hour=8, minute=0)
        elif res.hour < 8:
            res = res.replace(hour=8, minute=0)
    elif day_offset > 0:
        if res.hour >= 19:
            res = datetime.combine(res.date() + timedelta(days=1), datetime.min.time()).replace(hour=8, minute=0)
        elif res.hour < 8:
            res = res.replace(hour=8, minute=0)

    return res


def normalize_schedule_datetime(val: Any, ref_time: datetime | None = None) -> datetime | None:
    """Safely parse any date/time string into a normalized naive local datetime."""
    if not val:
        return None
    if ref_time is None:
        ref_time = datetime.now()
    if isinstance(val, datetime):
        return val.astimezone().replace(tzinfo=None) if val.tzinfo else val
    val_str = str(val).strip()
    if not val_str:
        return None

    # Si es "lo antes posible" / inmediato:
    # NUNCA programar automáticamente un pedido si el cliente no especificó fecha u hora futura.
    if any(w in val_str.lower() for w in [
        "lo antes posible", "inmediato", "urgente", "ahorita", "ahora", "asap",
        "lo mas pronto", "lo más pronto", "ya mismo", "ya", "en cuanto puedan",
        "cuanto antes", "al momento", "lo antes que se pueda"
    ]):
        return None
    clean_iso = val_str
    if clean_iso.endswith("Z"):
        clean_iso = clean_iso[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(clean_iso)
        if dt.tzinfo:
            return dt.astimezone().replace(tzinfo=None)
        return dt
    except Exception:
        pass
    dt = parse_schedule_deadline(val_str, ref_time)
    if dt and dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def to_utc_iso(val: Any, ref_time: datetime | None = None) -> str | None:
    """Convert any local datetime or schedule string to standard UTC ISO string (YYYY-MM-DDTHH:MM:SS.000Z) for NestJS and browser dashboards."""
    dt = normalize_schedule_datetime(val, ref_time)
    if not dt:
        return None
    dt_aware = dt.astimezone()
    dt_utc = dt_aware.astimezone(timezone.utc)
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def format_schedule_display(dt: datetime | None, ref_time: datetime | None = None) -> str:
    """Format a datetime into a clean, human-readable Spanish delivery schedule string."""
    if not dt:
        return "Lo antes posible"
    if ref_time is None:
        ref_time = datetime.now()
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    is_today = dt.date() == ref_time.date()
    is_tomorrow = dt.date() == (ref_time.date() + timedelta(days=1))
    day_label = "Hoy" if is_today else ("Mañana" if is_tomorrow else dt.strftime("%d/%m/%Y"))
    hour_12 = dt.strftime("%I:%M %p").lstrip("0")
    return f"{day_label} a las {hour_12}"


def _row_to_product(row: Any) -> Product:
    """Convert an sqlite3.Row to a Product model."""
    tags = []
    if "tags" in row.keys() and row["tags"]:
        try:
            tags = json.loads(row["tags"])
        except (json.JSONDecodeError, TypeError):
            tags = []

    return Product(
        id=row["id"],
        tenant_id=row["tenant_id"],
        name=row["name"],
        description=row["description"] or "",
        price=float(row["price"]),
        currency=row["currency"] or "MXN",
        category=row["category"] or "",
        image_url=row["image_url"] or "",
        tags=tags,
        in_stock=bool(row["in_stock"]) if "in_stock" in row.keys() else True,
        is_promoted=bool(row["is_promoted"]),
        promotion_text=row["promotion_text"] or "",
    )


def _row_to_driver(row: Any) -> Driver:
    """Convert an sqlite3.Row to a Driver model."""
    keys = row.keys() if hasattr(row, "keys") else []
    return Driver(
        id=row["id"],
        tenant_id=row["tenant_id"],
        name=row["name"],
        phone=row["phone"],
        telegram_user_id=row["telegram_user_id"] or None,
        vehicle_id=row["vehicle_id"] if "vehicle_id" in keys and row["vehicle_id"] is not None else None,
        unit_identifier=row["unit_identifier"] if "unit_identifier" in keys and row["unit_identifier"] is not None else None,
        vehicle_type=row["vehicle_type"] or "cilindros",
        vehicle_plate=row["vehicle_plate"] or "",
        zone=row["zone"] or "General",
        is_available=bool(row["is_available"]),
        current_lat=float(row["current_lat"]) if row["current_lat"] is not None else None,
        current_lng=float(row["current_lng"]) if row["current_lng"] is not None else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_vehicle(row: Any) -> Vehicle:
    """Convert an sqlite3.Row to a Vehicle model."""
    keys = row.keys() if hasattr(row, "keys") else []
    return Vehicle(
        id=row["id"],
        tenant_id=row["tenant_id"],
        unit_identifier=row["unit_identifier"],
        plate=row["plate"],
        model=row["model"],
        vehicle_type=row["vehicle_type"] or "camioneta",
        pipa_capacity_liters=float(row["pipa_capacity_liters"]) if "pipa_capacity_liters" in keys and row["pipa_capacity_liters"] is not None else None,
        cylinder_capacity_count=int(row["cylinder_capacity_count"]) if "cylinder_capacity_count" in keys and row["cylinder_capacity_count"] is not None else None,
        status=row["status"] or "active",
        notes=row["notes"] or "",
        assigned_driver_id=row["assigned_driver_id"] if "assigned_driver_id" in keys and row["assigned_driver_id"] is not None else None,
        assigned_driver_name=row["assigned_driver_name"] if "assigned_driver_name" in keys and row["assigned_driver_name"] is not None else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class SqliteRepository(ProductRepository):
    """SQLite implementation for Products, Customers, Addresses, Drivers, and Orders."""

    # ------------------------------------------------------------------
    # Products
    # ------------------------------------------------------------------

    def _get_all_products(self, tenant_id: str) -> list[Product]:
        """Fetch all products for a tenant from SQLite."""
        with get_db_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM products WHERE tenant_id = ? ORDER BY price ASC",
                (tenant_id,),
            )
            rows = cur.fetchall()
            return [_row_to_product(r) for r in rows]

    def search(self, tenant_id: str, query: str) -> list[Product]:
        """Search products in SQLite using tokenization and stemming."""
        products = self._get_all_products(tenant_id)
        q_tokens = _tokenize(query)
        if not q_tokens:
            return products[:10]

        scored: list[tuple[int, Product]] = []
        for p in products:
            parts = f"{p.name} {p.description} {p.category} {' '.join(p.tags)} {p.id}"
            p_tokens = _tokenize(parts)
            overlap = len(q_tokens & p_tokens)
            if overlap > 0:
                scored.append((overlap, p))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored[:10]]

    def get_by_id(self, tenant_id: str, product_id: str) -> Product | None:
        """Get product by ID from SQLite."""
        with get_db_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM products WHERE tenant_id = ? AND id = ?",
                (tenant_id, product_id),
            )
            row = cur.fetchone()
            return _row_to_product(row) if row else None

    def get_promotions(self, tenant_id: str) -> list[Product]:
        """Get promoted products for a tenant."""
        with get_db_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM products WHERE tenant_id = ? AND is_promoted = 1",
                (tenant_id,),
            )
            rows = cur.fetchall()
            return [_row_to_product(r) for r in rows]

    def find_similar(self, tenant_id: str, description: str) -> list[Product]:
        """Find products matching description by keyword overlap."""
        products = self._get_all_products(tenant_id)
        q_tokens = _tokenize(description)
        scored: list[tuple[int, Product]] = []

        for p in products:
            parts = f"{p.name} {p.description} {p.category} {' '.join(p.tags)}"
            p_tokens = _tokenize(parts)
            overlap = len(q_tokens & p_tokens)
            if overlap > 0:
                scored.append((overlap, p))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored[:5]]

    # ------------------------------------------------------------------
    # Customer Addresses
    # ------------------------------------------------------------------

    def get_customer_addresses(self, customer_id: int) -> list[CustomerAddress]:
        """Get all registered addresses for a customer, default first."""
        with get_db_connection() as conn:
            cur = conn.execute(
                """
                SELECT * FROM customer_addresses
                WHERE customer_id = ?
                ORDER BY is_default DESC, id ASC
                """,
                (customer_id,),
            )
            rows = cur.fetchall()
            results = []
            for r in rows:
                raw_addr = r["address"] or ""
                resolved_addr = resolve_gps_address_to_name(raw_addr)
                # Auto-heal in database if resolved name changed
                if resolved_addr and resolved_addr != raw_addr:
                    try:
                        conn.execute(
                            "UPDATE customer_addresses SET address = ? WHERE id = ?",
                            (resolved_addr, r["id"]),
                        )
                        conn.execute(
                            "UPDATE customers SET address = ? WHERE id = ? AND address = ?",
                            (resolved_addr, customer_id, raw_addr),
                        )
                    except Exception as e:
                        logger.warning(f"Failed to auto-heal customer address in DB: {e}")

                results.append(
                    CustomerAddress(
                        id=r["id"],
                        customer_id=r["customer_id"],
                        address=resolved_addr or raw_addr,
                        alias=r["alias"] or "Principal",
                        notes=r["notes"] or "",
                        is_default=bool(r["is_default"]),
                        created_at=r["created_at"],
                        updated_at=r["updated_at"],
                    )
                )
            return results

    def add_customer_address(
        self,
        customer_id: int,
        address: str,
        alias: str = "",
        notes: str = "",
        is_default: bool = False,
    ) -> CustomerAddress:
        """Add a new delivery address for a customer."""
        clean_addr = resolve_gps_address_to_name(address.strip())
        now_iso = datetime.now(timezone.utc).isoformat()

        with get_db_connection() as conn:
            existing = conn.execute(
                "SELECT * FROM customer_addresses WHERE customer_id = ? AND LOWER(TRIM(address)) = LOWER(?)",
                (customer_id, clean_addr),
            ).fetchone()

            if existing:
                return CustomerAddress(
                    id=existing["id"],
                    customer_id=existing["customer_id"],
                    address=existing["address"],
                    alias=existing["alias"] or "Principal",
                    notes=existing["notes"] or "",
                    is_default=bool(existing["is_default"]),
                    created_at=existing["created_at"],
                    updated_at=existing["updated_at"],
                )

            count = conn.execute(
                "SELECT COUNT(*) as cnt FROM customer_addresses WHERE customer_id = ?",
                (customer_id,),
            ).fetchone()["cnt"]

            if count == 0:
                is_default = True

            if not alias:
                alias = "Principal" if is_default else f"Dirección {count + 1}"

            if is_default and count > 0:
                conn.execute(
                    "UPDATE customer_addresses SET is_default = 0 WHERE customer_id = ?",
                    (customer_id,),
                )

            cur = conn.execute(
                """
                INSERT INTO customer_addresses (
                    customer_id, address, alias, notes, is_default, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (customer_id, clean_addr, alias, notes.strip(), 1 if is_default else 0, now_iso, now_iso),
            )
            addr_id = cur.lastrowid

            return CustomerAddress(
                id=addr_id,
                customer_id=customer_id,
                address=clean_addr,
                alias=alias,
                notes=notes.strip(),
                is_default=is_default,
                created_at=now_iso,
                updated_at=now_iso,
            )

    def delete_customer_address(self, customer_id: int, address_id: int) -> bool:
        """Delete a delivery address for a customer from SQLite."""
        with get_db_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM customer_addresses WHERE id = ? AND customer_id = ?",
                (address_id, customer_id),
            )
            row = cur.fetchone()
            if not row:
                return False

            was_default = bool(row["is_default"])
            conn.execute("DELETE FROM customer_addresses WHERE id = ?", (address_id,))

            # Si era la default, asignar default a la primera dirección restante si existe
            remaining = conn.execute(
                "SELECT * FROM customer_addresses WHERE customer_id = ? ORDER BY id ASC LIMIT 1",
                (customer_id,),
            ).fetchone()

            if remaining:
                if was_default:
                    conn.execute(
                        "UPDATE customer_addresses SET is_default = 1 WHERE id = ?",
                        (remaining["id"],),
                    )
                conn.execute(
                    "UPDATE customers SET address = ? WHERE id = ?",
                    (remaining["address"], customer_id),
                )
            else:
                conn.execute(
                    "UPDATE customers SET address = '' WHERE id = ?",
                    (customer_id,),
                )
            return True

    # ------------------------------------------------------------------
    # Customers
    # ------------------------------------------------------------------

    def save_or_update_customer(
        self,
        tenant_id: str,
        channel: str,
        channel_user_id: str,
        name: str = "",
        phone: str = "",
        address: str = "",
        notes: str = "",
    ) -> Customer:
        """Save or update customer profile in SQLite, managing multiple addresses across channels."""
        now_iso = datetime.now(timezone.utc).isoformat()
        clean_phone = re.sub(r"\D", "", phone) if phone else ""
        clean_10 = clean_phone[-10:] if len(clean_phone) >= 10 else clean_phone

        with get_db_connection() as conn:
            existing = None

            # 1. Buscar primero por teléfono (10 dígitos) para unificar perfil entre Telegram, WhatsApp y Web
            if clean_10:
                rows = conn.execute("SELECT * FROM customers WHERE tenant_id = ? ORDER BY id ASC", (tenant_id,)).fetchall()
                for r in rows:
                    r_phone = re.sub(r"\D", "", r["phone"] or "")
                    r_10 = r_phone[-10:] if len(r_phone) >= 10 else r_phone
                    if r_10 and r_10 == clean_10:
                        existing = r
                        break

            # 2. Si no se encontró por teléfono, buscar por channel_user_id
            if not existing and channel and channel_user_id:
                cur = conn.execute(
                    """
                    SELECT * FROM customers 
                    WHERE tenant_id = ? AND channel = ? AND channel_user_id = ?
                    """,
                    (tenant_id, channel, channel_user_id),
                )
                existing = cur.fetchone()

            if existing:
                new_name = name or existing["name"] or ""
                new_phone = phone or existing["phone"] or ""
                new_notes = notes or existing["notes"] or ""
                cust_addr = address or existing["address"] or ""
                # Si el canal original era genérico o cambió, registrar canal activo
                new_channel = channel if (channel and channel not in ("dashboard", "web", "admin_manual")) else (existing["channel"] or channel)
                new_uid = channel_user_id if (channel_user_id and channel_user_id not in ("dashboard", "web", "admin_manual")) else (existing["channel_user_id"] or channel_user_id)

                if new_channel and new_uid:
                    cur_check = conn.execute(
                        "SELECT id FROM customers WHERE tenant_id = ? AND channel = ? AND channel_user_id = ? AND id != ?",
                        (tenant_id, new_channel, new_uid, existing["id"])
                    )
                    if cur_check.fetchone():
                        new_channel = existing["channel"]
                        new_uid = existing["channel_user_id"]

                conn.execute(
                    """
                    UPDATE customers
                    SET name = ?, phone = ?, address = ?, notes = ?, channel = ?, channel_user_id = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (new_name, new_phone, cust_addr, new_notes, new_channel, new_uid, now_iso, existing["id"]),
                )
                customer_id = existing["id"]
                created_at = existing["created_at"]

            else:
                new_name = name
                new_phone = phone
                new_notes = notes
                cust_addr = resolve_gps_address_to_name(address.strip()) if address else ""
                created_at = now_iso

                cur = conn.execute(
                    """
                    INSERT INTO customers (
                        tenant_id, channel, channel_user_id, name, phone, address, notes,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tenant_id,
                        channel,
                        channel_user_id,
                        new_name,
                        new_phone,
                        cust_addr,
                        new_notes,
                        created_at,
                        now_iso,
                    ),
                )
                customer_id = cur.lastrowid

        if address and address.strip():
            self.add_customer_address(customer_id, address.strip(), notes=notes)

        addresses = self.get_customer_addresses(customer_id)
        default_addr = addresses[0].address if addresses else cust_addr

        return Customer(
            id=customer_id,
            tenant_id=tenant_id,
            channel=channel,
            channel_user_id=channel_user_id,
            name=new_name,
            phone=new_phone,
            address=default_addr,
            notes=new_notes,
            created_at=created_at,
            updated_at=now_iso,
            addresses=addresses,
        )

    def get_customer(
        self, tenant_id: str, channel: str, channel_user_id: str
    ) -> Customer | None:
        """Get customer by channel user ID (with phone fallback) with all registered addresses."""
        with get_db_connection() as conn:
            cur = conn.execute(
                """
                SELECT * FROM customers
                WHERE tenant_id = ? AND channel = ? AND channel_user_id = ?
                """,
                (tenant_id, channel, channel_user_id),
            )
            row = cur.fetchone()

            # Fallback: si channel_user_id tiene un número de teléfono (ej. WhatsApp wa_id 5216699123501)
            if not row and channel_user_id:
                clean_uid = re.sub(r"\D", "", str(channel_user_id))
                if len(clean_uid) >= 10:
                    clean_10 = clean_uid[-10:]
                    rows = conn.execute("SELECT * FROM customers WHERE tenant_id = ? ORDER BY id ASC", (tenant_id,)).fetchall()
                    for r in rows:
                        r_phone = re.sub(r"\D", "", r["phone"] or "")
                        r_10 = r_phone[-10:] if len(r_phone) >= 10 else r_phone
                        if r_10 and r_10 == clean_10:
                            row = r
                            break

            if not row:
                return None

            customer_id = row["id"]
            addresses = self.get_customer_addresses(customer_id)
            default_addr = addresses[0].address if addresses else (row["address"] or "")

            return Customer(
                id=customer_id,
                tenant_id=row["tenant_id"],
                channel=row["channel"],
                channel_user_id=row["channel_user_id"],
                name=row["name"] or "",
                phone=row["phone"] or "",
                address=default_addr,
                notes=row["notes"] or "",
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                addresses=addresses,
            )

    def get_customer_by_phone(
        self, tenant_id: str, phone: str
    ) -> Customer | None:
        """Get customer by phone number with all registered addresses."""
        clean_phone = re.sub(r"\D", "", phone)
        if not clean_phone or len(clean_phone) < 7:
            return None

        with get_db_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM customers WHERE tenant_id = ? ORDER BY id ASC",
                (tenant_id,),
            )
            rows = cur.fetchall()
            matching = []
            for r in rows:
                r_phone = re.sub(r"\D", "", r["phone"] or "")
                if len(r_phone) >= 7 and (
                    r_phone == clean_phone
                    or (len(clean_phone) >= 10 and len(r_phone) >= 10 and r_phone[-10:] == clean_phone[-10:])
                ):
                    customer_id = r["id"]
                    addresses = self.get_customer_addresses(customer_id)
                    default_addr = addresses[0].address if addresses else (r["address"] or "")

                    cust_obj = Customer(
                        id=customer_id,
                        tenant_id=r["tenant_id"],
                        channel=r["channel"],
                        channel_user_id=r["channel_user_id"],
                        name=r["name"] or "",
                        phone=r["phone"] or "",
                        address=default_addr,
                        notes=r["notes"] or "",
                        created_at=r["created_at"],
                        updated_at=r["updated_at"],
                        addresses=addresses,
                    )
                    matching.append(cust_obj)

            if not matching:
                return None

            # Prioritize the profile with registered addresses and complete details
            matching.sort(key=lambda c: (len(c.addresses), len(c.address.strip()), len(c.name.strip())), reverse=True)
            return matching[0]

    # ------------------------------------------------------------------
    # Drivers (Repartidores / Choferes)
    # ------------------------------------------------------------------

    def get_driver(self, driver_id: int) -> Driver | None:
        """Get driver by ID."""
        with get_db_connection() as conn:
            cur = conn.execute("SELECT * FROM drivers WHERE id = ?", (driver_id,))
            row = cur.fetchone()
            return _row_to_driver(row) if row else None

    def get_driver_by_telegram_id(self, tenant_id: str, telegram_user_id: str) -> Driver | None:
        """Find driver by their Telegram User ID."""
        with get_db_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM drivers WHERE tenant_id = ? AND telegram_user_id = ?",
                (tenant_id, str(telegram_user_id)),
            )
            row = cur.fetchone()
            return _row_to_driver(row) if row else None

    def get_driver_by_phone(self, tenant_id: str, phone: str) -> Driver | None:
        """Find driver by phone number (matches exact or 10-digit suffix)."""
        clean_phone = re.sub(r"\D", "", phone)
        clean_10 = clean_phone[-10:] if len(clean_phone) >= 10 else clean_phone
        with get_db_connection() as conn:
            rows = conn.execute("SELECT * FROM drivers WHERE tenant_id = ?", (tenant_id,)).fetchall()
            for r in rows:
                r_phone = re.sub(r"\D", "", r["phone"] or "")
                r_10 = r_phone[-10:] if len(r_phone) >= 10 else r_phone
                if clean_10 and r_10:
                    if clean_10 == r_10 or r_phone == clean_phone or r_phone.endswith(clean_10) or clean_phone.endswith(r_10):
                        return _row_to_driver(r)
        return None

    def get_all_drivers(self, tenant_id: str = "petroil") -> list[Driver]:
        """Fetch all drivers registered for a tenant."""
        with get_db_connection() as conn:
            rows = conn.execute("SELECT * FROM drivers WHERE tenant_id = ? ORDER BY id ASC", (tenant_id,)).fetchall()
            return [_row_to_driver(r) for r in rows]

    def get_available_drivers(
        self, tenant_id: str = "petroil", vehicle_type: str = "ambos", zone: str = ""
    ) -> list[Driver]:
        """Fetch available drivers matching vehicle capability."""
        with get_db_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM drivers WHERE tenant_id = ? AND is_available = 1 ORDER BY id ASC",
                (tenant_id,),
            )
            rows = cur.fetchall()
            matched: list[Driver] = []
            for r in rows:
                v_type = r["vehicle_type"] or "cilindros"
                if vehicle_type == "ambos" or v_type == "ambos" or v_type == vehicle_type:
                    matched.append(_row_to_driver(r))
            return matched

    def register_or_link_driver_telegram(
        self, tenant_id: str, phone: str, telegram_user_id: str, name: str = ""
    ) -> Driver:
        """Link an existing driver or register a new one with their Telegram ID."""
        now_iso = datetime.now(timezone.utc).isoformat()
        clean_phone = re.sub(r"\D", "", phone)

        driver = self.get_driver_by_phone(tenant_id, clean_phone)
        driver_id = None

        with get_db_connection() as conn:
            if driver:
                driver_id = driver.id
                conn.execute(
                    "UPDATE drivers SET telegram_user_id = ?, updated_at = ? WHERE id = ?",
                    (str(telegram_user_id), now_iso, driver_id),
                )
            else:
                d_name = name or f"Chofer {clean_phone[-4:]}"
                cur = conn.execute(
                    """
                    INSERT INTO drivers (
                        tenant_id, name, phone, telegram_user_id, vehicle_type,
                        is_available, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'cilindros', 1, ?, ?)
                    """,
                    (tenant_id, d_name, clean_phone, str(telegram_user_id), now_iso, now_iso),
                )
                driver_id = cur.lastrowid

        return self.get_driver(driver_id)

    def register_driver_full(
        self,
        tenant_id: str,
        telegram_user_id: str,
        name: str,
        phone: str,
        vehicle_type: str = "cilindros",
        vehicle_plate: str = "",
        zone: str = "General",
        lat: float | None = None,
        lng: float | None = None,
    ) -> Driver:
        """Register or update complete driver profile with Telegram ID and vehicle details."""
        now_iso = datetime.now(timezone.utc).isoformat()
        clean_phone = re.sub(r"\D", "", phone)
        tg_id_str = str(telegram_user_id)

        driver = self.get_driver_by_telegram_id(tenant_id, tg_id_str)
        if not driver and clean_phone:
            driver = self.get_driver_by_phone(tenant_id, clean_phone)

        with get_db_connection() as conn:
            if driver:
                driver_id = driver.id
                conn.execute(
                    """
                    UPDATE drivers
                    SET name = ?, phone = ?, telegram_user_id = ?, vehicle_type = ?,
                        vehicle_plate = ?, zone = ?, is_available = 1,
                        current_lat = COALESCE(?, current_lat),
                        current_lng = COALESCE(?, current_lng),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        name or driver.name,
                        clean_phone or driver.phone,
                        tg_id_str,
                        vehicle_type or driver.vehicle_type,
                        vehicle_plate or driver.vehicle_plate,
                        zone or driver.zone,
                        lat,
                        lng,
                        now_iso,
                        driver_id,
                    ),
                )
            else:
                cur = conn.execute(
                    """
                    INSERT INTO drivers (
                        tenant_id, name, phone, telegram_user_id, vehicle_type,
                        vehicle_plate, zone, is_available, current_lat, current_lng,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                    """,
                    (
                        tenant_id,
                        name,
                        clean_phone,
                        tg_id_str,
                        vehicle_type,
                        vehicle_plate,
                        zone,
                        lat,
                        lng,
                        now_iso,
                        now_iso,
                    ),
                )
                driver_id = cur.lastrowid

        return self.get_driver(driver_id)

    def set_driver_availability(self, driver_id: int, is_available: bool) -> None:
        """Toggle driver active/busy status."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE drivers SET is_available = ?, updated_at = ? WHERE id = ?",
                (1 if is_available else 0, now_iso, driver_id),
            )

    def update_driver_location(self, driver_id: int, lat: float, lng: float) -> None:
        """Update driver's current GPS coordinates."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE drivers SET current_lat = ?, current_lng = ?, updated_at = ? WHERE id = ?",
                (lat, lng, now_iso, driver_id),
            )

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def create_order(
        self,
        tenant_id: str,
        customer_name: str,
        customer_phone: str,
        delivery_address: str,
        items: list[dict[str, Any]],
        delivery_schedule: str = "Lo antes posible",
        payment_method: str = "Efectivo",
        notes: str = "",
        channel: str = "",
        channel_user_id: str = "",
        customer_id: int | None = None,
        delivery_lat: float | None = None,
        delivery_lng: float | None = None,
        scheduled_for: str | None = None,
    ) -> Order:
        """Create a new customer order and order items in SQLite."""
        now_dt = datetime.now()
        now_iso = datetime.now(timezone.utc).isoformat()
        clean_address = resolve_gps_address_to_name(delivery_address.strip())
        if (not clean_address or clean_address.lower().startswith("ubicaci")) and delivery_lat is not None and delivery_lng is not None:
            resolved_from_gps = reverse_geocode(delivery_lat, delivery_lng)
            if resolved_from_gps and not resolved_from_gps.lower().startswith("ubicaci"):
                clean_address = f"{resolved_from_gps} - {notes}" if notes else resolved_from_gps
        clean_schedule = delivery_schedule.strip() if delivery_schedule else "Lo antes posible"
        clean_payment = payment_method.strip() if payment_method else "Efectivo"

        sched_text = str(delivery_schedule or "").strip().lower()
        has_asap_text = any(w in sched_text for w in [
            "lo antes posible", "inmediato", "urgente", "ahorita", "ahora", "asap",
            "lo mas pronto", "lo más pronto", "ya mismo", "ya", "en cuanto puedan", "cuanto antes"
        ])
        deadline_dt = None
        if not has_asap_text:
            if scheduled_for and str(scheduled_for).strip():
                deadline_dt = normalize_schedule_datetime(scheduled_for, now_dt)
            elif clean_schedule and clean_schedule != "Lo antes posible":
                deadline_dt = normalize_schedule_datetime(clean_schedule, now_dt)

        if deadline_dt and deadline_dt > (now_dt + timedelta(minutes=15)):
            scheduled_for_iso = deadline_dt.isoformat()
            if not clean_schedule or clean_schedule == "Lo antes posible":
                clean_schedule = format_schedule_display(deadline_dt, now_dt)
            initial_status = "scheduled" if now_dt < (deadline_dt - timedelta(minutes=30)) else "confirmed"
        else:
            deadline_dt = None
            scheduled_for_iso = None
            clean_schedule = "Lo antes posible"
            initial_status = "confirmed"

        # Find or create customer
        if not customer_id:
            cust = None
            if customer_phone:
                cust = self.get_customer_by_phone(tenant_id, customer_phone)
            if not cust and channel and channel_user_id and channel_user_id not in ("admin_manual", "web", "dashboard"):
                cust = self.get_customer(tenant_id, channel, channel_user_id)

            if cust:
                customer_id = cust.id
                if clean_address:
                    self.add_customer_address(customer_id, clean_address, notes=notes)
            else:
                cust_channel_user_id = channel_user_id
                if not cust_channel_user_id or cust_channel_user_id in ("admin_manual", "web", "dashboard"):
                    cust_channel_user_id = f"{channel or 'dashboard'}_{customer_phone}" if customer_phone else f"cust_{datetime.now().timestamp()}"

                new_cust = self.save_or_update_customer(
                    tenant_id=tenant_id,
                    channel=channel or "dashboard",
                    channel_user_id=cust_channel_user_id,
                    name=customer_name,
                    phone=customer_phone,
                    address=clean_address,
                    notes=notes,
                )
                customer_id = new_cust.id
        elif clean_address:
            self.add_customer_address(customer_id, clean_address, notes=notes)

        # Resolve items and calculate totals
        order_items_to_save: list[OrderItem] = []
        total_amount = 0.0
        currency = "MXN"

        all_products = self._get_all_products(tenant_id)
        prod_map_by_id = {p.id.lower(): p for p in all_products}
        prod_map_by_name = {p.name.lower(): p for p in all_products}

        for raw_item in items:
            product_id = str(raw_item.get("product_id", "")).strip()
            product_name = str(raw_item.get("product_name", "")).strip()
            try:
                raw_qty = float(raw_item.get("quantity", 1))
            except (ValueError, TypeError):
                raw_qty = 1.0

            matched_p = prod_map_by_id.get(product_id.lower())
            if not matched_p and product_name:
                matched_p = prod_map_by_name.get(product_name.lower())
            if not matched_p:
                search_res = self.search(tenant_id, product_id or product_name)
                if search_res:
                    matched_p = search_res[0]

            if matched_p:
                p_id = matched_p.id
                p_name = matched_p.name
                unit_price = matched_p.price
                currency = matched_p.currency
            else:
                p_id = product_id or "custom-item"
                p_name = product_name or product_id or "Producto Gas"
                unit_price = float(raw_item.get("unit_price", 0.0))

            is_stationary = (
                matched_p and (
                    "estacionario" in matched_p.name.lower()
                    or "litro" in str(getattr(matched_p, "unit", "")).lower()
                    or str(getattr(matched_p, "category", "")).upper() == "ESTACIONARIO"
                )
            ) or ("estacionario" in product_name.lower() or "litro" in product_name.lower())

            incoming_price = float(raw_item.get("unit_price", 0.0))
            if is_stationary and incoming_price > (unit_price * 1.5) and raw_qty <= 5.0:
                raw_qty = round(incoming_price / unit_price, 2)

            quantity = int(raw_qty) if raw_qty.is_integer() else round(raw_qty, 2)
            if quantity <= 0:
                quantity = 1

            subtotal = round(unit_price * quantity, 2)
            total_amount += subtotal

            order_items_to_save.append(
                OrderItem(
                    product_id=p_id,
                    product_name=p_name,
                    quantity=quantity,
                    unit_price=unit_price,
                    subtotal=subtotal,
                )
            )

        with get_db_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO orders (
                    tenant_id, customer_id, customer_name, customer_phone,
                    delivery_address, delivery_schedule, total_amount, currency,
                    status, payment_method, notes, channel, channel_user_id,
                    delivery_lat, delivery_lng, scheduled_for, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    customer_id,
                    customer_name,
                    customer_phone,
                    clean_address,
                    clean_schedule,
                    total_amount,
                    currency,
                    initial_status,
                    clean_payment,
                    notes,
                    channel,
                    channel_user_id,
                    delivery_lat,
                    delivery_lng,
                    scheduled_for_iso,
                    now_iso,
                    now_iso,
                ),
            )
            order_id = cur.lastrowid

            saved_items: list[OrderItem] = []
            for itm in order_items_to_save:
                cur_item = conn.execute(
                    """
                    INSERT INTO order_items (
                        order_id, product_id, product_name, quantity, unit_price, subtotal
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        order_id,
                        itm.product_id,
                        itm.product_name,
                        itm.quantity,
                        itm.unit_price,
                        itm.subtotal,
                    ),
                )
                itm.id = cur_item.lastrowid
                itm.order_id = order_id
                saved_items.append(itm)

        return Order(
            id=order_id,
            tenant_id=tenant_id,
            customer_id=customer_id,
            customer_name=customer_name,
            customer_phone=customer_phone,
            delivery_address=clean_address,
            delivery_schedule=clean_schedule,
            total_amount=total_amount,
            currency=currency,
            status=initial_status,
            payment_method=clean_payment,
            notes=notes,
            channel=channel,
            channel_user_id=channel_user_id,
            delivery_lat=delivery_lat,
            delivery_lng=delivery_lng,
            scheduled_for=scheduled_for_iso,
            created_at=now_iso,
            updated_at=now_iso,
            items=saved_items,
        )

    def get_order_by_id(self, tenant_id: str, order_id: int) -> Order | None:
        """Get order and its items by ID, including assigned driver name."""
        with get_db_connection() as conn:
            cur = conn.execute(
                """
                SELECT o.*, d.name as driver_name
                FROM orders o
                LEFT JOIN drivers d ON o.driver_id = d.id
                WHERE o.tenant_id = ? AND o.id = ?
                """,
                (tenant_id, order_id),
            )
            row = cur.fetchone()
            if not row:
                return None

            items_cur = conn.execute(
                "SELECT * FROM order_items WHERE order_id = ?",
                (order_id,),
            )
            item_rows = items_cur.fetchall()
            items = [
                OrderItem(
                    id=ir["id"],
                    order_id=ir["order_id"],
                    product_id=ir["product_id"],
                    product_name=ir["product_name"],
                    quantity=ir["quantity"],
                    unit_price=float(ir["unit_price"]),
                    subtotal=float(ir["subtotal"]),
                )
                for ir in item_rows
            ]

            keys = row.keys()
            delivery_schedule = row["delivery_schedule"] if "delivery_schedule" in keys and row["delivery_schedule"] else "Lo antes posible"
            payment_method = row["payment_method"] if "payment_method" in keys and row["payment_method"] else "Efectivo"
            driver_id = row["driver_id"] if "driver_id" in keys else None
            driver_name = row["driver_name"] if "driver_name" in keys else None
            delivery_lat = float(row["delivery_lat"]) if "delivery_lat" in keys and row["delivery_lat"] is not None else None
            delivery_lng = float(row["delivery_lng"]) if "delivery_lng" in keys and row["delivery_lng"] is not None else None
            live_location_message_id = int(row["live_location_message_id"]) if "live_location_message_id" in keys and row["live_location_message_id"] is not None else None
            live_location_chat_id = row["live_location_chat_id"] if "live_location_chat_id" in keys and row["live_location_chat_id"] else None
            assigned_at = row["assigned_at"] if "assigned_at" in keys else None
            delivered_at = row["delivered_at"] if "delivered_at" in keys else None
            scheduled_for = row["scheduled_for"] if "scheduled_for" in keys else None
            driver_message_ids = row["driver_message_ids"] if "driver_message_ids" in keys else None

            canc_info = None
            try:
                from src.repositories.identity_store import identity_store
                canc_info = identity_store.get_order_cancellation(row["id"])
            except Exception:
                pass

            return Order(
                id=row["id"],
                tenant_id=row["tenant_id"],
                customer_id=row["customer_id"],
                customer_name=row["customer_name"],
                customer_phone=row["customer_phone"],
                delivery_address=row["delivery_address"],
                delivery_schedule=delivery_schedule,
                total_amount=float(row["total_amount"]),
                currency=row["currency"],
                status=row["status"],
                payment_method=payment_method,
                notes=row["notes"] or "",
                channel=row["channel"] or "",
                channel_user_id=row["channel_user_id"] or "",
                driver_id=driver_id,
                driver_name=driver_name,
                delivery_lat=delivery_lat,
                delivery_lng=delivery_lng,
                live_location_message_id=live_location_message_id,
                live_location_chat_id=live_location_chat_id,
                driver_message_ids=driver_message_ids,
                assigned_at=assigned_at,
                delivered_at=delivered_at,
                scheduled_for=scheduled_for,
                cancelled_by=canc_info.get("cancelled_by") if canc_info else None,
                cancellation_reason=canc_info.get("reason") if canc_info else None,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                items=items,
            )

    def set_order_live_location(
        self, tenant_id: str, order_id: int, chat_id: str, message_id: int
    ) -> bool:
        """Store Telegram live location message ID and chat ID for an active order."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with get_db_connection() as conn:
            conn.execute(
                """
                UPDATE orders
                SET live_location_message_id = ?, live_location_chat_id = ?, updated_at = ?
                WHERE tenant_id = ? AND id = ?
                """,
                (message_id, str(chat_id), now_iso, tenant_id, order_id),
            )
            return True

    def clear_order_live_location(self, tenant_id: str, order_id: int) -> bool:
        """Clear the Telegram live location message ID for an order."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with get_db_connection() as conn:
            conn.execute(
                """
                UPDATE orders
                SET live_location_message_id = NULL, live_location_chat_id = NULL, updated_at = ?
                WHERE tenant_id = ? AND id = ?
                """,
                (now_iso, tenant_id, order_id),
            )
            return True

    def add_order_driver_message_id(self, tenant_id: str, order_id: int, message_id: int) -> bool:
        """Store Telegram message ID sent to the driver for this order so buttons can be removed on cancellation."""
        if not order_id or not message_id:
            return False
        now_iso = datetime.now(timezone.utc).isoformat()
        with get_db_connection() as conn:
            row = conn.execute("SELECT driver_message_ids FROM orders WHERE tenant_id = ? AND id = ?", (tenant_id, order_id)).fetchone()
            current_str = (row["driver_message_ids"] or "") if row else ""
            existing = [int(x) for x in current_str.split(",") if x.strip().isdigit()]
            if message_id not in existing:
                existing.append(message_id)
                new_str = ",".join(str(x) for x in existing[-15:])
                conn.execute(
                    "UPDATE orders SET driver_message_ids = ?, updated_at = ? WHERE tenant_id = ? AND id = ?",
                    (new_str, now_iso, tenant_id, order_id),
                )
            return True

    def get_order_driver_message_ids(self, tenant_id: str, order_id: int) -> list[int]:
        """Retrieve all Telegram message IDs sent to the driver for this order."""
        with get_db_connection() as conn:
            row = conn.execute("SELECT driver_message_ids FROM orders WHERE tenant_id = ? AND id = ?", (tenant_id, order_id)).fetchone()
            if not row or not row["driver_message_ids"]:
                return []
            return [int(x) for x in str(row["driver_message_ids"]).split(",") if x.strip().isdigit()]

    def clear_order_driver_message_ids(self, tenant_id: str, order_id: int) -> bool:
        """Clear the driver message IDs for an order."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE orders SET driver_message_ids = NULL, updated_at = ? WHERE tenant_id = ? AND id = ?",
                (now_iso, tenant_id, order_id),
            )
            return True

    def assign_order_to_driver(
        self,
        tenant_id: str,
        order_id: int,
        driver_id: int | None,
        delivery_lat: float | None = None,
        delivery_lng: float | None = None,
        force_activate: bool = False,
    ) -> Order | None:
        """Assign an order to a driver with geocoded coordinates.
        If the order is scheduled for a future time (>30m) and not force_activated, status remains 'scheduled' until T-30 activation.
        """
        now_dt = datetime.now()
        existing_order = self.get_order_by_id(tenant_id, order_id)
        is_future_scheduled = False
        if existing_order and not force_activate and existing_order.status in ("scheduled", "PROGRAMADO", "SCHEDULED"):
            s_for = existing_order.scheduled_for
            s_text = existing_order.delivery_schedule
            deadline_dt = normalize_schedule_datetime(s_for, now_dt)
            if not deadline_dt and s_text:
                deadline_dt = normalize_schedule_datetime(s_text, now_dt)
            if deadline_dt and now_dt < (deadline_dt - timedelta(minutes=30)):
                is_future_scheduled = True

        new_status = "scheduled" if is_future_scheduled else ("assigned" if driver_id else "confirmed")
        now_iso = datetime.now(timezone.utc).isoformat()
        with get_db_connection() as conn:
            conn.execute(
                """
                UPDATE orders
                SET driver_id = ?, status = ?, delivery_lat = ?, delivery_lng = ?,
                    assigned_at = ?, updated_at = ?
                WHERE tenant_id = ? AND id = ?
                """,
                (driver_id, new_status, delivery_lat, delivery_lng, now_iso, now_iso, tenant_id, order_id),
            )
        return self.get_order_by_id(tenant_id, order_id)

    def update_order_status(
        self, tenant_id: str, order_id: int, status: str, notes_append: str = "", **kwargs: Any
    ) -> Order | None:
        """Update order lifecycle status (e.g. in_route, delivered, cancelled)."""
        now_iso = datetime.now(timezone.utc).isoformat()
        delivered_at = now_iso if status == "delivered" else None
        order = self.get_order_by_id(tenant_id, order_id)

        with get_db_connection() as conn:
            if delivered_at:
                conn.execute(
                    """
                    UPDATE orders
                    SET status = ?, delivered_at = ?, updated_at = ?
                    WHERE tenant_id = ? AND id = ?
                    """,
                    (status, delivered_at, now_iso, tenant_id, order_id),
                )
            elif notes_append:
                current_notes = order.notes if order and order.notes else ""
                new_notes = f"{current_notes} | {notes_append}".strip(" |")
                conn.execute(
                    """
                    UPDATE orders
                    SET status = ?, notes = ?, updated_at = ?
                    WHERE tenant_id = ? AND id = ?
                    """,
                    (status, new_notes, now_iso, tenant_id, order_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE orders
                    SET status = ?, updated_at = ?
                    WHERE tenant_id = ? AND id = ?
                    """,
                    (status, now_iso, tenant_id, order_id),
                )

        if status == "cancelled" and order and order.driver_id:
            self.set_driver_availability(order.driver_id, True)

        return self.get_order_by_id(tenant_id, order_id)

    def update_order_delivery_coords(
        self, tenant_id: str, order_id: int, delivery_lat: float, delivery_lng: float, delivery_address: str | None = None
    ) -> bool:
        """Update delivery coordinates and optionally address for an order."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with get_db_connection() as conn:
            if delivery_address:
                conn.execute(
                    """
                    UPDATE orders
                    SET delivery_lat = ?, delivery_lng = ?, delivery_address = ?, updated_at = ?
                    WHERE tenant_id = ? AND id = ?
                    """,
                    (delivery_lat, delivery_lng, delivery_address, now_iso, tenant_id, order_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE orders
                    SET delivery_lat = ?, delivery_lng = ?, updated_at = ?
                    WHERE tenant_id = ? AND id = ?
                    """,
                    (delivery_lat, delivery_lng, now_iso, tenant_id, order_id),
                )
        return True

    def get_orders_by_customer_phone(
        self, tenant_id: str, phone: str, limit: int = 5
    ) -> list[Order]:
        """Find orders by customer phone number."""
        clean_phone = re.sub(r"\D", "", phone)
        with get_db_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM orders WHERE tenant_id = ? ORDER BY id DESC",
                (tenant_id,),
            )
            rows = cur.fetchall()
            matched_orders: list[Order] = []

            for r in rows:
                r_phone = re.sub(r"\D", "", r["customer_phone"] or "")
                if r_phone and (r_phone == clean_phone or r_phone.endswith(clean_phone) or clean_phone.endswith(r_phone)):
                    order = self.get_order_by_id(tenant_id, r["id"])
                    if order:
                        matched_orders.append(order)
                    if len(matched_orders) >= limit:
                        break

            return matched_orders

    def get_orders_by_driver(
        self, tenant_id: str, driver_id: Any, active_only: bool = True
    ) -> list[Order]:
        """Get orders assigned to a specific driver."""
        if not driver_id:
            return []
        d_int = int(driver_id) if str(driver_id).isdigit() else None
        with get_db_connection() as conn:
            if active_only:
                cur = conn.execute(
                    "SELECT id FROM orders WHERE tenant_id = ? AND (driver_id = ? OR driver_id = ? OR (? IS NOT NULL AND driver_id = ?)) AND status IN ('assigned', 'in_route') ORDER BY id DESC",
                    (tenant_id, driver_id, str(driver_id), d_int, d_int),
                )
            else:
                cur = conn.execute(
                    "SELECT id FROM orders WHERE tenant_id = ? AND (driver_id = ? OR driver_id = ? OR (? IS NOT NULL AND driver_id = ?)) ORDER BY id DESC LIMIT 10",
                    (tenant_id, driver_id, str(driver_id), d_int, d_int),
                )
            rows = cur.fetchall()
            return [self.get_order_by_id(tenant_id, r["id"]) for r in rows if r]

    def cancel_order(
        self, tenant_id: str, order_id: int, cancelled_by: str = "customer", reason: str = ""
    ) -> Order | None:
        """Cancel an order, release driver if assigned, and update database."""
        from src.repositories.identity_store import identity_store
        identity_store.save_order_cancellation(order_id, cancelled_by=cancelled_by, reason=reason)
        try:
            from src.services.order_events import _EVENT_DEDUP_CACHE
            import time
            _EVENT_DEDUP_CACHE[f"cancelled:{order_id}"] = time.time()
        except Exception:
            pass

        order = self.get_order_by_id(tenant_id, order_id)
        if not order:
            return None

        now_iso = datetime.now(timezone.utc).isoformat()
        with get_db_connection() as conn:
            conn.execute(
                """
                UPDATE orders
                SET status = 'cancelled', updated_at = ?
                WHERE tenant_id = ? AND id = ?
                """,
                (now_iso, tenant_id, order_id),
            )

        # Release driver if they were assigned
        if order.driver_id:
            self.set_driver_availability(order.driver_id, True)

        return self.get_order_by_id(tenant_id, order_id)

    def get_scheduled_orders(self, tenant_id: str) -> list[Order]:
        """Get all orders that are scheduled for future delivery and not yet dispatched."""
        with get_db_connection() as conn:
            cur = conn.execute(
                "SELECT id FROM orders WHERE tenant_id = ? AND status = 'scheduled' ORDER BY id ASC",
                (tenant_id,),
            )
            rows = cur.fetchall()
            return [self.get_order_by_id(tenant_id, r["id"]) for r in rows if r]

    def check_and_activate_scheduled_orders(self, tenant_id: str = "petroil") -> list[int]:
        """Check all scheduled orders and activate those within 30 minutes of their deadline.
        
        Transitions status:
        - If assigned to driver: stays 'assigned' and dispatches Telegram notification
        - If unassigned: becomes 'confirmed' and triggers smart dispatch
        Returns list of activated order IDs.
        """
        now = datetime.now()
        activated_ids = []

        with get_db_connection() as conn:
            cur = conn.execute(
                """
                SELECT id, scheduled_for, delivery_schedule, status, driver_id
                FROM orders
                WHERE tenant_id = ? AND status IN ('scheduled', 'confirmed', 'assigned')
                """,
                (tenant_id,),
            )
            rows = cur.fetchall()

            for r in rows:
                oid = r["id"]
                s_for = r["scheduled_for"]
                schedule_text = r["delivery_schedule"]
                status = r["status"]
                driver_id = r["driver_id"]

                deadline_dt = normalize_schedule_datetime(s_for, now)
                if not deadline_dt and schedule_text:
                    deadline_dt = normalize_schedule_datetime(schedule_text, now)

                if not deadline_dt:
                    continue

                # 30-minute window threshold
                activation_time = deadline_dt - timedelta(minutes=30)
                
                # If now is at or after 30 minutes before deadline
                if now >= activation_time:
                    if status == "scheduled":
                        new_status = "assigned" if driver_id else "confirmed"
                        conn.execute(
                            "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
                            (new_status, now.isoformat(), oid),
                        )
                        activated_ids.append(oid)
                        logger.info(
                            f"[Scheduled Engine] Order #{oid} reached 30m window before deadline "
                            f"({deadline_dt.strftime('%Y-%m-%d %H:%M')}). Activated to '{new_status}'."
                        )
                        
                        # Trigger dispatch
                        try:
                            from src.services.dispatch import dispatch_order
                            dispatch_order(oid, tenant_id=tenant_id, force_immediate=True)
                        except Exception as e:
                            logger.error(f"[Scheduled Engine] Error dispatching activated order #{oid}: {e}")

        return activated_ids

    def get_scheduled_agenda(self, tenant_id: str = "petroil") -> list[dict[str, Any]]:
        """Return all scheduled orders with deadline details, activation status, and countdowns."""
        self.check_and_activate_scheduled_orders(tenant_id)
        now = datetime.now()

        with get_db_connection() as conn:
            cur = conn.execute(
                """
                SELECT o.*, d.name AS driver_name, d.phone AS driver_phone, d.vehicle_type AS driver_vehicle
                FROM orders o
                LEFT JOIN drivers d ON o.driver_id = d.id
                WHERE o.tenant_id = ?
                  AND o.status NOT IN ('cancelled', 'delivered')
                  AND (o.scheduled_for IS NOT NULL OR o.status = 'scheduled')
                ORDER BY o.id DESC
                """,
                (tenant_id,),
            )
            rows = cur.fetchall()

            agenda = []
            for r in rows:
                oid = r["id"]
                st = r["status"]
                created_raw = r["created_at"]
                order_ref_dt = now
                if created_raw:
                    try:
                        c_clean = str(created_raw).replace("Z", "+00:00")
                        order_ref_dt = datetime.fromisoformat(c_clean)
                        if order_ref_dt.tzinfo:
                            order_ref_dt = order_ref_dt.astimezone().replace(tzinfo=None)
                    except Exception:
                        order_ref_dt = now

                s_for = r["scheduled_for"]
                schedule_text = r["delivery_schedule"] or "Lo antes posible"

                deadline_dt = normalize_schedule_datetime(s_for, now)
                if not deadline_dt and schedule_text:
                    deadline_dt = normalize_schedule_datetime(schedule_text, order_ref_dt)

                if not deadline_dt:
                    continue

                if st != "scheduled" and deadline_dt and deadline_dt.date() < now.date():
                    continue

                if not schedule_text or schedule_text == "Lo antes posible":
                    schedule_text = format_schedule_display(deadline_dt, now)

                activation_time = deadline_dt - timedelta(minutes=30)
                is_activated = now >= activation_time

                diff_deadline_mins = int((deadline_dt - now).total_seconds() / 60)
                diff_act_mins = int((activation_time - now).total_seconds() / 60)

                deadline_display = format_schedule_display(deadline_dt, now)
                act_time_label = activation_time.strftime("%I:%M %p").lstrip("0")
                is_today = deadline_dt.date() == now.date()
                is_tomorrow = deadline_dt.date() == (now.date() + timedelta(days=1))
                day_label = "Hoy" if is_today else ("Mañana" if is_tomorrow else deadline_dt.strftime("%d/%m/%Y"))
                act_display = f"{day_label} a las {act_time_label}"

                items_cur = conn.execute(
                    "SELECT product_name, quantity, unit_price, subtotal FROM order_items WHERE order_id = ?",
                    (oid,),
                )
                items = [
                    {
                        "product_name": it["product_name"],
                        "quantity": it["quantity"],
                        "unit_price": it["unit_price"],
                        "subtotal": it["subtotal"],
                    }
                    for it in items_cur.fetchall()
                ]

                agenda.append({
                    "id": oid,
                    "customer_name": r["customer_name"],
                    "customer_phone": r["customer_phone"],
                    "delivery_address": r["delivery_address"],
                    "delivery_schedule": schedule_text,
                    "scheduled_for": deadline_dt.isoformat(),
                    "deadline_display": deadline_display,
                    "activation_at": activation_time.isoformat(),
                    "activation_display": act_display,
                    "is_activated": is_activated,
                    "minutes_until_deadline": diff_deadline_mins,
                    "minutes_until_activation": diff_act_mins,
                    "total_amount": float(r["total_amount"]),
                    "currency": r["currency"],
                    "payment_method": r["payment_method"],
                    "notes": r["notes"] or "",
                    "status": r["status"],
                    "driver_id": r["driver_id"],
                    "driver_name": r["driver_name"],
                    "driver_phone": r["driver_phone"],
                    "driver_vehicle": r["driver_vehicle"],
                    "delivery_lat": r["delivery_lat"],
                    "delivery_lng": r["delivery_lng"],
                    "items": items,
                    "created_at": r["created_at"],
                })

            def _agenda_sort_key(item: dict[str, Any]) -> tuple[str, int]:
                deadline = str(item.get("scheduled_for") or "9999-12-31T23:59:59")
                try:
                    order_num = int(item.get("id") or 0)
                except Exception:
                    order_num = 0
                return (deadline, order_num)

            agenda.sort(key=_agenda_sort_key, reverse=False)
            return agenda

    def reschedule_order(
        self, tenant_id: str, order_id: int, new_schedule: str, new_datetime_iso: str | None = None
    ) -> Order | None:
        """Update scheduled time for an order and adjust its activation status."""
        now = datetime.now()
        deadline_dt = normalize_schedule_datetime(new_datetime_iso, now)
        if not deadline_dt and new_schedule:
            deadline_dt = normalize_schedule_datetime(new_schedule, now)

        s_iso = deadline_dt.isoformat() if deadline_dt else None
        if deadline_dt and (not new_schedule or new_schedule == "Lo antes posible"):
            new_schedule = format_schedule_display(deadline_dt, now)
        
        order = self.get_order_by_id(tenant_id, order_id)
        if not order:
            return None

        if order.status not in ("delivered", "cancelled"):
            if deadline_dt and now < (deadline_dt - timedelta(minutes=30)):
                new_status = "scheduled"
            else:
                new_status = "assigned" if order.driver_id else "confirmed"
        else:
            new_status = order.status

        with get_db_connection() as conn:
            conn.execute(
                """
                UPDATE orders
                SET delivery_schedule = ?, scheduled_for = ?, status = ?, updated_at = ?
                WHERE tenant_id = ? AND id = ?
                """,
                (new_schedule, s_iso, new_status, now.isoformat(), tenant_id, order_id),
            )

        return self.get_order_by_id(tenant_id, order_id)

    def activate_scheduled_order_now(self, tenant_id: str, order_id: int) -> Order | None:
        """Manually push a scheduled order into active dispatch immediately."""
        order = self.get_order_by_id(tenant_id, order_id)
        if not order:
            return None

        new_status = "assigned" if order.driver_id else "confirmed"
        now = datetime.now()
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE orders SET status = ?, updated_at = ? WHERE tenant_id = ? AND id = ?",
                (new_status, now.isoformat(), tenant_id, order_id),
            )

        try:
            from src.services.dispatch import dispatch_order
            dispatch_order(order_id, tenant_id=tenant_id, force_immediate=True)
        except Exception as e:
            logger.error(f"[Agenda] Error dispatching order #{order_id} on manual activate: {e}")

        return self.get_order_by_id(tenant_id, order_id)

    # ------------------------------------------------------------------
    # Admin Backoffice Methods
    # ------------------------------------------------------------------

    def get_all_products(self, tenant_id: str = "petroil") -> list[Product]:
        """Fetch all products for administration."""
        return self._get_all_products(tenant_id)

    def get_product_by_id(self, tenant_id: str, product_id: str) -> Product | None:
        """Fetch a single product by its id."""
        products = self._get_all_products(tenant_id)
        for p in products:
            if p.id == product_id:
                return p
        return None

    def get_by_id(self, tenant_id: str, product_id: str) -> Product | None:
        """Fetch a single product by its id (protocol alias)."""
        return self.get_product_by_id(tenant_id, product_id)

    def create_product(
        self,
        tenant_id: str,
        id: str,
        name: str,
        description: str,
        price: float,
        currency: str = "MXN",
        category: str = "Cilindros",
        in_stock: bool = True,
        is_promoted: bool = False,
        promotion_text: str = "",
        tags: list[str] | None = None,
        image_url: str = "",
    ) -> Product:
        """Create a new product in the catalog."""
        now_iso = datetime.now(timezone.utc).isoformat()
        tags_json = json.dumps(tags or [])
        clean_id = id.strip().lower().replace(" ", "-")

        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO products (
                    id, tenant_id, name, description, price, currency,
                    category, image_url, tags, in_stock, is_promoted,
                    promotion_text, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_id,
                    tenant_id,
                    name.strip(),
                    description.strip(),
                    float(price),
                    currency,
                    category.strip(),
                    image_url.strip(),
                    tags_json,
                    1 if in_stock else 0,
                    1 if is_promoted else 0,
                    promotion_text.strip(),
                    now_iso,
                ),
            )
        return self.get_by_id(tenant_id, clean_id)

    def update_product(
        self, tenant_id: str, product_id: str, updates: dict[str, Any]
    ) -> Product | None:
        """Update fields of an existing product."""
        prod = self.get_by_id(tenant_id, product_id)
        if not prod:
            return None

        fields = []
        params = []
        for key in ["name", "description", "price", "currency", "category", "image_url", "promotion_text"]:
            if key in updates:
                fields.append(f"{key} = ?")
                params.append(updates[key])

        if "in_stock" in updates:
            fields.append("in_stock = ?")
            params.append(1 if updates["in_stock"] else 0)

        if "is_promoted" in updates:
            fields.append("is_promoted = ?")
            params.append(1 if updates["is_promoted"] else 0)

        if "tags" in updates:
            fields.append("tags = ?")
            params.append(json.dumps(updates["tags"]))

        if not fields:
            return prod

        params.extend([tenant_id, product_id])
        with get_db_connection() as conn:
            conn.execute(
                f"UPDATE products SET {', '.join(fields)} WHERE tenant_id = ? AND id = ?",
                tuple(params),
            )
        return self.get_by_id(tenant_id, product_id)

    def delete_product(self, tenant_id: str, product_id: str) -> bool:
        """Delete a product from the catalog."""
        with get_db_connection() as conn:
            cur = conn.execute(
                "DELETE FROM products WHERE tenant_id = ? AND id = ?",
                (tenant_id, product_id),
            )
            return cur.rowcount > 0

    def get_all_drivers(self, tenant_id: str = "petroil") -> list[Driver]:
        """Fetch all drivers registered in the system."""
        with get_db_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM drivers WHERE tenant_id = ? ORDER BY id ASC",
                (tenant_id,),
            )
            rows = cur.fetchall()
            return [_row_to_driver(r) for r in rows]

    # ------------------------------------------------------------------
    # Vehicles (Unidades Vehiculares / Pipas y Camionetas)
    # ------------------------------------------------------------------

    def create_vehicle(
        self,
        tenant_id: str,
        unit_identifier: str,
        plate: str,
        model: str,
        vehicle_type: str = "camioneta",
        pipa_capacity_liters: float | None = None,
        cylinder_capacity_count: int | None = None,
        status: str = "active",
        notes: str = "",
    ) -> Vehicle:
        """Register a new fleet vehicle in the database."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with get_db_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO vehicles (
                    tenant_id, unit_identifier, plate, model, vehicle_type,
                    pipa_capacity_liters, cylinder_capacity_count, status, notes,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    unit_identifier.strip().upper(),
                    plate.strip().upper(),
                    model.strip(),
                    vehicle_type.strip().lower(),
                    pipa_capacity_liters,
                    cylinder_capacity_count,
                    status.strip().lower(),
                    notes.strip(),
                    now_iso,
                    now_iso,
                ),
            )
            vehicle_id = cur.lastrowid
        return self.get_vehicle(tenant_id, vehicle_id)

    def get_vehicle(self, tenant_id: str, vehicle_id: int) -> Vehicle | None:
        """Fetch a vehicle by ID."""
        with get_db_connection() as conn:
            cur = conn.execute(
                """
                SELECT v.*,
                       d.id as assigned_driver_id,
                       d.name as assigned_driver_name
                FROM vehicles v
                LEFT JOIN drivers d ON d.vehicle_id = v.id
                WHERE v.tenant_id = ? AND v.id = ?
                """,
                (tenant_id, vehicle_id),
            )
            row = cur.fetchone()
            return _row_to_vehicle(row) if row else None

    def get_all_vehicles(self, tenant_id: str = "petroil") -> list[dict[str, Any]]:
        """Fetch all vehicles with their assigned driver details for the Control Tower."""
        with get_db_connection() as conn:
            cur = conn.execute(
                """
                SELECT v.*,
                       d.id as assigned_driver_id,
                       d.name as assigned_driver_name,
                       d.phone as assigned_driver_phone
                FROM vehicles v
                LEFT JOIN drivers d ON d.vehicle_id = v.id
                WHERE v.tenant_id = ?
                ORDER BY v.id ASC
                """,
                (tenant_id,),
            )
            rows = cur.fetchall()
            results = []
            for r in rows:
                v_obj = _row_to_vehicle(r)
                d = v_obj.model_dump()
                d["assigned_driver_phone"] = r["assigned_driver_phone"]
                results.append(d)
            return results

    def update_vehicle(
        self, tenant_id: str, vehicle_id: int, updates: dict[str, Any]
    ) -> Vehicle | None:
        """Update vehicle properties."""
        veh = self.get_vehicle(tenant_id, vehicle_id)
        if not veh:
            return None

        now_iso = datetime.now(timezone.utc).isoformat()
        fields = ["updated_at = ?"]
        params: list[Any] = [now_iso]

        for key in ["unit_identifier", "plate", "model", "vehicle_type", "status", "notes"]:
            if key in updates and updates[key] is not None:
                val = updates[key]
                if key in ["unit_identifier", "plate"]:
                    val = str(val).strip().upper()
                fields.append(f"{key} = ?")
                params.append(val)

        if "pipa_capacity_liters" in updates:
            fields.append("pipa_capacity_liters = ?")
            params.append(updates["pipa_capacity_liters"])

        if "cylinder_capacity_count" in updates:
            fields.append("cylinder_capacity_count = ?")
            params.append(updates["cylinder_capacity_count"])

        params.extend([tenant_id, vehicle_id])
        with get_db_connection() as conn:
            conn.execute(
                f"UPDATE vehicles SET {', '.join(fields)} WHERE tenant_id = ? AND id = ?",
                tuple(params),
            )
        return self.get_vehicle(tenant_id, vehicle_id)

    def delete_vehicle(self, tenant_id: str, vehicle_id: int) -> bool:
        """Delete a vehicle and unlink it from any driver."""
        with get_db_connection() as conn:
            conn.execute("UPDATE drivers SET vehicle_id = NULL WHERE vehicle_id = ?", (vehicle_id,))
            cur = conn.execute("DELETE FROM vehicles WHERE tenant_id = ? AND id = ?", (tenant_id, vehicle_id))
            return cur.rowcount > 0

    def create_driver(
        self,
        tenant_id: str,
        name: str,
        phone: str,
        vehicle_type: str = "cilindros",
        vehicle_plate: str = "",
        zone: str = "General",
        telegram_user_id: str = "",
        vehicle_id: int | None = None,
    ) -> Driver:
        """Create a new driver/vehicle unit."""
        now_iso = datetime.now(timezone.utc).isoformat()
        clean_phone = re.sub(r"\D", "", phone)
        tg_id = telegram_user_id.strip() if telegram_user_id else None

        # Auto-sync with vehicle if vehicle_id is provided
        if vehicle_id:
            veh = self.get_vehicle(tenant_id, vehicle_id)
            if veh:
                vehicle_plate = f"{veh.unit_identifier} ({veh.plate})"
                vehicle_type = "estacionario" if veh.vehicle_type == "pipa" else "cilindros"

        with get_db_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO drivers (
                    tenant_id, name, phone, telegram_user_id, vehicle_id, vehicle_type,
                    vehicle_plate, zone, is_available, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    tenant_id,
                    name.strip(),
                    clean_phone,
                    tg_id,
                    vehicle_id,
                    vehicle_type.strip(),
                    vehicle_plate.strip(),
                    zone.strip(),
                    now_iso,
                    now_iso,
                ),
            )
            driver_id = cur.lastrowid
        return self.get_driver(driver_id)

    def update_driver(self, driver_id: int, updates: dict[str, Any]) -> Driver | None:
        """Update driver profile, vehicle, or status."""
        driver = self.get_driver(driver_id)
        if not driver:
            return None

        # If vehicle_id is updated, auto-sync plate and vehicle_type
        if "vehicle_id" in updates:
            vid = updates["vehicle_id"]
            if vid:
                veh = self.get_vehicle(driver.tenant_id, vid)
                if veh:
                    updates["vehicle_plate"] = f"{veh.unit_identifier} ({veh.plate})"
                    updates["vehicle_type"] = "estacionario" if veh.vehicle_type == "pipa" else "cilindros"

        now_iso = datetime.now(timezone.utc).isoformat()
        fields = ["updated_at = ?"]
        params = [now_iso]

        for key in ["name", "phone", "vehicle_type", "vehicle_plate", "zone", "telegram_user_id", "vehicle_id"]:
            if key in updates:
                fields.append(f"{key} = ?")
                params.append(updates[key])

        if "is_available" in updates:
            fields.append("is_available = ?")
            params.append(1 if updates["is_available"] else 0)

        params.append(driver_id)
        with get_db_connection() as conn:
            conn.execute(
                f"UPDATE drivers SET {', '.join(fields)} WHERE id = ?",
                tuple(params),
            )
        return self.get_driver(driver_id)

    def delete_driver(self, driver_id: int) -> bool:
        """Delete a driver from the system."""
        with get_db_connection() as conn:
            cur = conn.execute("DELETE FROM drivers WHERE id = ?", (driver_id,))
            return cur.rowcount > 0

    def get_all_orders_admin(
        self, tenant_id: str = "petroil", status: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Fetch orders with driver information, item summaries, and rejection notes for Admin UI."""
        self.check_and_activate_scheduled_orders(tenant_id)
        now_dt = datetime.now()

        with get_db_connection() as conn:
            query = """
                SELECT o.*, d.name AS driver_name, d.phone AS driver_phone, d.vehicle_type AS driver_vehicle,
                       (SELECT reason FROM order_rejections WHERE order_id = o.id ORDER BY id DESC LIMIT 1) as rejection_reason,
                       (SELECT driver_name FROM order_rejections WHERE order_id = o.id ORDER BY id DESC LIMIT 1) as rejection_driver_name,
                       (SELECT rating FROM order_ratings WHERE order_id = o.id LIMIT 1) as driver_rating,
                       (SELECT feedback_tag FROM order_ratings WHERE order_id = o.id LIMIT 1) as rating_tag,
                       (SELECT comment FROM order_ratings WHERE order_id = o.id LIMIT 1) as rating_comment
                FROM orders o
                LEFT JOIN drivers d ON o.driver_id = d.id
                WHERE o.tenant_id = ?
            """
            params: list[Any] = [tenant_id]

            if status and status != "all":
                if status == "active":
                    query += " AND o.status IN ('confirmed', 'assigned', 'in_route', 'rejected_by_driver')"
                else:
                    query += " AND o.status = ?"
                    params.append(status)

            query += " ORDER BY o.id DESC LIMIT ?"
            params.append(limit)

            cur = conn.execute(query, tuple(params))
            rows = cur.fetchall()

            result = []
            for r in rows:
                oid = r["id"]
                s_status = r["status"]
                s_for = r["scheduled_for"] if "scheduled_for" in r.keys() else None
                s_schedule = r["delivery_schedule"] or ""

                # If we are viewing active / default orders (not explicitly requesting 'all' or 'scheduled'):
                # Exclude scheduled orders that are still pending activation in the agenda
                if status != "all" and status != "scheduled":
                    if s_status == "scheduled":
                        continue

                items_cur = conn.execute(
                    "SELECT product_name, quantity, unit_price, subtotal FROM order_items WHERE order_id = ?",
                    (oid,),
                )
                items_rows = items_cur.fetchall()
                items = [
                    {
                        "product_name": it["product_name"],
                        "quantity": it["quantity"],
                        "unit_price": it["unit_price"],
                        "subtotal": it["subtotal"],
                    }
                    for it in items_rows
                ]

                result.append({
                    "id": oid,
                    "customer_name": r["customer_name"],
                    "customer_phone": r["customer_phone"],
                    "delivery_address": r["delivery_address"],
                    "delivery_schedule": r["delivery_schedule"],
                    "scheduled_for": s_for,
                    "total_amount": r["total_amount"],
                    "currency": r["currency"],
                    "status": r["status"],
                    "payment_method": r["payment_method"],
                    "notes": r["notes"],
                    "channel": r["channel"],
                    "driver_id": r["driver_id"],
                    "driver_name": r["driver_name"],
                    "driver_phone": r["driver_phone"],
                    "driver_vehicle": r["driver_vehicle"],
                    "driver_rating": r["driver_rating"],
                    "rating_tag": r["rating_tag"],
                    "rating_comment": r["rating_comment"],
                    "rejection_reason": r["rejection_reason"],
                    "rejection_driver_name": r["rejection_driver_name"],
                    "delivery_lat": r["delivery_lat"],
                    "delivery_lng": r["delivery_lng"],
                    "assigned_at": r["assigned_at"],
                    "delivered_at": r["delivered_at"],
                    "created_at": r["created_at"],
                    "items": items,
                })

            return result

    def reassign_order(
        self, tenant_id: str, order_id: int, driver_id: int
    ) -> dict[str, Any] | None:
        """Reassign an order to a new driver manually from the Backoffice."""
        order = self.get_order_by_id(tenant_id, order_id)
        driver = self.get_driver(driver_id)
        if not order or not driver:
            return None
        if order.status == "cancelled":
            return None

        now_iso = datetime.now(timezone.utc).isoformat()
        with get_db_connection() as conn:
            # Release previous driver if assigned and different
            if order.driver_id and order.driver_id != driver_id:
                conn.execute(
                    "UPDATE drivers SET is_available = 1 WHERE id = ?",
                    (order.driver_id,),
                )

            # Assign new driver and reset status to assigned
            conn.execute(
                """
                UPDATE orders
                SET driver_id = ?, status = 'assigned', assigned_at = ?, updated_at = ?
                WHERE tenant_id = ? AND id = ?
                """,
                (driver_id, now_iso, now_iso, tenant_id, order_id),
            )

            # Mark any prior rejection for this order as resolved
            conn.execute(
                "UPDATE order_rejections SET is_resolved = 1 WHERE tenant_id = ? AND order_id = ?",
                (tenant_id, order_id),
            )

        return {
            "success": True,
            "order_id": order_id,
            "driver_id": driver_id,
            "driver_name": driver.name,
        }

    def cancel_all_orders_for_driver(
        self, tenant_id: str, driver_id: int, reason: str = "Cancelación múltiple por chofer"
    ) -> int:
        """Release and cancel all active orders currently assigned to a driver."""
        now_iso = datetime.now(timezone.utc).isoformat()
        driver = self.get_driver(driver_id)
        driver_name = driver.name if driver else f"Chofer #{driver_id}"

        with get_db_connection() as conn:
            cur = conn.execute(
                "SELECT id FROM orders WHERE tenant_id = ? AND driver_id = ? AND status IN ('assigned', 'in_route')",
                (tenant_id, driver_id),
            )
            order_ids = [r["id"] for r in cur.fetchall()]

            for oid in order_ids:
                conn.execute(
                    "UPDATE orders SET status = 'rejected_by_driver', driver_id = NULL, updated_at = ? WHERE tenant_id = ? AND id = ?",
                    (now_iso, tenant_id, oid),
                )
                conn.execute(
                    """
                    INSERT INTO order_rejections (
                        tenant_id, order_id, driver_id, driver_name, reason, is_resolved, created_at
                    ) VALUES (?, ?, ?, ?, ?, 0, ?)
                    """,
                    (tenant_id, oid, driver_id, driver_name, reason, now_iso),
                )

            # Ensure driver is set to available
            conn.execute("UPDATE drivers SET is_available = 1 WHERE id = ?", (driver_id,))
            return len(order_ids)

    def record_order_rejection(
        self, tenant_id: str, order_id: int, driver_id: int, driver_name: str, reason: str
    ) -> dict[str, Any]:
        """Record an incident where a driver rejected or cancelled an assigned order."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with get_db_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO order_rejections (
                    tenant_id, order_id, driver_id, driver_name, reason, is_resolved, created_at
                ) VALUES (?, ?, ?, ?, ?, 0, ?)
                """,
                (tenant_id, order_id, driver_id, driver_name, reason.strip(), now_iso),
            )
            # Update order status to rejected_by_driver and unassign driver
            conn.execute(
                """
                UPDATE orders
                SET driver_id = NULL, status = 'rejected_by_driver', updated_at = ?
                WHERE tenant_id = ? AND id = ?
                """,
                (now_iso, tenant_id, order_id),
            )
            # Release driver to be available
            conn.execute(
                "UPDATE drivers SET is_available = 1 WHERE id = ?",
                (driver_id,),
            )
            rejection_id = cur.lastrowid
            return {
                "id": rejection_id,
                "order_id": order_id,
                "driver_id": driver_id,
                "driver_name": driver_name,
                "reason": reason,
                "is_resolved": 0,
                "created_at": now_iso,
            }

    def get_order_rejections(
        self, tenant_id: str = "petroil", unresolved_only: bool = False
    ) -> list[dict[str, Any]]:
        """Get list of driver rejections with order details for the Control Tower."""
        with get_db_connection() as conn:
            query = """
                SELECT r.*, o.customer_name, o.customer_phone, o.delivery_address, o.total_amount, o.status as order_status,
                       d.phone as driver_phone, d.vehicle_plate as driver_vehicle_plate
                FROM order_rejections r
                LEFT JOIN orders o ON r.order_id = o.id
                LEFT JOIN drivers d ON r.driver_id = d.id
                WHERE r.tenant_id = ?
            """
            params: list[Any] = [tenant_id]
            if unresolved_only:
                query += " AND r.is_resolved = 0"
            query += " ORDER BY r.id DESC LIMIT 100"

            cur = conn.execute(query, tuple(params))
            rows = cur.fetchall()
            return [dict(r) for r in rows]

    def resolve_order_rejections(self, tenant_id: str, order_id: int) -> bool:
        """Mark previous rejections for an order as resolved when reassigned."""
        with get_db_connection() as conn:
            cur = conn.execute(
                "UPDATE order_rejections SET is_resolved = 1 WHERE tenant_id = ? AND order_id = ?",
                (tenant_id, order_id),
            )
            return cur.rowcount > 0

    def get_all_drivers_operational_status(
        self, tenant_id: str = "petroil"
    ) -> list[dict[str, Any]]:
        """Get all drivers with their real-time operational status (disponible, en_entrega, fuera_servicio)."""
        with get_db_connection() as conn:
            cur = conn.execute(
                """
                SELECT d.*, 
                       v.unit_identifier as vehicle_unit_identifier,
                       v.model as vehicle_model,
                       v.pipa_capacity_liters as vehicle_pipa_capacity,
                       v.cylinder_capacity_count as vehicle_cylinder_capacity,
                       (SELECT id FROM orders WHERE driver_id = d.id AND status IN ('assigned', 'in_route') ORDER BY id DESC LIMIT 1) AS active_order_id,
                       (SELECT customer_name FROM orders WHERE driver_id = d.id AND status IN ('assigned', 'in_route') ORDER BY id DESC LIMIT 1) AS active_customer_name,
                       (SELECT delivery_address FROM orders WHERE driver_id = d.id AND status IN ('assigned', 'in_route') ORDER BY id DESC LIMIT 1) AS active_delivery_address,
                       (SELECT status FROM orders WHERE driver_id = d.id AND status IN ('assigned', 'in_route') ORDER BY id DESC LIMIT 1) AS active_order_status,
                       (SELECT check_in_at FROM driver_shifts WHERE driver_id = d.id AND status = 'active' ORDER BY id DESC LIMIT 1) AS shift_check_in_at,
                       (SELECT check_out_at FROM driver_shifts WHERE driver_id = d.id ORDER BY id DESC LIMIT 1) AS last_check_out_at,
                       (SELECT ROUND(AVG(rating), 1) FROM order_ratings WHERE driver_id = d.id) AS avg_rating,
                       (SELECT COUNT(*) FROM order_ratings WHERE driver_id = d.id) AS total_ratings
                FROM drivers d
                LEFT JOIN vehicles v ON d.vehicle_id = v.id
                WHERE d.tenant_id = ?
                ORDER BY d.id ASC
                """,
                (tenant_id,),
            )
            rows = cur.fetchall()
            results = []
            for r in rows:
                has_active = bool(r["active_order_id"])
                is_avail = bool(r["is_available"])

                if has_active:
                    op_status = "en_entrega"
                elif is_avail:
                    op_status = "disponible"
                else:
                    op_status = "fuera_servicio"

                results.append({
                    "id": r["id"],
                    "tenant_id": r["tenant_id"],
                    "name": r["name"],
                    "phone": r["phone"],
                    "telegram_user_id": r["telegram_user_id"],
                    "vehicle_id": r["vehicle_id"],
                    "vehicle_unit_identifier": r["vehicle_unit_identifier"] or "",
                    "vehicle_model": r["vehicle_model"] or "",
                    "vehicle_pipa_capacity": r["vehicle_pipa_capacity"],
                    "vehicle_cylinder_capacity": r["vehicle_cylinder_capacity"],
                    "vehicle_type": r["vehicle_type"] or "cilindros",
                    "vehicle_plate": r["vehicle_plate"] or "",
                    "zone": r["zone"] or "General",
                    "is_available": is_avail,
                    "operational_status": op_status,
                    "active_order_id": r["active_order_id"],
                    "active_customer_name": r["active_customer_name"],
                    "active_delivery_address": r["active_delivery_address"],
                    "active_order_status": r["active_order_status"],
                    "shift_check_in_at": r["shift_check_in_at"],
                    "last_check_out_at": r["last_check_out_at"],
                    "avg_rating": round(float(r["avg_rating"]), 1) if r["avg_rating"] is not None else 5.0,
                    "total_ratings": int(r["total_ratings"] or 0),
                    "current_lat": r["current_lat"],
                    "current_lng": r["current_lng"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                })
            return results

    def get_all_customers_admin(self, tenant_id: str = "petroil") -> list[dict[str, Any]]:
        """Fetch all customers with their addresses and order count for Backoffice."""
        with get_db_connection() as conn:
            cur = conn.execute(
                """
                SELECT c.*, COUNT(o.id) as order_count, SUM(o.total_amount) as total_spent
                FROM customers c
                LEFT JOIN orders o ON c.id = o.customer_id AND o.status = 'delivered'
                WHERE c.tenant_id = ?
                GROUP BY c.id
                ORDER BY c.id DESC
                """,
                (tenant_id,),
            )
            rows = cur.fetchall()

            result = []
            for r in rows:
                cid = r["id"]
                addrs = self.get_customer_addresses(cid)
                result.append({
                    "id": cid,
                    "name": r["name"] or "Sin nombre",
                    "phone": r["phone"] or "",
                    "channel": r["channel"],
                    "channel_user_id": r["channel_user_id"],
                    "address": r["address"] or "",
                    "notes": r["notes"] or "",
                    "order_count": r["order_count"] or 0,
                    "total_spent": r["total_spent"] or 0.0,
                    "created_at": r["created_at"],
                    "addresses": [
                        {
                            "id": a.id,
                            "address": a.address,
                            "alias": a.alias,
                            "is_default": a.is_default,
                        }
                        for a in addrs
                    ],
                })
            return result

    def get_admin_dashboard_metrics(self, tenant_id: str = "petroil") -> dict[str, Any]:
        """Calculate aggregated KPI metrics for the live dashboard."""
        with get_db_connection() as conn:
            # 1. Total orders by status
            cur = conn.execute(
                """
                SELECT
                    COUNT(*) as total_orders,
                    SUM(CASE WHEN status IN ('confirmed', 'assigned', 'in_route') THEN 1 ELSE 0 END) as active_orders,
                    SUM(CASE WHEN status = 'delivered' THEN 1 ELSE 0 END) as delivered_orders,
                    SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) as cancelled_orders,
                    SUM(CASE WHEN status = 'scheduled' THEN 1 ELSE 0 END) as scheduled_orders,
                    SUM(CASE WHEN status = 'rejected_by_driver' THEN 1 ELSE 0 END) as rejected_orders,
                    SUM(CASE WHEN status = 'delivered' THEN total_amount ELSE 0 END) as total_revenue,
                    SUM(CASE WHEN status = 'delivered' AND LOWER(payment_method) LIKE '%efectivo%' THEN total_amount ELSE 0 END) as revenue_cash,
                    SUM(CASE WHEN status = 'delivered' AND (LOWER(payment_method) LIKE '%terminal%' OR LOWER(payment_method) LIKE '%tarjeta%') THEN total_amount ELSE 0 END) as revenue_card
                FROM orders
                WHERE tenant_id = ?
                """,
                (tenant_id,),
            )
            row = cur.fetchone()

            # 2. Driver operational breakdown
            drivers_status = self.get_all_drivers_operational_status(tenant_id)
            total_drivers = len(drivers_status)
            available_drivers = sum(1 for d in drivers_status if d["operational_status"] == "disponible")
            en_entrega_drivers = sum(1 for d in drivers_status if d["operational_status"] == "en_entrega")
            fuera_servicio_drivers = sum(1 for d in drivers_status if d["operational_status"] == "fuera_servicio")

            # 3. Product stats
            p_cur = conn.execute(
                "SELECT COUNT(*) as total_products FROM products WHERE tenant_id = ?",
                (tenant_id,),
            )
            p_row = p_cur.fetchone()

            # 4. Customer count
            c_cur = conn.execute(
                "SELECT COUNT(*) as total_customers FROM customers WHERE tenant_id = ?",
                (tenant_id,),
            )
            c_row = c_cur.fetchone()

            # 5. Unresolved rejections count
            rej_cur = conn.execute(
                "SELECT COUNT(*) as total_rejections FROM order_rejections WHERE tenant_id = ? AND is_resolved = 0",
                (tenant_id,),
            )
            rej_row = rej_cur.fetchone()

            # 6. Customer Satisfaction (CSAT) from order ratings
            csat_cur = conn.execute(
                """
                SELECT 
                    ROUND(AVG(rating), 1) as avg_rating,
                    COUNT(*) as total_ratings
                FROM order_ratings
                WHERE tenant_id = ?
                """,
                (tenant_id,),
            )
            csat_row = csat_cur.fetchone()
            avg_satisfaction = round(float(csat_row["avg_rating"]), 1) if csat_row and csat_row["avg_rating"] is not None else 5.0
            total_ratings_count = int(csat_row["total_ratings"] or 0) if csat_row else 0

            return {
                "total_orders": row["total_orders"] or 0,
                "active_orders": row["active_orders"] or 0,
                "delivered_orders": row["delivered_orders"] or 0,
                "cancelled_orders": row["cancelled_orders"] or 0,
                "scheduled_orders": row["scheduled_orders"] or 0,
                "rejected_orders": row["rejected_orders"] or 0,
                "unresolved_rejections": rej_row["total_rejections"] or 0,
                "total_revenue": row["total_revenue"] or 0.0,
                "revenue_cash": row["revenue_cash"] or 0.0,
                "revenue_card": row["revenue_card"] or 0.0,
                "total_drivers": total_drivers,
                "available_drivers": available_drivers,
                "en_entrega_drivers": en_entrega_drivers,
                "fuera_servicio_drivers": fuera_servicio_drivers,
                "total_products": p_row["total_products"] or 0,
                "total_customers": c_row["total_customers"] or 0,
                "avg_satisfaction": avg_satisfaction,
                "total_ratings": total_ratings_count,
            }

    # -------------------------------------------------------------------------
    # Tank & Pipa Load Readings (Carga Inicial y Carga Final)
    # -------------------------------------------------------------------------

    def save_tank_reading(
        self,
        tenant_id: str,
        driver_id: int,
        driver_name: str,
        vehicle_plate: str,
        reading_type: str,
        reading_value: str,
        photo_path: str | None = None,
        photo_telegram_id: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Record a tank/pipa load reading (initial, final, refill) for a driver shift."""
        with get_db_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO driver_tank_readings (
                    tenant_id, driver_id, driver_name, vehicle_plate,
                    reading_type, reading_value, photo_path, photo_telegram_id, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    driver_id,
                    driver_name,
                    vehicle_plate,
                    reading_type,
                    reading_value,
                    photo_path,
                    photo_telegram_id,
                    notes,
                ),
            )
            reading_id = cur.lastrowid
            row = conn.execute(
                "SELECT * FROM driver_tank_readings WHERE id = ?",
                (reading_id,),
            ).fetchone()
            return dict(row) if row else {}

    def get_tank_readings_by_driver(
        self,
        tenant_id: str,
        driver_id: int,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get chronological tank readings for a specific driver."""
        with get_db_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM driver_tank_readings
                WHERE tenant_id = ? AND driver_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (tenant_id, driver_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_latest_tank_reading(
        self,
        tenant_id: str,
        driver_id: int,
        reading_type: str | None = None,
        shift_date: str | None = None,
    ) -> dict[str, Any] | None:
        """Get the most recent tank reading for a driver, optionally filtered by type or date."""
        with get_db_connection() as conn:
            query = "SELECT * FROM driver_tank_readings WHERE tenant_id = ? AND driver_id = ?"
            params: list[Any] = [tenant_id, driver_id]
            if reading_type:
                query += " AND reading_type = ?"
                params.append(reading_type)
            if shift_date:
                query += " AND shift_date = ?"
                params.append(shift_date)
            query += " ORDER BY id DESC LIMIT 1"

            row = conn.execute(query, tuple(params)).fetchone()
            return dict(row) if row else None

    def get_all_tank_readings(
        self,
        tenant_id: str = "petroil",
        limit: int = 150,
    ) -> list[dict[str, Any]]:
        """Get all tank readings for control tower oversight."""
        with get_db_connection() as conn:
            rows = conn.execute(
                """
                SELECT r.*, d.vehicle_type, d.phone as driver_phone
                FROM driver_tank_readings r
                LEFT JOIN drivers d ON r.driver_id = d.id
                WHERE r.tenant_id = ?
                ORDER BY r.id DESC
                LIMIT ?
                """,
                (tenant_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def update_tank_reading(
        self,
        reading_id: int,
        reading_value: str,
        notes: str | None = None,
    ) -> dict[str, Any] | None:
        """Update the value or notes of a previously recorded tank reading."""
        with get_db_connection() as conn:
            if notes is not None:
                conn.execute(
                    "UPDATE driver_tank_readings SET reading_value = ?, notes = ? WHERE id = ?",
                    (reading_value, notes, reading_id),
                )
            else:
                conn.execute(
                    "UPDATE driver_tank_readings SET reading_value = ? WHERE id = ?",
                    (reading_value, reading_id),
                )
            row = conn.execute(
                "SELECT * FROM driver_tank_readings WHERE id = ?",
                (reading_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_delivered_orders_count_by_driver(
        self,
        tenant_id: str,
        driver_id: int,
        date_str: str | None = None,
    ) -> int:
        """Count orders delivered by driver today or on a specific date."""
        with get_db_connection() as conn:
            if date_str:
                row = conn.execute(
                    """
                    SELECT COUNT(*) as cnt FROM orders 
                    WHERE tenant_id = ? AND driver_id = ? AND status = 'delivered'
                    AND date(created_at) = ?
                    """,
                    (tenant_id, driver_id, date_str),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT COUNT(*) as cnt FROM orders 
                    WHERE tenant_id = ? AND driver_id = ? AND status = 'delivered'
                    AND date(created_at) = date('now', 'localtime')
                    """,
                    (tenant_id, driver_id),
                ).fetchone()
            return row["cnt"] if row else 0

    # -------------------------------------------------------------------------
    # Driver Attendance & Shifts (Hora de Entrada y Salida)
    # -------------------------------------------------------------------------

    def start_driver_shift(
        self,
        tenant_id: str,
        driver_id: int,
        driver_name: str,
        vehicle_plate: str,
        initial_reading: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Record driver check-in (hora de entrada) for a shift session."""
        with get_db_connection() as conn:
            # Check if there's already an active shift today
            existing = conn.execute(
                """
                SELECT * FROM driver_shifts
                WHERE tenant_id = ? AND driver_id = ? AND status = 'active'
                ORDER BY id DESC LIMIT 1
                """,
                (tenant_id, driver_id),
            ).fetchone()

            if existing:
                if initial_reading and not existing["initial_reading"]:
                    conn.execute(
                        "UPDATE driver_shifts SET initial_reading = ? WHERE id = ?",
                        (initial_reading, existing["id"]),
                    )
                    existing = conn.execute("SELECT * FROM driver_shifts WHERE id = ?", (existing["id"],)).fetchone()
                return dict(existing)

            cur = conn.execute(
                """
                INSERT INTO driver_shifts (
                    tenant_id, driver_id, driver_name, vehicle_plate,
                    shift_date, check_in_at, status, initial_reading, notes
                ) VALUES (
                    ?, ?, ?, ?,
                    date('now', 'localtime'), datetime('now', 'localtime'), 'active', ?, ?
                )
                """,
                (tenant_id, driver_id, driver_name, vehicle_plate, initial_reading, notes),
            )
            shift_id = cur.lastrowid
            row = conn.execute("SELECT * FROM driver_shifts WHERE id = ?", (shift_id,)).fetchone()
            return dict(row) if row else {}

    def end_driver_shift(
        self,
        tenant_id: str,
        driver_id: int,
        final_reading: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any] | None:
        """Record driver check-out (hora de salida) and compute shift duration."""
        with get_db_connection() as conn:
            active = conn.execute(
                """
                SELECT * FROM driver_shifts
                WHERE tenant_id = ? AND driver_id = ? AND status = 'active'
                ORDER BY id DESC LIMIT 1
                """,
                (tenant_id, driver_id),
            ).fetchone()

            if active:
                shift_id = active["id"]
                conn.execute(
                    """
                    UPDATE driver_shifts
                    SET check_out_at = datetime('now', 'localtime'),
                        status = 'completed',
                        final_reading = COALESCE(?, final_reading),
                        notes = COALESCE(?, notes),
                        duration_minutes = CAST(ROUND((julianday('now', 'localtime') - julianday(check_in_at)) * 1440) AS INTEGER)
                    WHERE id = ?
                    """,
                    (final_reading, notes, shift_id),
                )
            else:
                # If no open shift was found, create a completed one now
                driver = self.get_driver(driver_id)
                d_name = driver.name if driver else "Chofer"
                v_plate = driver.vehicle_plate if driver else ""
                cur = conn.execute(
                    """
                    INSERT INTO driver_shifts (
                        tenant_id, driver_id, driver_name, vehicle_plate,
                        shift_date, check_in_at, check_out_at, duration_minutes,
                        status, final_reading, notes
                    ) VALUES (
                        ?, ?, ?, ?,
                        date('now', 'localtime'), datetime('now', 'localtime'), datetime('now', 'localtime'), 0,
                        'completed', ?, ?
                    )
                    """,
                    (tenant_id, driver_id, d_name, v_plate, final_reading, notes or "Cierre sin entrada previa"),
                )
                shift_id = cur.lastrowid

            row = conn.execute("SELECT * FROM driver_shifts WHERE id = ?", (shift_id,)).fetchone()
            return dict(row) if row else None

    def get_active_driver_shift(
        self,
        tenant_id: str,
        driver_id: int,
    ) -> dict[str, Any] | None:
        """Get currently active shift for driver if in shift."""
        with get_db_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM driver_shifts
                WHERE tenant_id = ? AND driver_id = ? AND status = 'active'
                ORDER BY id DESC LIMIT 1
                """,
                (tenant_id, driver_id),
            ).fetchone()
            return dict(row) if row else None

    def get_driver_shifts(
        self,
        tenant_id: str,
        driver_id: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get shift history for a driver or all drivers."""
        with get_db_connection() as conn:
            if driver_id:
                rows = conn.execute(
                    """
                    SELECT s.*, d.vehicle_type, d.phone as driver_phone
                    FROM driver_shifts s
                    LEFT JOIN drivers d ON s.driver_id = d.id
                    WHERE s.tenant_id = ? AND s.driver_id = ?
                    ORDER BY s.id DESC LIMIT ?
                    """,
                    (tenant_id, driver_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT s.*, d.vehicle_type, d.phone as driver_phone
                    FROM driver_shifts s
                    LEFT JOIN drivers d ON s.driver_id = d.id
                    WHERE s.tenant_id = ?
                    ORDER BY s.id DESC LIMIT ?
                    """,
                    (tenant_id, limit),
                ).fetchall()
            return [dict(r) for r in rows]

    # -------------------------------------------------------------------------
    # Driver Ratings & Delivery Survey (Calificación de Chofer y Encuesta)
    # -------------------------------------------------------------------------

    def save_order_rating(
        self,
        tenant_id: str,
        order_id: int,
        driver_id: int | None,
        customer_id: int | None,
        rating: int,
        feedback_tag: str = "",
        comment: str = "",
    ) -> dict[str, Any]:
        """Save a new rating and survey response for an order."""
        rating = max(1, min(5, int(rating)))
        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO order_ratings (tenant_id, order_id, driver_id, customer_id, rating, feedback_tag, comment)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, order_id) DO UPDATE SET
                    rating = excluded.rating,
                    feedback_tag = CASE WHEN excluded.feedback_tag != '' THEN excluded.feedback_tag ELSE order_ratings.feedback_tag END,
                    comment = CASE WHEN excluded.comment != '' THEN excluded.comment ELSE order_ratings.comment END,
                    updated_at = datetime('now', 'localtime')
                """,
                (tenant_id, order_id, driver_id, customer_id, rating, feedback_tag, comment),
            )
            row = conn.execute(
                "SELECT * FROM order_ratings WHERE tenant_id = ? AND order_id = ?",
                (tenant_id, order_id),
            ).fetchone()
            return dict(row) if row else {}

    def update_order_rating_feedback(
        self,
        tenant_id: str,
        order_id: int,
        feedback_tag: str | None = None,
        comment: str | None = None,
    ) -> bool:
        """Update the feedback tag or open text comment of an existing order rating."""
        with get_db_connection() as conn:
            clauses = ["updated_at = datetime('now', 'localtime')"]
            params: list[Any] = []
            if feedback_tag is not None:
                clauses.append("feedback_tag = ?")
                params.append(feedback_tag)
            if comment is not None:
                clauses.append("comment = ?")
                params.append(comment)
            params.extend([tenant_id, order_id])
            cur = conn.execute(
                f"UPDATE order_ratings SET {', '.join(clauses)} WHERE tenant_id = ? AND order_id = ?",
                tuple(params),
            )
            return cur.rowcount > 0

    def get_order_rating(self, tenant_id: str, order_id: int) -> dict[str, Any] | None:
        """Get rating and survey details for a specific order."""
        with get_db_connection() as conn:
            row = conn.execute(
                """
                SELECT r.*, d.name as driver_name, c.name as customer_name
                FROM order_ratings r
                LEFT JOIN drivers d ON r.driver_id = d.id
                LEFT JOIN customers c ON r.customer_id = c.id
                WHERE r.tenant_id = ? AND r.order_id = ?
                """,
                (tenant_id, order_id),
            ).fetchone()
            return dict(row) if row else None

    def get_driver_ratings(self, tenant_id: str, driver_id: int, limit: int = 50) -> list[dict[str, Any]]:
        """Get ratings and survey comments received by a specific driver."""
        with get_db_connection() as conn:
            rows = conn.execute(
                """
                SELECT r.*, c.name as customer_name, o.delivery_address, o.total_amount
                FROM order_ratings r
                LEFT JOIN customers c ON r.customer_id = c.id
                LEFT JOIN orders o ON r.order_id = o.id
                WHERE r.tenant_id = ? AND r.driver_id = ?
                ORDER BY r.id DESC LIMIT ?
                """,
                (tenant_id, driver_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_driver_rating_stats(self, tenant_id: str, driver_id: int) -> dict[str, Any]:
        """Get average stars and rating count for a driver."""
        with get_db_connection() as conn:
            row = conn.execute(
                """
                SELECT 
                    ROUND(AVG(rating), 1) as avg_rating,
                    COUNT(*) as total_ratings,
                    SUM(CASE WHEN rating = 5 THEN 1 ELSE 0 END) as stars_5,
                    SUM(CASE WHEN rating = 4 THEN 1 ELSE 0 END) as stars_4,
                    SUM(CASE WHEN rating = 3 THEN 1 ELSE 0 END) as stars_3,
                    SUM(CASE WHEN rating = 2 THEN 1 ELSE 0 END) as stars_2,
                    SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) as stars_1
                FROM order_ratings
                WHERE tenant_id = ? AND driver_id = ?
                """,
                (tenant_id, driver_id),
            ).fetchone()
            if not row or not row["total_ratings"]:
                return {"average": 5.0, "count": 0, "breakdown": {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}}
            return {
                "average": float(row["avg_rating"] or 5.0),
                "count": int(row["total_ratings"] or 0),
                "breakdown": {
                    5: int(row["stars_5"] or 0),
                    4: int(row["stars_4"] or 0),
                    3: int(row["stars_3"] or 0),
                    2: int(row["stars_2"] or 0),
                    1: int(row["stars_1"] or 0),
                },
            }

    def get_all_ratings_admin(self, tenant_id: str = "petroil", limit: int = 100) -> list[dict[str, Any]]:
        """Get all ratings and survey comments for the Control Tower."""
        with get_db_connection() as conn:
            rows = conn.execute(
                """
                SELECT r.*, 
                       d.name as driver_name, 
                       d.vehicle_plate as driver_plate,
                       c.name as customer_name,
                       o.delivery_address, 
                       o.total_amount
                FROM order_ratings r
                LEFT JOIN drivers d ON r.driver_id = d.id
                LEFT JOIN customers c ON r.customer_id = c.id
                LEFT JOIN orders o ON r.order_id = o.id
                WHERE r.tenant_id = ?
                ORDER BY r.id DESC LIMIT ?
                """,
                (tenant_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]




