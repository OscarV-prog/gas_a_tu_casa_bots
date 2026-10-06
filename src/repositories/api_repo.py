"""REST API Repository Adapter for Centralized NestJS + PostgreSQL Backend.

Pure REST API repository with no SQLite dependency when DATA_SOURCE=api.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any
from datetime import datetime, timezone, timedelta

from src.models.customer import Customer, CustomerAddress
from src.models.driver import Driver
from src.models.vehicle import Vehicle
from src.models.order import Order, OrderItem
from src.models.product import Product
from src.repositories.identity_store import identity_store
from src.repositories.sqlite_repo import parse_schedule_deadline, normalize_schedule_datetime, format_schedule_display, to_utc_iso, get_local_now, MAZATLAN_TZ
from src.services.api_client import api_get, api_post, api_patch, api_put, api_delete
from src.services.geocoding import geocode_address, resolve_gps_address_to_name

logger = logging.getLogger(__name__)


class ApiRepository:
    """Repository implementation that communicates exclusively with the centralized NestJS REST API and PostgreSQL."""

    def __init__(self, fallback_repo: Any = None):
        self.fallback_repo = fallback_repo  # None when SQLite is deactivated
        self._last_failure_time: float = 0
        self._cooldown_seconds: float = 10.0
        self._order_id_map: dict[Any, dict] = {}
        self._order_live_locations: dict[str, dict[str, Any]] = {}
        self._order_channel_user_ids: dict[Any, tuple[str, str]] = {}
        self._phone_to_telegram_chat_id: dict[str, str] = {}
        self._order_ratings: dict[str, dict[str, Any]] = {}
        self._order_schedules: dict[str, dict[str, Any]] = {}
        self._driver_locations: dict[str, tuple[float, float]] = {}
        self._order_driver_msg_ids: dict[str, list[int]] = {}

    def bind_telegram_user_phone(self, telegram_user_id: str | int, phone: str) -> None:
        """Bind customer's phone number to their Telegram Chat ID in memory and persistent identity store."""
        if not telegram_user_id or not phone:
            return
        tg_id = str(telegram_user_id).strip()
        clean_phone = re.sub(r"\D", "", str(phone))
        if len(clean_phone) >= 10:
            self._phone_to_telegram_chat_id[clean_phone[-10:]] = tg_id
            self._phone_to_telegram_chat_id[clean_phone] = tg_id
        self._phone_to_telegram_chat_id[tg_id] = tg_id
        identity_store.bind_telegram_user_phone(tg_id, clean_phone)

    def get_telegram_chat_id_for_phone(self, phone: str) -> str | None:
        """Retrieve Telegram Chat ID for a given phone number."""
        clean = re.sub(r"\D", "", str(phone))
        if clean[-10:] in self._phone_to_telegram_chat_id:
            return self._phone_to_telegram_chat_id[clean[-10:]]
        if clean in self._phone_to_telegram_chat_id:
            return self._phone_to_telegram_chat_id[clean]
        return identity_store.get_telegram_chat_id(clean)

    def _resolve_order_uuid(self, order_id: Any) -> str:
        """Resolve integer order ID, numeric string, or orderNumber to the PostgreSQL UUID."""
        if not order_id:
            return ""
        s_id = str(order_id).strip()
        if len(s_id) == 36 and s_id.count("-") == 4:
            return s_id

        if s_id in self._order_id_map:
            cached_id = self._order_id_map[s_id].get("id")
            if cached_id and len(str(cached_id)) == 36:
                return str(cached_id)

        if order_id in self._order_id_map:
            cached_id = self._order_id_map[order_id].get("id")
            if cached_id and len(str(cached_id)) == 36:
                return str(cached_id)

        # Lookup in API orders
        try:
            raw_orders = api_get("/orders", params={"tenantId": "petroil"}, timeout=5)
            if isinstance(raw_orders, list):
                for o in raw_orders:
                    o_num_digits = re.findall(r"\d+", str(o.get("orderNumber") or ""))
                    o_num = int(o_num_digits[-1]) if o_num_digits else None
                    if (
                        str(o.get("id")) == s_id
                        or str(o.get("orderNumber")) == s_id
                        or (o_num is not None and str(o_num) == s_id)
                    ):
                        self._order_id_map[s_id] = o
                        self._order_id_map[str(o.get("id"))] = o
                        return str(o.get("id"))
        except Exception:
            pass

        return s_id

    def _should_skip_api(self) -> bool:
        """Check if remote API circuit breaker is active."""
        if not self._last_failure_time:
            return False
        return (time.time() - self._last_failure_time) < self._cooldown_seconds

    def _record_api_failure(self, error: Exception) -> None:
        """Record connection failure timestamp."""
        self._last_failure_time = time.time()
        logger.warning(f"[ApiRepository] Remote API error: {error}. Circuit cooldown {self._cooldown_seconds}s.")

    def _record_api_success(self) -> None:
        """Reset circuit breaker on successful response."""
        self._last_failure_time = 0

    # -------------------------------------------------------------------------
    # Products / Catalog
    # -------------------------------------------------------------------------

    def get_all_products(self, tenant_id: str = "petroil") -> list[Product]:
        """Fetch all available products from the NestJS REST API."""
        try:
            raw_products = api_get("/products", params={"tenantId": tenant_id}, timeout=5)
            if isinstance(raw_products, list):
                products = []
                for p in raw_products:
                    # Filtrar por tenant si el objeto lo incluye
                    p_tenant = p.get("tenantId", tenant_id)
                    if p_tenant and p_tenant != tenant_id:
                        continue

                    pid = str(p.get("id") or p.get("productId") or "")
                    name = str(p.get("name") or "")
                    price = float(p.get("pricePerUnit") or p.get("price") or 0.0)
                    category = str(p.get("category") or "CILINDRO")
                    unit = str(p.get("unitType") or p.get("unit") or "pieza")
                    desc = str(p.get("description") or f"{name} - ${price:.2f}")
                    in_stock = bool(p.get("isAvailable", p.get("in_stock", True)))
                    is_promo = bool(p.get("isPromotion", False))
                    promo_desc = float(p.get("promoDiscount", 0.0))

                    products.append(
                        Product(
                            id=pid,
                            tenant_id=tenant_id,
                            name=name,
                            description=desc,
                            price=price,
                            currency="MXN",
                            category=category,
                            unit=unit,
                            in_stock=in_stock,
                            is_promotion=is_promo,
                            promo_discount=promo_desc,
                        )
                    )
                if products:
                    self._record_api_success()
                    return products
        except Exception as e:
            self._record_api_failure(e)

        if self.fallback_repo:
            return self.fallback_repo.get_all_products(tenant_id)
        return []

    def search(self, tenant_id: str, query: str) -> list[Product]:
        """Search products by name, category or description keywords."""
        all_prods = self.get_all_products(tenant_id)
        if not query or not query.strip():
            return all_prods

        q_clean = query.lower().strip()
        matches = []
        for p in all_prods:
            if (
                q_clean in p.name.lower()
                or q_clean in p.description.lower()
                or q_clean in p.category.lower()
                or (q_clean.isdigit() and f"{q_clean} kg" in p.name.lower())
            ):
                matches.append(p)

        return matches or all_prods

    def get_product_by_id(self, tenant_id: str, product_id: str) -> Product | None:
        """Lookup a product by ID or name."""
        for p in self.get_all_products(tenant_id):
            if p.id == product_id or (product_id.lower() in p.id.lower()) or (product_id.lower() in p.name.lower()):
                return p
        if self.fallback_repo:
            return self.fallback_repo.get_product_by_id(tenant_id, product_id)
        return None

    def get_promotions(self, tenant_id: str) -> list[Product]:
        """Get active promotions from PostgreSQL."""
        return [p for p in self.get_all_products(tenant_id) if getattr(p, "is_promotion", False)]

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
        """Create a new product in remote API and local SQLite fallback."""
        try:
            body = {
                "id": id,
                "tenantId": tenant_id,
                "name": name,
                "description": description,
                "price": price,
                "pricePerUnit": price,
                "currency": currency,
                "category": category,
                "in_stock": in_stock,
                "isAvailable": in_stock,
                "isPromotion": is_promoted,
                "promotion_text": promotion_text,
                "tags": tags or [],
                "image_url": image_url,
            }
            api_post("/products", body, timeout=5)
        except Exception:
            pass

        if self.fallback_repo:
            return self.fallback_repo.create_product(
                tenant_id=tenant_id,
                id=id,
                name=name,
                description=description,
                price=price,
                currency=currency,
                category=category,
                in_stock=in_stock,
                is_promoted=is_promoted,
                promotion_text=promotion_text,
                tags=tags,
                image_url=image_url,
            )

        return Product(
            id=id,
            tenant_id=tenant_id,
            name=name,
            description=description,
            price=price,
            currency=currency,
            category=category,
            in_stock=in_stock,
            is_promotion=is_promoted,
            promotion_text=promotion_text,
            tags=tags or [],
            image_url=image_url,
        )

    def update_product(
        self, tenant_id: str, product_id: str, updates: dict[str, Any]
    ) -> Product | None:
        """Update an existing product."""
        try:
            api_patch(f"/products/{product_id}", updates, timeout=5)
        except Exception:
            pass

        if self.fallback_repo:
            return self.fallback_repo.update_product(tenant_id, product_id, updates)
        return None

    def delete_product(self, tenant_id: str, product_id: str) -> bool:
        """Delete a product from the catalog."""
        try:
            api_delete(f"/products/{product_id}", timeout=5)
        except Exception:
            pass

        if self.fallback_repo:
            return self.fallback_repo.delete_product(tenant_id, product_id)
        return True

    # -------------------------------------------------------------------------
    # Customers
    # -------------------------------------------------------------------------

    def get_customer_by_phone(self, tenant_id: str, phone: str) -> Customer | None:
        """Lookup customer profile by 10-digit phone number in PostgreSQL API."""
        clean_phone = re.sub(r"\D", "", phone) if phone else ""
        if clean_phone.startswith("521") and len(clean_phone) == 13:
            clean_phone = clean_phone[3:]
        elif clean_phone.startswith("52") and len(clean_phone) == 12:
            clean_phone = clean_phone[2:]
        if len(clean_phone) > 10:
            clean_phone = clean_phone[-10:]

        if not clean_phone:
            return None

        try:
            res = api_get("/customers", params={"tenantId": tenant_id}, timeout=5)
            matching_customers = []
            if isinstance(res, list):
                # Filtrar con precisión por el número de teléfono del cliente
                for c_data in res:
                    raw_phone = re.sub(r"\D", "", str(c_data.get("phone", "")))
                    if raw_phone.startswith("521") and len(raw_phone) == 13:
                        raw_phone = raw_phone[3:]
                    elif raw_phone.startswith("52") and len(raw_phone) == 12:
                        raw_phone = raw_phone[2:]
                    if len(raw_phone) > 10:
                        raw_phone = raw_phone[-10:]

                    if raw_phone == clean_phone:
                        matching_customers.append(c_data)

            if matching_customers:
                self._record_api_success()
                # Priorizar el registro que ya tenga direcciones o que sea más reciente
                matching_customers.sort(
                    key=lambda c: (
                        len(c.get("addresses") or []),
                        len(str(c.get("address") or "")),
                        str(c.get("createdAt") or ""),
                    ),
                    reverse=True,
                )
                primary_c = matching_customers[0]
                cust = self._parse_api_customer(primary_c, tenant_id, clean_phone)

                # Unificar direcciones de cualquier otro perfil del mismo teléfono
                existing_addrs_set = {a.address.strip().lower() for a in cust.addresses}
                for other in matching_customers[1:]:
                    for oa in (other.get("addresses") or []):
                        oa_str = (oa.get("address") if isinstance(oa, dict) else str(oa)) or ""
                        if oa_str and oa_str.strip().lower() not in existing_addrs_set:
                            if not identity_store.is_address_deleted(clean_phone, oa_str):
                                existing_addrs_set.add(oa_str.strip().lower())
                                cust.addresses.append(
                                    CustomerAddress(
                                        id=oa.get("id") if isinstance(oa, dict) else len(cust.addresses) + 1,
                                        customer_id=cust.id,
                                        address=oa_str.strip(),
                                        alias=f"Dirección {len(cust.addresses) + 1}",
                                        is_default=False,
                                    )
                                )
                    other_main = (other.get("address") or "").strip()
                    if other_main and other_main.lower() not in existing_addrs_set:
                        if not cust.addresses and not identity_store.is_address_deleted(clean_phone, other_main):
                            existing_addrs_set.add(other_main.lower())
                            cust.addresses.append(
                                CustomerAddress(
                                    id=len(cust.addresses) + 1,
                                    customer_id=cust.id,
                                    address=other_main,
                                    alias=f"Dirección {len(cust.addresses) + 1}",
                                    is_default=False,
                                )
                            )
                return cust

            elif isinstance(res, dict) and res.get("name"):
                raw_phone = re.sub(r"\D", "", str(res.get("phone", "")))
                if raw_phone == clean_phone or not raw_phone:
                    self._record_api_success()
                    return self._parse_api_customer(res, tenant_id, clean_phone)
        except Exception as e:
            self._record_api_failure(e)

        if self.fallback_repo:
            return self.fallback_repo.get_customer_by_phone(tenant_id, phone)
        return None

    def get_customer(self, tenant_id: str, channel: str, channel_user_id: str) -> Customer | None:
        """Lookup customer by channel and user ID."""
        from src.repositories.identity_store import identity_store
        mapped_phone = identity_store.get_phone_for_channel_user(channel, str(channel_user_id))
        if mapped_phone:
            cust = self.get_customer_by_phone(tenant_id, mapped_phone)
            if cust:
                return cust
        if str(channel).lower() in ("whatsapp", "phone", "call"):
            clean_uid = re.sub(r"\D", "", str(channel_user_id))
            if len(clean_uid) >= 10:
                cust = self.get_customer_by_phone(tenant_id, clean_uid[-10:])
                if cust:
                    return cust
        if self.fallback_repo:
            return self.fallback_repo.get_customer(tenant_id, channel, channel_user_id)
        return None

    def get_customer_addresses(self, customer_id: Any) -> list[CustomerAddress]:
        """Fetch saved customer addresses."""
        if not customer_id:
            return []
        try:
            res = api_get(f"/customers/{customer_id}/addresses", timeout=5)
            if isinstance(res, list) and res:
                results = []
                for i, a in enumerate(res, 1):
                    if isinstance(a, dict) and a.get("address"):
                        results.append(
                            CustomerAddress(
                                id=a.get("id") or i,
                                customer_id=customer_id,
                                address=a.get("address"),
                                alias=a.get("alias") or f"Dirección {i}",
                                notes=a.get("notes") or "",
                                is_default=bool(a.get("isDefault", i == 1)),
                                created_at=a.get("createdAt"),
                                updated_at=a.get("updatedAt"),
                            )
                        )
                if results:
                    return results
        except Exception as e:
            logger.debug(f"[ApiRepository] get_customer_addresses error: {e}")

        # Fallback a consultar en /customers
        try:
            res = api_get("/customers", timeout=5)
            if isinstance(res, list):
                for c in res:
                    if str(c.get("id")) == str(customer_id) or str(c.get("phone")) == str(customer_id):
                        cust = self._parse_api_customer(c, "petroil", str(c.get("phone", "")))
                        return cust.addresses
        except Exception:
            pass

        if self.fallback_repo:
            return self.fallback_repo.get_customer_addresses(customer_id)
        return []

    def add_customer_address(
        self,
        customer_id: Any,
        address: str,
        alias: str = "",
        notes: str = "",
        is_default: bool = False,
    ) -> CustomerAddress:
        """Add a new delivery address for a customer in PostgreSQL API without replacing existing ones."""
        clean_addr = resolve_gps_address_to_name(address.strip())
        if not clean_addr:
            return CustomerAddress(id=1, customer_id=customer_id, address=address)

        existing = self.get_customer_addresses(customer_id)
        for ea in existing:
            if ea.address.strip().lower() == clean_addr.lower():
                return ea

        count = len(existing)
        if count == 0:
            is_default = True
        if not alias:
            alias = "Principal" if is_default else f"Dirección {count + 1}"

        body = {
            "address": clean_addr,
            "alias": alias,
            "notes": notes.strip() if notes else None,
            "isDefault": is_default,
        }
        try:
            res = api_post(f"/customers/{customer_id}/addresses", body, timeout=5)
            if isinstance(res, dict) and res.get("id"):
                new_ca = CustomerAddress(
                    id=res.get("id"),
                    customer_id=customer_id,
                    address=clean_addr,
                    alias=alias,
                    notes=notes.strip() if notes else "",
                    is_default=is_default,
                    created_at=res.get("createdAt"),
                    updated_at=res.get("updatedAt"),
                )
                if self.fallback_repo:
                    try:
                        self.fallback_repo.add_customer_address(customer_id, clean_addr, alias=alias, notes=notes, is_default=is_default)
                    except Exception:
                        pass
                return new_ca
        except Exception as e:
            logger.warning(f"[ApiRepository] Failed to add customer address via API: {e}")

        if self.fallback_repo:
            return self.fallback_repo.add_customer_address(customer_id, clean_addr, alias=alias, notes=notes, is_default=is_default)

        return CustomerAddress(
            id=count + 1,
            customer_id=customer_id,
            address=clean_addr,
            alias=alias,
            notes=notes.strip() if notes else "",
            is_default=is_default,
        )

    def save_or_update_customer(
        self,
        tenant_id: str,
        channel: str,
        channel_user_id: str,
        name: str,
        phone: str = "",
        address: str = "",
        **kwargs: Any,
    ) -> Customer:
        """Create or update customer profile in PostgreSQL without replacing saved addresses."""
        clean_phone = re.sub(r"\D", "", phone) if phone else ""
        if len(clean_phone) > 10:
            clean_phone = clean_phone[-10:]

        customer_type = (channel or "TELEGRAM").upper()
        lat = kwargs.get("latitude") or kwargs.get("delivery_lat")
        lng = kwargs.get("longitude") or kwargs.get("delivery_lng")
        if (lat is None or lng is None or float(lat) == 0.0) and address:
            try:
                g_lat, g_lng, _ = geocode_address(address, city_context="Mazatlán")
                if g_lat and g_lng:
                    lat, lng = g_lat, g_lng
            except Exception:
                pass

        phone_val = clean_phone or channel_user_id
        if phone_val and not str(phone_val).startswith("+") and len(str(phone_val)) == 10:
            formatted_phone = f"+52{phone_val}"
        else:
            formatted_phone = phone_val

        body = {
            "tenantId": tenant_id,
            "name": name,
            "phone": formatted_phone or clean_phone or channel_user_id,
            "address": address or "Mazatlán",
            "colonia": "Mazatlán",
            "city": "Mazatlán",
            "customerType": customer_type,
        }
        if lat is not None and lng is not None:
            body["latitude"] = float(lat)
            body["longitude"] = float(lng)

        try:
            res = api_post("/customers/identify-or-create", body, timeout=5)
            if isinstance(res, dict) and res.get("id"):
                cid = res.get("id")
                # Si se proporcionó una dirección nueva y válida, añadirla a la libreta de direcciones sin sobreescribir
                if address and address.strip():
                    self.add_customer_address(cid, address.strip(), notes=kwargs.get("notes") or "")
                return self._parse_api_customer(res, tenant_id, clean_phone or channel_user_id)
        except Exception as e:
            logger.debug(f"[ApiRepository] save_or_update_customer API note: {e}")

        if self.fallback_repo:
            return self.fallback_repo.save_or_update_customer(tenant_id, channel, channel_user_id, name, phone, address, **kwargs)

        return Customer(
            id=1,
            tenant_id=tenant_id,
            channel=channel,
            channel_user_id=channel_user_id,
            name=name,
            phone=clean_phone or channel_user_id,
            address=address,
            addresses=[CustomerAddress(id=1, address=address, alias="Principal")] if address else [],
        )

    def delete_customer_address(
        self,
        customer_id: Any,
        address_id: Any,
        phone: str = "",
        address_text: str = "",
    ) -> bool:
        """Delete customer address in PostgreSQL API and track permanent deletion."""
        from src.repositories.identity_store import identity_store

        clean_p = re.sub(r"\D", "", str(phone or ""))
        if len(clean_p) > 10:
            clean_p = clean_p[-10:]

        target_text = (address_text or "").strip()
        target_uuid = str(address_id or "").strip()

        # If we have an integer or non-UUID id, or need to discover address text
        try:
            direct_addrs = api_get(f"/customers/{customer_id}/addresses", timeout=5)
            if isinstance(direct_addrs, list):
                for a in direct_addrs:
                    if isinstance(a, dict):
                        aid = str(a.get("id") or "")
                        atext = (a.get("address") or "").strip()
                        if aid == target_uuid or (target_text and atext.lower() == target_text.lower()):
                            target_uuid = aid
                            if not target_text:
                                target_text = atext
                            break
        except Exception:
            pass

        # Execute API deletion if it's a UUID
        if target_uuid and len(target_uuid) > 10 and "-" in target_uuid:
            try:
                api_delete(f"/customers/{customer_id}/addresses/{target_uuid}", timeout=5)
                logger.info(f"[ApiRepository] Address {target_uuid} deleted from NestJS API.")
            except Exception as e:
                logger.warning(f"[ApiRepository] Failed to delete customer address via API: {e}")

        # Mark in identity_store to guarantee it is NEVER resurrected
        if target_text:
            if clean_p:
                identity_store.mark_address_deleted(clean_p, target_text)
            else:
                for p in list(identity_store._phone_to_tg.keys()):
                    if len(p) == 10:
                        identity_store.mark_address_deleted(p, target_text)

        if self.fallback_repo:
            try:
                self.fallback_repo.delete_customer_address(customer_id, address_id)
            except Exception:
                pass
        return True

    def _parse_api_customer(self, data: dict, tenant_id: str, phone: str) -> Customer:
        from src.repositories.identity_store import identity_store

        cid = data.get("id")
        name = data.get("name") or data.get("customerName") or "Cliente"
        raw_addrs = data.get("addresses") or []
        addrs = []
        if isinstance(raw_addrs, list) and raw_addrs:
            for i, a in enumerate(raw_addrs, 1):
                if isinstance(a, dict):
                    addr_str = (a.get("address") or "").strip()
                    if addr_str and not identity_store.is_address_deleted(phone, addr_str):
                        addrs.append(
                            CustomerAddress(
                                id=a.get("id") or i,
                                customer_id=cid,
                                address=addr_str,
                                alias=a.get("alias") or f"Dirección {i}",
                                notes=a.get("notes") or "",
                                is_default=bool(a.get("isDefault", i == 1)),
                                created_at=a.get("createdAt"),
                                updated_at=a.get("updatedAt"),
                            )
                        )
                elif isinstance(a, str):
                    addr_str = a.strip()
                    if addr_str and not identity_store.is_address_deleted(phone, addr_str):
                        addrs.append(CustomerAddress(id=i, customer_id=cid, address=addr_str, alias=f"Dirección {i}"))

        # Si el listado de direcciones vino vacío desde el resumen, consultar endpoint directo
        if not addrs and cid:
            try:
                direct_addrs = api_get(f"/customers/{cid}/addresses", timeout=5)
                if isinstance(direct_addrs, list) and direct_addrs:
                    for i, a in enumerate(direct_addrs, 1):
                        if isinstance(a, dict) and a.get("address"):
                            addr_str = (a.get("address") or "").strip()
                            if addr_str and not identity_store.is_address_deleted(phone, addr_str):
                                addrs.append(
                                    CustomerAddress(
                                        id=a.get("id") or i,
                                        customer_id=cid,
                                        address=addr_str,
                                        alias=a.get("alias") or f"Dirección {i}",
                                        notes=a.get("notes") or "",
                                        is_default=bool(a.get("isDefault", i == 1)),
                                        created_at=a.get("createdAt"),
                                        updated_at=a.get("updatedAt"),
                                    )
                                )
            except Exception:
                pass

        default_addr = (data.get("address") or "").strip()
        if default_addr and identity_store.is_address_deleted(phone, default_addr):
            default_addr = ""

        # Solo si la libreta de direcciones está totalmente vacía y default_addr no está eliminada, usarla
        if not addrs and default_addr and not identity_store.is_address_deleted(phone, default_addr):
            addrs.append(CustomerAddress(id=1, customer_id=cid, address=default_addr, alias="Principal", is_default=True))

        active_default = default_addr or (addrs[0].address if addrs else "")

        return Customer(
            id=cid,
            tenant_id=tenant_id,
            channel="api",
            channel_user_id=phone,
            name=name,
            phone=phone,
            address=active_default,
            addresses=addrs,
        )

    # -------------------------------------------------------------------------
    # Orders
    # -------------------------------------------------------------------------

    def _map_api_status_to_local(self, api_status: str | None) -> str:
        """Map NestJS uppercase Spanish status to local standard status slug."""
        if not api_status:
            return "confirmed"
        s = str(api_status).upper().strip().replace(" ", "_")
        status_map = {
            "PENDIENTE": "confirmed",
            "PENDING": "confirmed",
            "CONFIRMADO": "confirmed",
            "CONFIRMED": "confirmed",
            "ASIGNADO": "assigned",
            "ASSIGNED": "assigned",
            "EN_RUTA": "in_route",
            "EN_REPARTO": "in_route",
            "EN_CAMINO": "in_route",
            "IN_ROUTE": "in_route",
            "ENTREGADO": "delivered",
            "DELIVERED": "delivered",
            "CANCELADO": "cancelled",
            "CANCELLED": "cancelled",
            "PROGRAMADO": "scheduled",
            "SCHEDULED": "scheduled",
            "RECHAZADO": "rejected_by_driver",
            "RECHAZADO_POR_CHOFER": "rejected_by_driver",
            "REJECTED_BY_DRIVER": "rejected_by_driver",
        }
        return status_map.get(s, s.lower())

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
        channel: str = "telegram",
        channel_user_id: str = "",
        customer_id: Any = None,
        delivery_lat: float | None = None,
        delivery_lng: float | None = None,
        scheduled_for: str | None = None,
        **kwargs: Any,
    ) -> Order:
        """Create a new order in NestJS API + PostgreSQL."""
        prods = self.get_all_products(tenant_id)
        prods_by_id = {p.id: p for p in prods}
        prods_by_name = {p.name.lower(): p for p in prods}

        api_items = []
        total_calc = 0.0
        clean_items_for_local = []

        for it in items:
            p_id = str(it.get("product_id") or it.get("productId") or "")
            p_name = str(it.get("product_name") or it.get("name") or "")
            try:
                raw_qty = float(it.get("quantity") or it.get("qty") or 1)
            except (ValueError, TypeError):
                raw_qty = 1.0

            # Match against remote product UUID
            matched_prod = prods_by_id.get(p_id) or prods_by_name.get(p_name.lower())
            if not matched_prod:
                for p in prods:
                    if p.name.lower() in p_name.lower() or p_name.lower() in p.name.lower():
                        matched_prod = p
                        break
            if not matched_prod and prods:
                for p in prods:
                    if "30" in p.name:
                        matched_prod = p
                        break
                if not matched_prod:
                    matched_prod = prods[0]

            if matched_prod:
                real_p_id = matched_prod.id
                prod_name_clean = matched_prod.name
                price = matched_prod.price
            else:
                real_p_id = p_id or "945c5de8-a30e-4c0e-b6f5-909c37e9a617"
                prod_name_clean = p_name or "Cilindro de Gas LP 30 kg"
                price = float(it.get("unit_price") or 705.0)

            is_stationary = (
                matched_prod and (
                    "estacionario" in matched_prod.name.lower()
                    or "litro" in str(getattr(matched_prod, "unit", "")).lower()
                    or str(getattr(matched_prod, "category", "")).upper() == "ESTACIONARIO"
                )
            ) or ("estacionario" in p_name.lower() or "litro" in p_name.lower())

            incoming_price = float(it.get("unit_price") or it.get("price") or 0.0)
            if is_stationary and incoming_price > (price * 1.5) and raw_qty <= 5.0:
                raw_qty = round(incoming_price / price, 2)

            qty = int(raw_qty) if raw_qty.is_integer() else round(raw_qty, 2)
            subtotal = round(price * qty, 2)
            total_calc += subtotal
            api_items.append({"productId": str(real_p_id), "quantity": qty})
            clean_items_for_local.append({
                "product_id": real_p_id,
                "product_name": prod_name_clean,
                "quantity": qty,
                "unit_price": price,
                "subtotal": subtotal,
            })

        now_dt = get_local_now()
        sched_text = str(delivery_schedule or "").strip().lower()
        has_asap_text = any(w in sched_text for w in [
            "lo antes posible", "inmediato", "urgente", "ahorita", "ahora", "asap",
            "lo mas pronto", "lo más pronto", "ya mismo", "ya", "en cuanto puedan", "cuanto antes"
        ]) or (not delivery_schedule) or (delivery_schedule.strip() == "Lo antes posible")

        deadline_dt = None
        if not has_asap_text:
            if scheduled_for and str(scheduled_for).strip():
                deadline_dt = normalize_schedule_datetime(scheduled_for, now_dt)
            elif delivery_schedule and delivery_schedule.strip() != "Lo antes posible":
                deadline_dt = normalize_schedule_datetime(delivery_schedule, now_dt)

        if deadline_dt and deadline_dt > (now_dt + timedelta(minutes=15)):
            is_scheduled = True
            scheduled_for_iso = to_utc_iso(deadline_dt, now_dt)
            if not delivery_schedule or delivery_schedule == "Lo antes posible":
                delivery_schedule = format_schedule_display(deadline_dt, now_dt)
        else:
            is_scheduled = False
            deadline_dt = None
            scheduled_for_iso = None
            delivery_schedule = "Lo antes posible"

        clean_pay = "EFECTIVO" if "efectivo" in payment_method.lower() else ("TARJETA" if "tarjeta" in payment_method.lower() or "terminal" in payment_method.lower() else "EFECTIVO")
        clean_channel = channel.upper() if channel else "TELEGRAM"

        if (delivery_lat is None or delivery_lng is None or float(delivery_lat) == 0.0) and delivery_address:
            try:
                g_lat, g_lng, _ = geocode_address(delivery_address, city_context="Mazatlán")
                if g_lat and g_lng:
                    delivery_lat, delivery_lng = g_lat, g_lng
            except Exception:
                pass

        order_type = "SCHEDULED" if (is_scheduled or (scheduled_for_iso and deadline_dt and deadline_dt > now_dt)) else "ASAP"
        body = {
            "tenantId": tenant_id,
            "type": order_type,
            "customerName": customer_name,
            "customerPhone": customer_phone,
            "deliveryAddress": delivery_address,
            "colonia": "Mazatlán",
            "city": "Mazatlán",
            "channel": clean_channel,
            "paymentMethod": clean_pay,
            "notes": notes or "",
            "scheduledFor": scheduled_for_iso,
            "deliverySchedule": delivery_schedule,
            "status": "PROGRAMADO" if is_scheduled else "PENDIENTE",
            "items": api_items,
        }
        if api_items:
            body["productId"] = api_items[0].get("productId")
            body["quantity"] = api_items[0].get("quantity", 1)

        # Sincronizar dirección del cliente en NestJS/PostgreSQL para que en PWA no aparezca dirección vieja
        try:
            cust_synced = self.save_or_update_customer(
                tenant_id=tenant_id,
                channel=channel,
                channel_user_id=channel_user_id or customer_phone,
                name=customer_name,
                phone=customer_phone,
                address=delivery_address,
                lat=delivery_lat,
                lng=delivery_lng,
                notes=notes,
            )
            if cust_synced and cust_synced.id and re.match(r"^[0-9a-fA-F-]{36}$", str(cust_synced.id)):
                body["customerId"] = str(cust_synced.id)
        except Exception as e:
            logger.debug(f"[ApiRepository] Failed to sync customer profile on order create: {e}")

        if "customerId" not in body:
            if customer_id and re.match(r"^[0-9a-fA-F-]{36}$", str(customer_id)):
                body["customerId"] = str(customer_id)
            else:
                try:
                    cust_found = self.get_customer_by_phone(tenant_id, customer_phone)
                    if cust_found and cust_found.id and re.match(r"^[0-9a-fA-F-]{36}$", str(cust_found.id)):
                        body["customerId"] = str(cust_found.id)
                except Exception:
                    pass
        if delivery_lat is not None and delivery_lng is not None:
            body["latitude"] = float(delivery_lat)
            body["longitude"] = float(delivery_lng)
            body["deliveryLat"] = float(delivery_lat)
            body["deliveryLng"] = float(delivery_lng)

        # Backup local sync in SQLite
        local_order = None
        if self.fallback_repo:
            try:
                local_order = self.fallback_repo.create_order(
                    tenant_id=tenant_id,
                    customer_name=customer_name,
                    customer_phone=customer_phone,
                    delivery_address=delivery_address,
                    items=clean_items_for_local,
                    delivery_schedule=delivery_schedule,
                    payment_method=payment_method,
                    notes=notes,
                    channel=channel,
                    channel_user_id=channel_user_id,
                    customer_id=customer_id,
                    delivery_lat=delivery_lat,
                    delivery_lng=delivery_lng,
                    scheduled_for=scheduled_for_iso,
                )
            except Exception as e:
                logger.debug(f"[ApiRepository] Local SQLite mirror error: {e}")

        try:
            res = api_post("/orders", body, timeout=5)
            if isinstance(res, dict) and res.get("id"):
                self._record_api_success()
                logger.info(f"[ApiRepository] Order created in NestJS API: ID={res.get('id')}, OrderNumber={res.get('orderNumber')}")
                if channel:
                    res["channel"] = channel
                if channel_user_id:
                    res["channelUserId"] = str(channel_user_id)
                    res["channel_user_id"] = str(channel_user_id)
                if customer_phone:
                    res["customerPhone"] = customer_phone
                    clean_phone = re.sub(r"\D", "", customer_phone)
                    if len(clean_phone) >= 10 and channel_user_id and str(channel).lower() == "telegram":
                        self.bind_telegram_user_phone(str(channel_user_id), clean_phone[-10:])
                if notes:
                    res["notes"] = notes
                if scheduled_for_iso:
                    res["scheduledFor"] = scheduled_for_iso
                if delivery_schedule:
                    res["deliverySchedule"] = delivery_schedule
                if is_scheduled:
                    res["status"] = "PROGRAMADO"
                    try:
                        api_patch(f"/orders/{res['id']}/status", {
                            "status": "PROGRAMADO",
                            "scheduledFor": scheduled_for_iso,
                            "description": f"Pedido Agendado para {delivery_schedule}",
                            "actor": "SISTEMA_IA",
                        }, timeout=5)
                        logger.info(f"[ApiRepository] Order #{res.get('orderNumber')} status confirmed as PROGRAMADO in NestJS DB.")
                    except Exception as e_stat:
                        logger.warning(f"[ApiRepository] Could not patch PROGRAMADO status to NestJS for Order #{res.get('orderNumber')}: {e_stat}")

                parsed_ord = self._parse_api_order(res, tenant_id)
                if is_scheduled:
                    parsed_ord.status = "scheduled"
                    parsed_ord.scheduled_for = scheduled_for_iso
                    parsed_ord.delivery_schedule = delivery_schedule

                if delivery_schedule or scheduled_for_iso:
                    for k in (parsed_ord.id, str(parsed_ord.id), str(res.get("id")), str(res.get("orderNumber"))):
                        if k:
                            self._order_schedules[str(k)] = {
                                "delivery_schedule": delivery_schedule,
                                "scheduled_for": scheduled_for_iso,
                            }
                            identity_store.save_order_schedule(k, delivery_schedule, scheduled_for_iso)

                if channel_user_id:
                    parsed_ord.channel = channel
                    parsed_ord.channel_user_id = str(channel_user_id)
                    for k in (parsed_ord.id, str(parsed_ord.id), str(res.get("id")), str(res.get("orderNumber"))):
                        if k:
                            self._order_channel_user_ids[k] = (channel, str(channel_user_id))
                            identity_store.save_order_channel_info(k, channel, str(channel_user_id), customer_phone)
                return parsed_ord
        except Exception as e:
            self._record_api_failure(e)

        if local_order:
            return local_order

        # Fallback in-memory order representation
        order_items = [
            OrderItem(
                product_id=it.get("productId", ""),
                product_name=it.get("productName", "Gas LP"),
                quantity=it.get("quantity", 1),
                unit_price=float(it.get("unitPrice", 0.0)),
                subtotal=float(it.get("subtotal", 0.0)),
            )
            for it in clean_items_for_local
        ]
        return Order(
            id=int(time.time()) % 100000,
            tenant_id=tenant_id,
            customer_name=customer_name,
            customer_phone=customer_phone,
            delivery_address=delivery_address,
            total_amount=total_calc,
            status="confirmed",
            payment_method=payment_method,
            items=order_items,
        )

    def get_order_by_id(self, tenant_id: str, order_id: Any) -> Order | None:
        """Fetch order details from PostgreSQL API or memory cache."""
        target_uuid = self._resolve_order_uuid(order_id)
        if len(target_uuid) == 36 and target_uuid.count("-") == 4:
            try:
                res = api_get(f"/orders/{target_uuid}", timeout=5)
                if isinstance(res, dict) and res.get("id"):
                    self._record_api_success()
                    return self._parse_api_order(res, tenant_id)
            except Exception:
                pass

        try:
            res = api_get("/orders", params={"tenantId": tenant_id}, timeout=5)
            if isinstance(res, list):
                for o in res:
                    o_digits = re.findall(r"\d+", str(o.get("orderNumber") or ""))
                    o_num = int(o_digits[-1]) if o_digits else None
                    if (
                        str(o.get("id")) == str(order_id)
                        or str(o.get("orderNumber")) == str(order_id)
                        or (o_num is not None and (str(o_num) == str(order_id) or o_num == order_id))
                    ):
                        self._record_api_success()
                        return self._parse_api_order(o, tenant_id)
        except Exception as e:
            self._record_api_failure(e)

        if order_id in self._order_id_map or str(order_id) in self._order_id_map:
            cached_data = self._order_id_map.get(order_id) or self._order_id_map.get(str(order_id))
            if cached_data:
                return self._parse_api_order(cached_data, tenant_id)

        if self.fallback_repo:
            return self.fallback_repo.get_order_by_id(tenant_id, order_id)
        return None

    def get_orders_by_customer_phone(self, tenant_id: str, phone: str, limit: int = 10) -> list[Order]:
        """Fetch orders for a given customer phone from PostgreSQL API."""
        clean_phone = re.sub(r"\D", "", phone) if phone else ""
        if len(clean_phone) > 10:
            clean_phone = clean_phone[-10:]

        try:
            res = api_get("/orders", params={"tenantId": tenant_id}, timeout=5)
            if isinstance(res, list):
                orders = []
                for o in res:
                    o_phone = re.sub(r"\D", "", str(o.get("customerPhone") or (o.get("customer", {}).get("phone") if isinstance(o.get("customer"), dict) else "")))
                    if len(o_phone) > 10:
                        o_phone = o_phone[-10:]
                    if o_phone == clean_phone:
                        orders.append(self._parse_api_order(o, tenant_id))
                if orders:
                    self._record_api_success()
                    return orders[:limit]
        except Exception as e:
            self._record_api_failure(e)

        if self.fallback_repo:
            return self.fallback_repo.get_orders_by_customer_phone(tenant_id, phone, limit=limit)
        return []

    def get_delivered_orders_count_by_driver(
        self, tenant_id: str, driver_id: Any, date_str: str | None = None
    ) -> int:
        """Count orders delivered by driver today or on a specific date from PostgreSQL."""
        if not driver_id:
            return 0
        try:
            raw_orders = api_get("/orders", params={"tenantId": tenant_id}, timeout=5)
            if isinstance(raw_orders, list):
                d_str = str(driver_id).strip()
                cnt = 0
                for o in raw_orders:
                    o_driver_id = str(o.get("driverId") or "").strip()
                    o_status = str(o.get("status") or "").lower()
                    if o_driver_id == d_str and o_status in ("delivered", "entregado", "completed"):
                        if date_str:
                            c_at = str(o.get("createdAt") or o.get("created_at") or "")
                            if c_at.startswith(date_str):
                                cnt += 1
                        else:
                            cnt += 1
                return cnt
        except Exception:
            pass
        return 0

    def save_tank_reading(
        self,
        tenant_id: str,
        driver_id: Any,
        driver_name: str,
        vehicle_plate: str,
        reading_type: str,
        reading_value: str,
        photo_path: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Save a tank reading in PostgreSQL API."""
        try:
            body = {
                "tenantId": tenant_id,
                "driverId": str(driver_id),
                "readingType": reading_type,
                "readingValue": reading_value,
                "photoUrl": photo_path,
                "notes": notes,
            }
            res = api_post("/admin/tank-readings", body, timeout=5)
            if isinstance(res, dict):
                return res
        except Exception:
            pass
        return {
            "id": f"read_{int(time.time())}",
            "tenant_id": tenant_id,
            "driver_id": driver_id,
            "driver_name": driver_name,
            "vehicle_plate": vehicle_plate,
            "reading_type": reading_type,
            "reading_value": reading_value,
            "photo_path": photo_path,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def get_latest_tank_reading(
        self,
        tenant_id: str,
        driver_id: Any,
        reading_type: str | None = None,
        shift_date: str | None = None,
    ) -> dict[str, Any] | None:
        """Get the latest tank reading for driver from PostgreSQL API."""
        if not driver_id:
            return None
        try:
            params = {"tenantId": tenant_id, "driverId": str(driver_id)}
            if reading_type:
                params["readingType"] = reading_type
            res = api_get("/admin/tank-readings/latest", params=params, timeout=5)
            if isinstance(res, dict) and res.get("id"):
                return res
        except Exception:
            pass
        return None

    def get_tank_readings_history(
        self,
        tenant_id: str,
        driver_id: Any,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get history of tank readings for driver from PostgreSQL API."""
        if not driver_id:
            return []
        try:
            res = api_get(f"/admin/tank-readings/history/{driver_id}", params={"tenantId": tenant_id}, timeout=5)
            if isinstance(res, list):
                return res[:limit]
        except Exception:
            pass
        return []

    def update_tank_reading(
        self,
        reading_id: Any,
        reading_value: str,
        notes: str | None = None,
    ) -> dict[str, Any] | None:
        """Update the value or notes of a previously recorded tank reading."""
        try:
            body: dict[str, Any] = {"readingValue": reading_value}
            if notes is not None:
                body["notes"] = notes
            res = api_patch(f"/admin/tank-readings/{reading_id}", body, timeout=5)
            if isinstance(res, dict):
                return res
        except Exception:
            pass
        if self.fallback_repo and hasattr(self.fallback_repo, "update_tank_reading"):
            try:
                return self.fallback_repo.update_tank_reading(reading_id, reading_value, notes)
            except Exception:
                pass
        return {"id": reading_id, "reading_value": reading_value, "notes": notes}

    def get_all_orders_admin(
        self, tenant_id: str = "petroil", status: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Fetch orders with driver information, item summaries, and status for Admin UI."""
        try:
            raw_orders = api_get("/orders", params={"tenantId": tenant_id}, timeout=5)
            if isinstance(raw_orders, list):
                self._record_api_success()
                drivers_map = {str(d.id): d for d in self.get_all_drivers(tenant_id)}
                result = []
                now_dt = datetime.now()

                for o in raw_orders:
                    api_status = str(o.get("status") or "PENDIENTE").upper()
                    local_status = self._map_api_status_to_local(api_status)

                    raw_id = o.get("orderNumber") or o.get("id") or 1
                    sched_for = o.get("scheduledFor") or o.get("scheduled_for")
                    delivery_sched = o.get("deliverySchedule") or o.get("delivery_schedule")

                    sched_info = (
                        self._order_schedules.get(str(raw_id))
                        or self._order_schedules.get(str(o.get("id")))
                        or identity_store.get_order_schedule(raw_id)
                        or identity_store.get_order_schedule(o.get("id"))
                    )
                    if sched_info:
                        delivery_sched = sched_info.get("delivery_schedule") or delivery_sched
                        sched_for = sched_info.get("scheduled_for") or sched_for

                    deadline_dt = normalize_schedule_datetime(sched_for, now_dt)
                    if not deadline_dt and delivery_sched:
                        deadline_dt = normalize_schedule_datetime(delivery_sched, now_dt)

                    if deadline_dt:
                        sched_for = deadline_dt.isoformat()
                        if not delivery_sched or delivery_sched == "Lo antes posible" or ("t" in delivery_sched.lower() and len(delivery_sched) >= 19):
                            delivery_sched = format_schedule_display(deadline_dt, now_dt)
                    elif not delivery_sched:
                        delivery_sched = "Lo antes posible"

                    if api_status in ("PROGRAMADO", "SCHEDULED") or local_status == "scheduled":
                        if deadline_dt and now_dt >= (deadline_dt - timedelta(minutes=30)):
                            local_status = "assigned" if o.get("driverId") else "confirmed"
                        else:
                            local_status = "scheduled"

                    if status and status != "all":
                        if status == "active":
                            if local_status not in ("confirmed", "assigned", "in_route", "rejected_by_driver"):
                                continue
                        elif status == "scheduled":
                            if local_status != "scheduled":
                                continue
                        elif local_status != status.lower():
                            continue
                    elif status != "all" and status != "scheduled":
                        # Hide scheduled orders waiting in agenda before T-30
                        if local_status == "scheduled":
                            continue

                    items = []
                    for it in o.get("items", []):
                        p_info = it.get("product") or {}
                        p_name = it.get("productName") or p_info.get("name") or "Gas LP"
                        p_qty = it.get("quantity") or 1
                        p_unit_price = float(it.get("unitPrice") or p_info.get("pricePerUnit") or 0.0)
                        p_subtotal = float(it.get("subtotal") or (p_qty * p_unit_price))
                        items.append({
                            "product_name": p_name,
                            "quantity": p_qty,
                            "unit_price": p_unit_price,
                            "subtotal": p_subtotal,
                        })

                    cust = o.get("customer") or {}
                    raw_id = o.get("orderNumber") or o.get("id") or 1

                    driver_id_val = o.get("driverId")

                    # Traceability / IdentityStore extraction for ratings & rejection notes
                    rating_val = None
                    rating_tag_val = None
                    rating_comment_val = None
                    rejection_reason_val = None

                    # Check persistent IdentityStore & memory
                    saved_rating = (
                        identity_store.get_order_rating(raw_id)
                        or identity_store.get_order_rating(o.get("id"))
                        or self._order_ratings.get(str(raw_id))
                        or self._order_ratings.get(str(o.get("id")))
                    )
                    if saved_rating:
                        rating_val = int(saved_rating.get("rating", 5))
                        rating_tag_val = saved_rating.get("feedback_tag") or None
                        rating_comment_val = saved_rating.get("comment") or None
                        if not driver_id_val and saved_rating.get("driver_id"):
                            driver_id_val = saved_rating.get("driver_id")

                    d_obj = drivers_map.get(str(driver_id_val)) if driver_id_val else None
                    driver_name_val = o.get("driverName") or (d_obj.name if d_obj else None)
                    driver_phone_val = o.get("driverPhone") or (d_obj.phone if d_obj else None)
                    driver_veh_val = o.get("truckPlate") or (d_obj.vehicle_plate if d_obj else ("Cilindros" if driver_id_val else None))

                    last_trace_desc = ""
                    for tr in (o.get("traceability") or []):
                        desc = str(tr.get("description") or "")
                        if desc:
                            last_trace_desc = desc
                        if "Calificación recibida:" in desc or "estrellas" in desc:
                            m_stars = re.search(r"(\d+)/5", desc)
                            if m_stars and rating_val is None:
                                rating_val = int(m_stars.group(1))
                            if "Comentario:" in desc and not rating_comment_val:
                                rating_comment_val = desc.split("Comentario:")[-1].strip()
                        if "Aspecto:" in desc and not rating_tag_val:
                            try:
                                rating_tag_val = desc.split("Aspecto:")[1].split("|")[0].strip()
                            except Exception:
                                pass
                        if "rechaz" in desc.lower() or "motivo" in desc.lower():
                            rejection_reason_val = desc

                    # Interceptar error del dashboard externo donde asignación envía ENTREGADO
                    if api_status in ("ENTREGADO", "DELIVERED") and ("salir a ruta" in last_trace_desc.lower() or "unidad asignada" in last_trace_desc.lower()):
                        local_status = "assigned"
                        try:
                            target_uuid = self._resolve_order_uuid(raw_id)
                            api_patch(f"/orders/{target_uuid}/status", {"status": "ASIGNADO", "description": "Auto-corrección: Unidad asignada a chofer", "actor": "SISTEMA"}, timeout=3)
                        except Exception:
                            pass

                    # If rating found, persist it to IdentityStore only if not already saved
                    if rating_val and raw_id and not saved_rating:
                        eff_driver_id = driver_id_val or None
                        identity_store.save_order_rating(
                            order_id=raw_id,
                            driver_id=eff_driver_id,
                            rating=rating_val,
                            feedback_tag=rating_tag_val or "",
                            comment=rating_comment_val or "",
                        )

                    result.append({
                        "id": raw_id,
                        "customer_name": o.get("customerName") or cust.get("name") or "Cliente",
                        "customer_phone": o.get("customerPhone") or cust.get("phone") or "",
                        "delivery_address": o.get("deliveryAddress") or cust.get("address") or "",
                        "delivery_schedule": delivery_sched,
                        "scheduled_for": deadline_dt.isoformat() if deadline_dt else sched_for,
                        "total_amount": float(o.get("totalAmount") or 0.0),
                        "currency": "MXN",
                        "status": local_status,
                        "last_traceability_desc": last_trace_desc,
                        "traceability": o.get("traceability") or [],
                        "payment_method": o.get("paymentMethod") or "Efectivo",
                        "notes": o.get("notes") or "",
                        "channel": str(o.get("channel") or "TELEGRAM").lower(),
                        "driver_id": driver_id_val,
                        "driver_name": driver_name_val,
                        "driver_phone": driver_phone_val,
                        "driver_vehicle": driver_veh_val,
                        "driver_rating": rating_val,
                        "rating_tag": rating_tag_val,
                        "rating_comment": rating_comment_val,
                        "rejection_reason": rejection_reason_val,
                        "rejection_driver_name": driver_name_val if local_status == "rejected_by_driver" else None,
                        "cancelled_by": (
                            o.get("cancelledBy")
                            or o.get("cancelled_by")
                            or (identity_store.get_order_cancellation(raw_id) or {}).get("cancelled_by")
                            or (identity_store.get_order_cancellation(o.get("id")) or {}).get("cancelled_by")
                            or None
                        ),
                        "items": items,
                        "created_at": o.get("createdAt") or datetime.now(timezone.utc).isoformat(),
                    })
                def _order_sort_key(item: dict[str, Any]) -> tuple[int, str]:
                    val = str(item.get("id") or "")
                    digits = re.findall(r"\d+", val)
                    return (int(digits[-1]) if digits else 0, str(item.get("created_at") or ""))

                result.sort(key=_order_sort_key, reverse=True)
                return result[:limit]
        except Exception as e:
            self._record_api_failure(e)

        if self.fallback_repo:
            return self.fallback_repo.get_all_orders_admin(tenant_id, status=status, limit=limit)
        return []

    def get_admin_dashboard_metrics(self, tenant_id: str = "petroil") -> dict[str, Any]:
        """Get aggregated KPI metrics for the live dashboard."""
        try:
            raw_metrics = api_get("/admin/metrics", params={"tenantId": tenant_id}, timeout=5)
            orders = self.get_all_orders_admin(tenant_id, status="all")
            prods = self.get_all_products(tenant_id)

            drivers_status = self.get_all_drivers_operational_status(tenant_id)
            total_drivers = len(drivers_status)
            available_drivers = sum(1 for d in drivers_status if d.get("operational_status") == "disponible")
            en_entrega_drivers = sum(1 for d in drivers_status if d.get("operational_status") == "en_entrega")
            fuera_servicio_drivers = sum(1 for d in drivers_status if d.get("operational_status") == "fuera_servicio")

            active_orders = sum(1 for o in orders if o["status"] in ("confirmed", "assigned", "in_route", "rejected_by_driver"))
            delivered_orders = sum(1 for o in orders if o["status"] == "delivered")
            cancelled_orders = sum(1 for o in orders if o["status"] == "cancelled")
            scheduled_orders = sum(1 for o in orders if o["status"] == "scheduled")
            total_rev = sum(o["total_amount"] for o in orders if o["status"] == "delivered")
            rev_cash = sum(o["total_amount"] for o in orders if o["status"] == "delivered" and "efectivo" in (o.get("payment_method") or "").lower())
            rev_card = sum(o["total_amount"] for o in orders if o["status"] == "delivered" and ("tarjeta" in (o.get("payment_method") or "").lower() or "terminal" in (o.get("payment_method") or "").lower()))

            all_ratings = self.get_all_ratings_admin(tenant_id)
            total_ratings_count = len(all_ratings)
            avg_satisfaction = round(sum(float(r["rating"]) for r in all_ratings) / total_ratings_count, 1) if total_ratings_count > 0 else 5.0

            return {
                "total_orders": len(orders),
                "active_orders": active_orders,
                "delivered_orders": delivered_orders,
                "cancelled_orders": cancelled_orders,
                "scheduled_orders": scheduled_orders,
                "rejected_orders": 0,
                "unresolved_rejections": 0,
                "total_revenue": total_rev,
                "revenue_cash": rev_cash,
                "revenue_card": rev_card,
                "total_drivers": total_drivers or (raw_metrics.get("totalDrivers") if isinstance(raw_metrics, dict) else 4),
                "available_drivers": available_drivers or (raw_metrics.get("activeDrivers") if isinstance(raw_metrics, dict) else 3),
                "en_entrega_drivers": en_entrega_drivers,
                "fuera_servicio_drivers": fuera_servicio_drivers,
                "total_products": len(prods),
                "total_customers": len(orders) or 1,
                "avg_satisfaction": avg_satisfaction,
                "total_ratings": total_ratings_count,
            }
        except Exception as e:
            self._record_api_failure(e)

        if self.fallback_repo:
            return self.fallback_repo.get_admin_dashboard_metrics(tenant_id)
        return {
            "total_orders": 0, "active_orders": 0, "delivered_orders": 0, "cancelled_orders": 0,
            "scheduled_orders": 0, "rejected_orders": 0, "unresolved_rejections": 0,
            "total_revenue": 0.0, "revenue_cash": 0.0, "revenue_card": 0.0,
            "total_drivers": 0, "available_drivers": 0, "en_entrega_drivers": 0,
            "fuera_servicio_drivers": 0, "total_products": 0, "total_customers": 0,
            "avg_satisfaction": 5.0, "total_ratings": 0,
        }

    def get_all_customers_admin(self, tenant_id: str = "petroil") -> list[dict[str, Any]]:
        """Fetch all customers from PostgreSQL API or fallback."""
        try:
            raw_cust = api_get("/customers", params={"tenantId": tenant_id}, timeout=5)
            if isinstance(raw_cust, list) and raw_cust:
                self._record_api_success()
                res = []
                for c in raw_cust:
                    res.append({
                        "id": c.get("id"),
                        "name": c.get("name") or "Sin nombre",
                        "phone": c.get("phone") or "",
                        "channel": "api",
                        "channel_user_id": c.get("phone") or "",
                        "address": c.get("address") or "",
                        "notes": "",
                        "order_count": c.get("_count", {}).get("orders", 0) if isinstance(c.get("_count"), dict) else 0,
                        "total_spent": 0.0,
                        "created_at": c.get("createdAt") or datetime.now(timezone.utc).isoformat(),
                        "addresses": [
                            {
                                "id": 1,
                                "address": c.get("address") or "Mazatlán",
                                "alias": "Principal",
                                "is_default": True,
                            }
                        ] if c.get("address") else [],
                    })
                return res
        except Exception as e:
            self._record_api_failure(e)

        if self.fallback_repo:
            return self.fallback_repo.get_all_customers_admin(tenant_id)
        return []

    # -------------------------------------------------------------------------
    # Drivers (PostgreSQL API)
    # -------------------------------------------------------------------------

    def _parse_api_driver(self, d: dict, tenant_id: str = "petroil") -> Driver:
        """Convert a PostgreSQL API driver dictionary to a Driver model."""
        veh = d.get("vehicle") or {}
        v_type_raw = (veh.get("vehicleType") or d.get("vehicleType") or "CAMIONETA").upper()
        v_type = "estacionario" if v_type_raw == "PIPA" else "cilindros"

        unit_id = veh.get("identifier") or d.get("unitIdentifier") or ""
        plate = veh.get("plate") or d.get("vehiclePlate") or ""
        if (not unit_id or not plate) and d.get("vehicleId"):
            try:
                v_obj = self.get_vehicle(tenant_id, d.get("vehicleId"))
                if v_obj:
                    unit_id = unit_id or v_obj.unit_identifier
                    plate = plate or v_obj.plate
                    if v_obj.vehicle_type:
                        v_type = "estacionario" if v_obj.vehicle_type == "pipa" else "cilindros"
            except Exception:
                pass
        v_plate_str = f"{unit_id} [{plate}]" if (unit_id and plate) else (unit_id or plate)

        d_id_str = str(d.get("id")).strip() if d.get("id") else ""
        cached_loc = self._driver_locations.get(d_id_str)
        c_lat = cached_loc[0] if cached_loc else (float(d.get("currentLat")) if d.get("currentLat") is not None else None)
        c_lng = cached_loc[1] if cached_loc else (float(d.get("currentLng")) if d.get("currentLng") is not None else None)

        # Si la API no tiene coordenadas, consultar SQLite local persistente por telegram_user_id, teléfono o ID
        if c_lat is None or c_lng is None:
            try:
                from src.repositories.sqlite_repo import get_db_connection
                tg_uid = str(d.get("telegramUserId") or "").strip()
                d_phone = str(d.get("phone") or "").strip()
                clean_p = re.sub(r"\D", "", d_phone)[-10:] if len(re.sub(r"\D", "", d_phone)) >= 10 else d_phone

                with get_db_connection() as conn:
                    row = None
                    if tg_uid and tg_uid.isdigit():
                        row = conn.execute(
                            "SELECT current_lat, current_lng FROM drivers WHERE telegram_user_id = ? AND current_lat IS NOT NULL",
                            (tg_uid,),
                        ).fetchone()
                    if not row and clean_p:
                        row = conn.execute(
                            "SELECT current_lat, current_lng FROM drivers WHERE phone LIKE ? AND current_lat IS NOT NULL",
                            (f"%{clean_p}%",),
                        ).fetchone()
                    if not row and d_id_str:
                        row = conn.execute(
                            "SELECT current_lat, current_lng FROM drivers WHERE (id = ? OR name = ?) AND current_lat IS NOT NULL",
                            (d_id_str, d.get("name", "")),
                        ).fetchone()

                    if row and row["current_lat"] is not None and row["current_lng"] is not None:
                        c_lat = float(row["current_lat"])
                        c_lng = float(row["current_lng"])
                        if d_id_str:
                            self._driver_locations[d_id_str] = (c_lat, c_lng)
            except Exception as e:
                logger.debug(f"[api_repo] Error resolving driver coordinates from SQLite: {e}")

        return Driver(
            id=d.get("id"),
            tenant_id=d.get("tenantId") or tenant_id,
            name=d.get("name") or "Chofer",
            phone=d.get("phone") or "",
            telegram_user_id=str(d.get("telegramUserId")) if d.get("telegramUserId") else None,
            vehicle_id=d.get("vehicleId"),
            unit_identifier=unit_id,
            vehicle_type=v_type,
            vehicle_plate=v_plate_str,
            zone=d.get("zone") or "Mazatlán Centro / General",
            is_available=bool(d.get("isAvailable", True)),
            current_lat=c_lat,
            current_lng=c_lng,
            created_at=d.get("createdAt"),
            updated_at=d.get("updatedAt"),
        )

    def get_all_drivers(self, tenant_id: str = "petroil") -> list[Driver]:
        """Fetch all drivers directly from NestJS PostgreSQL API."""
        try:
            res = api_get("/admin/drivers", params={"tenantId": tenant_id}, timeout=5)
            if isinstance(res, list):
                self._record_api_success()
                return [self._parse_api_driver(d, tenant_id) for d in res]
        except Exception as e:
            self._record_api_failure(e)

        if self.fallback_repo:
            return self.fallback_repo.get_all_drivers(tenant_id)
        return []

    def get_driver(self, driver_id: Any) -> Driver | None:
        """Find driver by ID in PostgreSQL, supporting full UUID, unique prefix, or telegram_user_id."""
        if not driver_id:
            return None
        d_str = str(driver_id).strip()
        all_drivers = self.get_all_drivers()
        # 1. Exact match by string representation of ID
        for d in all_drivers:
            if str(d.id).strip().lower() == d_str.lower():
                return d
        # 2. Match by prefix (e.g. truncated integer or partial UUID)
        prefix_matches = [d for d in all_drivers if str(d.id).strip().lower().startswith(d_str.lower())]
        if len(prefix_matches) == 1:
            return prefix_matches[0]
        # 3. Match by telegram_user_id
        for d in all_drivers:
            if d.telegram_user_id and str(d.telegram_user_id).strip() == d_str:
                return d
        # 4. Fallback to sqlite/fallback repo
        if self.fallback_repo:
            return self.fallback_repo.get_driver(driver_id)
        return None

    def get_driver_by_phone(self, tenant_id: str, phone: str) -> Driver | None:
        """Find driver by phone number (exact or 10-digit suffix) in PostgreSQL."""
        clean_phone = re.sub(r"\D", "", str(phone))
        if not clean_phone:
            return None
        suffix_10 = clean_phone[-10:] if len(clean_phone) >= 10 else clean_phone

        for d in self.get_all_drivers(tenant_id):
            d_clean = re.sub(r"\D", "", str(d.phone))
            d_suffix_10 = d_clean[-10:] if len(d_clean) >= 10 else d_clean
            if d_clean == clean_phone or (suffix_10 and d_suffix_10 and suffix_10 == d_suffix_10):
                return d

        if self.fallback_repo:
            return self.fallback_repo.get_driver_by_phone(tenant_id, phone)
        return None

    def driver_login(self, phone: str, password: str = "") -> dict[str, Any] | None:
        """Authenticate driver with Central NestJS API (POST /api/admin/drivers/login)."""
        clean_phone = re.sub(r"\D", "", str(phone))
        phone_payload = clean_phone if clean_phone.startswith("+") else (f"+52{clean_phone[-10:]}" if len(clean_phone) >= 10 else clean_phone)
        body = {
            "phone": phone_payload,
            "password": password or "123456",
        }
        try:
            res = api_post("/admin/drivers/login", body, timeout=5)
            if isinstance(res, dict):
                self._record_api_success()
                return res
        except Exception as e:
            logger.debug(f"[ApiRepository] driver_login endpoint note: {e}")
        return None

    def get_driver_by_telegram_id(self, tenant_id: str, telegram_user_id: str) -> Driver | None:
        """Find driver by Telegram User ID in PostgreSQL."""
        if not telegram_user_id:
            return None
        tg_str = str(telegram_user_id).strip()
        for d in self.get_all_drivers(tenant_id):
            if d.telegram_user_id and str(d.telegram_user_id).strip() == tg_str:
                return d

        if self.fallback_repo:
            return self.fallback_repo.get_driver_by_telegram_id(tenant_id, telegram_user_id)
        return None

    def get_driver_by_telegram(self, telegram_user_id: int | str) -> Driver | None:
        """Alias for get_driver_by_telegram_id."""
        return self.get_driver_by_telegram_id("petroil", str(telegram_user_id))

    def get_available_drivers(
        self, tenant_id: str = "petroil", vehicle_type: str = "ambos", zone: str = ""
    ) -> list[Driver]:
        """Fetch available drivers matching vehicle capability from PostgreSQL."""
        drivers = self.get_all_drivers(tenant_id)
        matched: list[Driver] = []
        for d in drivers:
            if not d.is_available:
                continue
            if vehicle_type == "ambos" or d.vehicle_type == "ambos" or d.vehicle_type == vehicle_type:
                matched.append(d)
        return matched

    def create_driver(
        self,
        tenant_id: str,
        name: str,
        phone: str,
        vehicle_type: str = "cilindros",
        vehicle_plate: str = "",
        zone: str = "General",
        telegram_user_id: str = "",
        vehicle_id: Any = None,
    ) -> Driver:
        """Create a new driver in PostgreSQL."""
        body = {
            "tenantId": tenant_id,
            "name": name.strip(),
            "phone": phone.strip(),
            "vehicleType": "PIPA" if vehicle_type.lower() in ("pipa", "estacionario") else "CAMIONETA",
            "vehiclePlate": vehicle_plate.strip(),
            "zone": zone.strip(),
            "telegramUserId": telegram_user_id.strip() if telegram_user_id else None,
            "vehicleId": str(vehicle_id) if vehicle_id else None,
            "isAvailable": True,
        }
        try:
            res = api_post("/admin/drivers", body, timeout=5)
            if isinstance(res, dict) and res.get("id"):
                self._record_api_success()
                return self._parse_api_driver(res, tenant_id)
        except Exception as e:
            self._record_api_failure(e)

        if self.fallback_repo:
            return self.fallback_repo.create_driver(
                tenant_id=tenant_id,
                name=name,
                phone=phone,
                vehicle_type=vehicle_type,
                vehicle_plate=vehicle_plate,
                zone=zone,
                telegram_user_id=telegram_user_id,
                vehicle_id=vehicle_id,
            )

        return Driver(
            id=f"drv_{int(time.time())}",
            tenant_id=tenant_id,
            name=name,
            phone=phone,
            vehicle_type=vehicle_type,
            vehicle_plate=vehicle_plate,
            zone=zone,
            telegram_user_id=telegram_user_id or None,
            vehicle_id=vehicle_id,
        )

    def update_driver(self, driver_id: Any, updates: dict[str, Any]) -> Driver | None:
        """Update driver profile, Telegram user ID, GPS, or availability in PostgreSQL preserving existing fields."""
        if not driver_id:
            return None

        d_str = str(driver_id).strip()
        driver_obj = self.get_driver(driver_id)
        target_uuid = str(driver_obj.id).strip() if (driver_obj and driver_obj.id) else d_str

        # Fetch current driver state from PostgreSQL to avoid wiping out fields on PUT
        current_raw = None
        try:
            raw_drivers = api_get("/admin/drivers", timeout=5)
            if isinstance(raw_drivers, list):
                for rd in raw_drivers:
                    rd_id = str(rd.get("id")).strip()
                    rd_tg = str(rd.get("telegramUserId") or "").strip()
                    if rd_id in (target_uuid, d_str) or (rd_tg and rd_tg in (target_uuid, d_str)):
                        current_raw = rd
                        target_uuid = rd_id
                        break
        except Exception:
            pass

        body: dict[str, Any] = {}
        if current_raw:
            body["name"] = current_raw.get("name")
            body["phone"] = current_raw.get("phone")
            body["telegramUserId"] = current_raw.get("telegramUserId")
            body["vehicleId"] = current_raw.get("vehicleId")
            body["zone"] = current_raw.get("zone")
            body["isAvailable"] = current_raw.get("isAvailable", True)
            body["status"] = current_raw.get("status", "AVAILABLE")
            body["currentLat"] = current_raw.get("currentLat")
            body["currentLng"] = current_raw.get("currentLng")

        key_mapping = {
            "telegram_user_id": "telegramUserId",
            "is_available": "isAvailable",
            "current_lat": "currentLat",
            "current_lng": "currentLng",
            "vehicle_id": "vehicleId",
            "vehicle_type": "vehicleType",
            "vehicle_plate": "vehiclePlate",
            "zone": "zone",
            "name": "name",
            "phone": "phone",
            "status": "status",
        }
        for k, v in updates.items():
            mapped_key = key_mapping.get(k, k)
            body[mapped_key] = v

        try:
            api_put(f"/admin/drivers/{target_uuid}", body, timeout=5)
            self._record_api_success()
            return self.get_driver(target_uuid)
        except Exception as e:
            self._record_api_failure(e)

        if self.fallback_repo:
            return self.fallback_repo.update_driver(driver_id, updates)

        return self.get_driver(driver_id)

    def delete_driver(self, driver_id: Any) -> bool:
        """Delete a driver from PostgreSQL."""
        try:
            api_delete(f"/admin/drivers/{driver_id}", timeout=5)
            self._record_api_success()
            return True
        except Exception as e:
            self._record_api_failure(e)

        if self.fallback_repo:
            return self.fallback_repo.delete_driver(driver_id)
        return False

    def set_driver_availability(self, driver_id: Any, is_available: bool) -> None:
        """Toggle driver active/offline status in PostgreSQL."""
        self.update_driver(
            driver_id,
            {
                "is_available": is_available,
                "status": "AVAILABLE" if is_available else "OFFLINE",
            },
        )

    def update_driver_location(self, driver_id: Any, lat: float, lng: float) -> None:
        """Update driver GPS coordinates in memory cache, remote API, and fallback store.

        Ensures the PostgreSQL driver UUID is resolved and updated so live tracking maps
        and dispatchers receive 100% reliable real-time positions.
        """
        if not driver_id:
            return
        d_str = str(driver_id).strip()
        self._driver_locations[d_str] = (float(lat), float(lng))
        driver_obj = self.get_driver(driver_id)
        target_uuid = str(driver_obj.id).strip() if (driver_obj and driver_obj.id) else d_str

        if driver_obj:
            if target_uuid != d_str:
                self._driver_locations[target_uuid] = (float(lat), float(lng))
            if driver_obj.telegram_user_id:
                self._driver_locations[str(driver_obj.telegram_user_id).strip()] = (float(lat), float(lng))

        try:
            self.update_driver(target_uuid, {"current_lat": lat, "current_lng": lng})
        except Exception:
            pass

        # Call Central API endpoint: POST /api/admin/drivers/:driverId/location
        # Note: Must use database driver UUID so NestJS updates currentLat and currentLng in PostgreSQL!
        try:
            res_loc = api_post(f"/admin/drivers/{target_uuid}/location", {"lat": float(lat), "lng": float(lng)}, timeout=4)
            if isinstance(res_loc, dict) and res_loc.get("count", 0) > 0:
                self._record_api_success()
                logger.info(f"📍 [ApiRepository] Driver GPS updated in PostgreSQL: UUID={target_uuid} ({lat:.4f}, {lng:.4f})")
            elif d_str != target_uuid:
                api_post(f"/admin/drivers/{d_str}/location", {"lat": float(lat), "lng": float(lng)}, timeout=4)
        except Exception as e:
            logger.debug(f"[ApiRepository] Note: POST /admin/drivers/{target_uuid}/location: {e}")

        # Persistir coordenadas en SQLite para compartir entre procesos (driver_bot <-> FastAPI)
        try:
            from src.repositories.sqlite_repo import get_db_connection
            now_iso = datetime.now(timezone.utc).isoformat()
            tg_uid = str(driver_obj.telegram_user_id).strip() if (driver_obj and driver_obj.telegram_user_id) else (d_str if d_str.isdigit() else None)
            d_phone = str(driver_obj.phone).strip() if (driver_obj and driver_obj.phone) else None
            clean_p = re.sub(r"\D", "", d_phone)[-10:] if (d_phone and len(re.sub(r"\D", "", d_phone)) >= 10) else None

            with get_db_connection() as conn:
                if tg_uid and tg_uid.isdigit():
                    conn.execute("UPDATE drivers SET current_lat = ?, current_lng = ?, updated_at = ? WHERE telegram_user_id = ?", (float(lat), float(lng), now_iso, tg_uid))
                if clean_p:
                    conn.execute("UPDATE drivers SET current_lat = ?, current_lng = ?, updated_at = ? WHERE phone LIKE ?", (float(lat), float(lng), now_iso, f"%{clean_p}%"))
                if str(driver_id).isdigit():
                    conn.execute("UPDATE drivers SET current_lat = ?, current_lng = ?, updated_at = ? WHERE id = ?", (float(lat), float(lng), now_iso, int(driver_id)))
        except Exception as e:
            logger.debug(f"[api_repo] Error syncing GPS to SQLite: {e}")

        if self.fallback_repo and hasattr(self.fallback_repo, "update_driver_location"):
            try:
                self.fallback_repo.update_driver_location(driver_id, lat, lng)
            except Exception:
                pass

    def get_all_drivers_admin(self, tenant_id: str = "petroil") -> list[dict[str, Any]]:
        """Fetch all drivers formatted for the Admin Dashboard."""
        return self.get_all_drivers_operational_status(tenant_id)

    def get_all_drivers_operational_status(self, tenant_id: str = "petroil") -> list[dict[str, Any]]:
        """Get operational status and active deliveries count for all drivers from PostgreSQL."""
        drivers = self.get_all_drivers(tenant_id)
        orders = self.get_all_orders_admin(tenant_id, status="all")

        # Collect ratings from persistent store and delivered orders
        all_stored_ratings = identity_store.get_all_order_ratings()
        ratings_by_driver: dict[str, list[float]] = {}
        for r in all_stored_ratings:
            drv_id = str(r.get("driver_id") or "").strip().lower()
            if drv_id and r.get("rating"):
                try:
                    ratings_by_driver.setdefault(drv_id, []).append(float(r["rating"]))
                except (ValueError, TypeError):
                    pass

        # Also pull ratings from orders if not already in store
        for o in orders:
            drv_id = str(o.get("driver_id") or "").strip().lower()
            r_val = o.get("driver_rating")
            if drv_id and r_val:
                o_id_str = str(o.get("id"))
                if not any(r.get("order_id") == o_id_str for r in all_stored_ratings):
                    try:
                        ratings_by_driver.setdefault(drv_id, []).append(float(r_val))
                    except (ValueError, TypeError):
                        pass

        result = []
        for d in drivers:
            active_orders = [
                o for o in orders
                if str(o.get("driver_id")) == str(d.id)
                and o.get("status") in ("assigned", "in_route")
            ]
            if active_orders:
                op_status = "en_entrega"
            elif d.is_available:
                op_status = "disponible"
            else:
                op_status = "fuera_servicio"

            # Match ratings belonging to this driver across any identifier
            d_keys = {str(d.id).strip().lower()}
            if d.telegram_user_id:
                d_keys.add(str(d.telegram_user_id).strip().lower())
            if d.name:
                d_keys.add(str(d.name).strip().lower())
            if d.phone:
                d_keys.add(re.sub(r"\D", "", str(d.phone)))

            d_ratings: list[float] = []
            for k in d_keys:
                if k in ratings_by_driver:
                    for val in ratings_by_driver[k]:
                        d_ratings.append(val)

            if d_ratings:
                avg_rating = round(sum(d_ratings) / len(d_ratings), 1)
                total_ratings = len(d_ratings)
            else:
                avg_rating = 5.0
                total_ratings = 0

            result.append({
                "id": d.id,
                "name": d.name,
                "phone": d.phone,
                "telegram_user_id": d.telegram_user_id,
                "vehicle_id": d.vehicle_id,
                "vehicle_plate": d.vehicle_plate,
                "vehicle_type": d.vehicle_type,
                "zone": d.zone,
                "is_available": d.is_available,
                "operational_status": op_status,
                "active_orders_count": len(active_orders),
                "active_order_id": active_orders[0].get("id") if active_orders else None,
                "active_customer_name": active_orders[0].get("customer_name") if active_orders else None,
                "active_delivery_address": active_orders[0].get("delivery_address") if active_orders else None,
                "active_order_status": active_orders[0].get("status") if active_orders else None,
                "avg_rating": avg_rating,
                "rating": avg_rating,
                "total_ratings": total_ratings,
                "current_lat": d.current_lat,
                "current_lng": d.current_lng,
            })
        return result

    # -------------------------------------------------------------------------
    # Vehicles (PostgreSQL API)
    # -------------------------------------------------------------------------

    def _parse_api_vehicle(self, v: dict, tenant_id: str = "petroil") -> Vehicle:
        """Convert a PostgreSQL API vehicle dictionary to a Vehicle model."""
        v_type_raw = str(v.get("vehicleType") or "CAMIONETA").upper()
        v_type = "pipa" if v_type_raw == "PIPA" else "camioneta"
        status_raw = str(v.get("status") or "ACTIVE").upper()
        status = "active" if status_raw == "ACTIVE" else ("maintenance" if status_raw == "MAINTENANCE" else "inactive")

        drivers = v.get("drivers") or []
        first_d = drivers[0] if drivers else {}

        return Vehicle(
            id=v.get("id"),
            tenant_id=v.get("tenantId") or tenant_id,
            unit_identifier=v.get("identifier") or v.get("unit_identifier") or "UNIDAD",
            plate=v.get("plate") or "",
            model=v.get("model") or "",
            vehicle_type=v_type,
            pipa_capacity_liters=float(v.get("capacityLiters")) if v.get("capacityLiters") is not None else None,
            cylinder_capacity_count=int(v.get("capacityCylinders")) if v.get("capacityCylinders") is not None else None,
            status=status,
            notes=v.get("notes") or "",
            assigned_driver_id=first_d.get("id"),
            assigned_driver_name=first_d.get("name"),
            created_at=v.get("createdAt"),
            updated_at=v.get("updatedAt"),
        )

    def get_all_vehicles(self, tenant_id: str = "petroil") -> list[dict[str, Any]]:
        """Fetch all vehicles directly from NestJS PostgreSQL API."""
        try:
            res = api_get("/admin/vehicles", params={"tenantId": tenant_id}, timeout=5)
            if isinstance(res, list):
                self._record_api_success()
                return [
                    {
                        "id": v.get("id"),
                        "tenant_id": v.get("tenantId") or tenant_id,
                        "unit_identifier": v.get("identifier") or "",
                        "plate": v.get("plate") or "",
                        "model": v.get("model") or "",
                        "vehicle_type": "pipa" if str(v.get("vehicleType", "")).upper() == "PIPA" else "camioneta",
                        "pipa_capacity_liters": v.get("capacityLiters"),
                        "cylinder_capacity_count": v.get("capacityCylinders"),
                        "status": "active" if str(v.get("status", "")).upper() == "ACTIVE" else "inactive",
                        "notes": v.get("notes") or "",
                    }
                    for v in res
                ]
        except Exception as e:
            self._record_api_failure(e)

        if self.fallback_repo:
            return self.fallback_repo.get_all_vehicles(tenant_id)
        return []

    def get_all_vehicles_admin(self, tenant_id: str = "petroil") -> list[dict[str, Any]]:
        """Fetch all vehicles for Admin UI."""
        return self.get_all_vehicles(tenant_id)

    def get_vehicle(self, tenant_id: str, vehicle_id: Any) -> Vehicle | None:
        """Find vehicle by ID in PostgreSQL."""
        if not vehicle_id:
            return None
        v_str = str(vehicle_id).strip()
        try:
            res = api_get("/admin/vehicles", params={"tenantId": tenant_id}, timeout=5)
            if isinstance(res, list):
                for v in res:
                    if str(v.get("id")).strip() == v_str:
                        return self._parse_api_vehicle(v, tenant_id)
        except Exception as e:
            self._record_api_failure(e)

        if self.fallback_repo:
            return self.fallback_repo.get_vehicle(tenant_id, vehicle_id)
        return None

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
        """Create a vehicle in PostgreSQL."""
        body = {
            "tenantId": tenant_id,
            "identifier": unit_identifier.strip(),
            "plate": plate.strip(),
            "model": model.strip(),
            "vehicleType": "PIPA" if vehicle_type.lower() == "pipa" else "CAMIONETA",
            "capacityLiters": pipa_capacity_liters,
            "capacityCylinders": cylinder_capacity_count,
            "status": "ACTIVE" if status.lower() == "active" else "INACTIVE",
            "notes": notes.strip(),
        }
        try:
            res = api_post("/admin/vehicles", body, timeout=5)
            if isinstance(res, dict) and res.get("id"):
                self._record_api_success()
                return self._parse_api_vehicle(res, tenant_id)
        except Exception as e:
            self._record_api_failure(e)

        if self.fallback_repo:
            return self.fallback_repo.create_vehicle(
                tenant_id=tenant_id,
                unit_identifier=unit_identifier,
                plate=plate,
                model=model,
                vehicle_type=vehicle_type,
                pipa_capacity_liters=pipa_capacity_liters,
                cylinder_capacity_count=cylinder_capacity_count,
                status=status,
                notes=notes,
            )

        return Vehicle(
            id=f"veh_{int(time.time())}",
            tenant_id=tenant_id,
            unit_identifier=unit_identifier,
            plate=plate,
            model=model,
            vehicle_type=vehicle_type,
            pipa_capacity_liters=pipa_capacity_liters,
            cylinder_capacity_count=cylinder_capacity_count,
            status=status,
            notes=notes,
        )

    def update_vehicle(
        self, tenant_id: str, vehicle_id: Any, updates: dict[str, Any]
    ) -> Vehicle | None:
        """Update vehicle in PostgreSQL preserving existing fields."""
        current_raw = None
        try:
            raw_vehicles = api_get("/admin/vehicles", params={"tenantId": tenant_id}, timeout=5)
            if isinstance(raw_vehicles, list):
                for rv in raw_vehicles:
                    if str(rv.get("id")).strip() == str(vehicle_id).strip():
                        current_raw = rv
                        break
        except Exception:
            pass

        body: dict[str, Any] = {}
        if current_raw:
            body["identifier"] = current_raw.get("identifier")
            body["plate"] = current_raw.get("plate")
            body["model"] = current_raw.get("model")
            body["vehicleType"] = current_raw.get("vehicleType")
            body["capacityLiters"] = current_raw.get("capacityLiters")
            body["capacityCylinders"] = current_raw.get("capacityCylinders")
            body["status"] = current_raw.get("status")
            body["notes"] = current_raw.get("notes")

        mapping = {
            "unit_identifier": "identifier",
            "plate": "plate",
            "model": "model",
            "vehicle_type": "vehicleType",
            "pipa_capacity_liters": "capacityLiters",
            "cylinder_capacity_count": "capacityCylinders",
            "status": "status",
            "notes": "notes",
        }
        for k, v in updates.items():
            mapped_key = mapping.get(k, k)
            if mapped_key == "vehicleType" and v:
                body[mapped_key] = "PIPA" if str(v).lower() == "pipa" else "CAMIONETA"
            elif mapped_key == "status" and v:
                body[mapped_key] = "ACTIVE" if str(v).lower() == "active" else "INACTIVE"
            else:
                body[mapped_key] = v

        try:
            api_put(f"/admin/vehicles/{vehicle_id}", body, timeout=5)
            self._record_api_success()
            return self.get_vehicle(tenant_id, vehicle_id)
        except Exception as e:
            self._record_api_failure(e)

        if self.fallback_repo:
            return self.fallback_repo.update_vehicle(tenant_id, vehicle_id, updates)

        return self.get_vehicle(tenant_id, vehicle_id)

    def delete_vehicle(self, tenant_id: str, vehicle_id: Any) -> bool:
        """Delete vehicle from PostgreSQL."""
        try:
            api_delete(f"/admin/vehicles/{vehicle_id}", timeout=5)
            self._record_api_success()
            return True
        except Exception as e:
            self._record_api_failure(e)

        if self.fallback_repo:
            return self.fallback_repo.delete_vehicle(tenant_id, vehicle_id)
        return False

    # -------------------------------------------------------------------------
    # Shifts (PostgreSQL API)
    # -------------------------------------------------------------------------

    def get_active_driver_shift(self, tenant_id: str, driver_id: Any) -> dict[str, Any] | None:
        """Get active shift for driver from PostgreSQL."""
        if not driver_id:
            return None
        try:
            res = api_get(f"/admin/shifts/active/{driver_id}", timeout=5)
            if isinstance(res, dict) and res.get("id"):
                self._record_api_success()
                return res
        except Exception:
            pass
        return None

    def get_driver_shifts(self, tenant_id: str, driver_id: Any = None, limit: int = 50) -> list[dict[str, Any]]:
        """Get shift history from PostgreSQL."""
        try:
            endpoint = f"/admin/shifts/history/{driver_id}" if driver_id else "/admin/shifts"
            res = api_get(endpoint, timeout=5)
            if isinstance(res, list):
                self._record_api_success()
                return res[:limit]
        except Exception:
            pass
        return []

    def start_driver_shift(
        self,
        tenant_id: str,
        driver_id: Any,
        vehicle_id: Any = None,
        initial_tank_pct: float | None = None,
        initial_odometer: float | None = None,
        photo_url: str = "",
        driver_name: str = "",
        vehicle_plate: str = "",
        initial_reading: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Start a driver shift in PostgreSQL."""
        # Support initialReading per Central API documentation alongside initialTankPct/Odometer
        initial_reading_val: float | str = 0
        if initial_reading:
            try:
                nums = re.findall(r"\d+(?:\.\d+)?", str(initial_reading))
                if nums:
                    initial_reading_val = float(nums[0])
                else:
                    initial_reading_val = initial_reading
            except Exception:
                initial_reading_val = 0
        elif initial_odometer is not None:
            initial_reading_val = initial_odometer
        elif initial_tank_pct is not None:
            initial_reading_val = initial_tank_pct

        d_obj = self.get_driver(driver_id)
        target_driver_id = str(d_obj.id).strip() if (d_obj and d_obj.id) else str(driver_id)

        body = {
            "tenantId": tenant_id,
            "driverId": target_driver_id,
            "vehicleId": str(vehicle_id) if vehicle_id else None,
            "initialReading": initial_reading_val,
            "initialTankPct": initial_tank_pct,
            "initialOdometer": initial_odometer,
            "photoUrl": photo_url or None,
            "notes": initial_reading or None,
        }
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            res = api_post("/admin/shifts/start", body, timeout=5)
            if isinstance(res, dict):
                self._record_api_success()
                if "check_in_at" not in res:
                    res["check_in_at"] = res.get("startTime") or res.get("createdAt") or now_str
                return res
        except Exception as e:
            self._record_api_failure(e)
        return {"id": f"shift_{int(time.time())}", "driverId": target_driver_id, "status": "ACTIVE", "check_in_at": now_str}

    def end_driver_shift(
        self,
        tenant_id: str,
        shift_id: Any = None,
        driver_id: Any = None,
        final_tank_pct: float | None = None,
        final_odometer: float | None = None,
        photo_url: str = "",
        final_reading: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """End an active driver shift in PostgreSQL."""
        if final_reading and final_tank_pct is None:
            try:
                nums = re.findall(r"\d+(?:\.\d+)?", str(final_reading))
                if nums:
                    final_tank_pct = float(nums[0])
            except Exception:
                pass

        # Support finalReading per Central API documentation alongside finalTankPct/Odometer
        final_reading_val: float | str = 100
        if final_reading:
            try:
                nums = re.findall(r"\d+(?:\.\d+)?", str(final_reading))
                if nums:
                    final_reading_val = float(nums[0])
                else:
                    final_reading_val = final_reading
            except Exception:
                final_reading_val = 100
        elif final_odometer is not None:
            final_reading_val = final_odometer
        elif final_tank_pct is not None:
            final_reading_val = final_tank_pct

        d_obj = self.get_driver(driver_id) if driver_id else None
        target_driver_id = str(d_obj.id).strip() if (d_obj and d_obj.id) else (str(driver_id) if driver_id else None)

        body = {
            "tenantId": tenant_id,
            "shiftId": str(shift_id) if shift_id else None,
            "driverId": target_driver_id,
            "finalReading": final_reading_val,
            "finalTankPct": final_tank_pct,
            "finalOdometer": final_odometer,
            "photoUrl": photo_url or None,
            "notes": final_reading or None,
        }
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            res = api_put("/admin/shifts/end", body, timeout=5)
            if isinstance(res, dict):
                self._record_api_success()
                if "check_out_at" not in res:
                    res["check_out_at"] = res.get("endTime") or res.get("updatedAt") or now_str
                return res
        except Exception as e:
            self._record_api_failure(e)
        return {"status": "CLOSED", "check_out_at": now_str}

    # -------------------------------------------------------------------------
    # Orders, Agenda & Dispatch (PostgreSQL API)
    # -------------------------------------------------------------------------

    def get_orders_by_driver(self, tenant_id: str, driver_id: Any, active_only: bool = True) -> list[Order]:
        """Fetch orders assigned to driver from PostgreSQL API.

        Tries GET /api/admin/drivers/:driverId/orders first per Central API docs,
        with fallback to filtering /orders.
        """
        if not driver_id:
            return []
        d_str = str(driver_id).strip()
        driver_obj = self.get_driver(driver_id)
        target_uuid = str(driver_obj.id).strip() if (driver_obj and driver_obj.id) else d_str

        try:
            raw_orders = api_get(f"/admin/drivers/{target_uuid}/orders", timeout=5)
            if isinstance(raw_orders, list):
                self._record_api_success()
                matched = []
                for o in raw_orders:
                    parsed = self._parse_api_order(o, tenant_id)
                    if active_only:
                        if parsed.status in ("assigned", "in_route", "pending", "confirmed"):
                            matched.append(parsed)
                    else:
                        matched.append(parsed)
                return matched
        except Exception as e:
            logger.debug(f"[ApiRepository] Note: GET /admin/drivers/{target_uuid}/orders fallback: {e}")

        try:
            raw_orders = api_get("/orders", params={"tenantId": tenant_id}, timeout=5)
            if isinstance(raw_orders, list):
                matched = []
                for o in raw_orders:
                    o_driver_id = str(o.get("driverId") or "").strip()
                    if o_driver_id in (target_uuid, d_str):
                        parsed = self._parse_api_order(o, tenant_id)
                        if active_only:
                            if parsed.status in ("assigned", "in_route", "pending", "confirmed"):
                                matched.append(parsed)
                        else:
                            matched.append(parsed)
                return matched
        except Exception as e:
            self._record_api_failure(e)
        return []

    def get_scheduled_agenda(self, tenant_id: str = "petroil") -> list[dict[str, Any]]:
        """Return scheduled agenda orders with full countdowns and activation details."""
        self.check_and_activate_scheduled_orders(tenant_id)
        now = datetime.now()

        all_orders = self.get_all_orders_admin(tenant_id, status="all")
        agenda = []

        for o in all_orders:
            # Only consider orders that are scheduled or have a future deadline and not completed/cancelled
            st = o.get("status")
            if st in ("cancelled", "delivered"):
                continue

            created_raw = o.get("created_at")
            order_ref_dt = now
            if created_raw:
                try:
                    c_clean = str(created_raw).replace("Z", "+00:00")
                    order_ref_dt = datetime.fromisoformat(c_clean)
                    if order_ref_dt.tzinfo:
                        order_ref_dt = order_ref_dt.astimezone().replace(tzinfo=None)
                except Exception:
                    order_ref_dt = now

            s_for = o.get("scheduled_for")
            schedule_text = o.get("delivery_schedule") or "Lo antes posible"

            deadline_dt = normalize_schedule_datetime(s_for, now)
            if not deadline_dt and schedule_text:
                deadline_dt = normalize_schedule_datetime(schedule_text, order_ref_dt)

            # If not explicitly scheduled and no deadline recognized, skip
            if not deadline_dt and st != "scheduled":
                continue

            # If the order is NOT scheduled and its deadline was in the past (e.g. earlier days),
            # it belongs to active dispatch or history, NOT to the scheduled agenda.
            if st != "scheduled" and deadline_dt and deadline_dt.date() < now.date():
                continue

            if not deadline_dt:
                deadline_dt = now + timedelta(hours=2)

            if not schedule_text or schedule_text == "Lo antes posible" or ("t" in str(schedule_text).lower() and len(str(schedule_text)) >= 19):
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

            agenda.append({
                "id": o["id"],
                "customer_name": o["customer_name"],
                "customer_phone": o["customer_phone"],
                "delivery_address": o["delivery_address"],
                "delivery_schedule": schedule_text,
                "scheduled_for": deadline_dt.isoformat(),
                "deadline_display": deadline_display,
                "activation_at": activation_time.isoformat(),
                "activation_display": act_display,
                "is_activated": is_activated,
                "minutes_until_deadline": diff_deadline_mins,
                "minutes_until_activation": diff_act_mins,
                "total_amount": float(o.get("total_amount") or 0.0),
                "currency": o.get("currency") or "MXN",
                "payment_method": o.get("payment_method") or "Efectivo",
                "notes": o.get("notes") or "",
                "status": st,
                "driver_id": o.get("driver_id"),
                "driver_name": o.get("driver_name"),
                "driver_phone": o.get("driver_phone"),
                "driver_vehicle": o.get("driver_vehicle"),
                "delivery_lat": o.get("delivery_lat"),
                "delivery_lng": o.get("delivery_lng"),
                "items": o.get("items") or [],
                "created_at": o.get("created_at"),
            })

        def _agenda_sort_key(item: dict[str, Any]) -> tuple[str, int]:
            # Primario: Hora pactada de entrega / deadline ascendente (más temprano primero)
            # Secundario: Número de folio ascendente
            deadline = str(item.get("scheduled_for") or "9999-12-31T23:59:59")
            val = str(item.get("id") or "")
            digits = re.findall(r"\d+", val)
            order_num = int(digits[-1]) if digits else 0
            return (deadline, order_num)

        agenda.sort(key=_agenda_sort_key, reverse=False)
        return agenda

    def check_and_activate_scheduled_orders(self, tenant_id: str = "petroil") -> list[int]:
        """Check scheduled orders that should activate now (within 30 min of deadline)."""
        now = datetime.now()
        activated_ids: list[int] = []

        try:
            orders = self.get_all_orders_admin(tenant_id, status="all")
            for o in orders:
                if o.get("status") != "scheduled":
                    continue

                s_for = o.get("scheduled_for")
                schedule_text = o.get("delivery_schedule") or ""
                deadline_dt = normalize_schedule_datetime(s_for, now)
                if not deadline_dt and schedule_text:
                    deadline_dt = normalize_schedule_datetime(schedule_text, now)

                if not deadline_dt:
                    continue

                activation_time = deadline_dt - timedelta(minutes=30)
                if now >= activation_time:
                    driver_id = o.get("driver_id")
                    new_status = "assigned" if driver_id else "confirmed"
                    self.update_order_status(tenant_id, o["id"], status=new_status)
                    activated_ids.append(o["id"])
                    logger.info(
                        f"[Scheduled Engine API] Order #{o['id']} reached 30m window before deadline "
                        f"({deadline_dt.strftime('%Y-%m-%d %H:%M')}). Activated to '{new_status}'."
                    )
                    try:
                        from src.services.dispatch import dispatch_order
                        dispatch_order(o["id"], tenant_id=tenant_id, force_immediate=True)
                    except Exception as e:
                        logger.error(f"[Scheduled Engine API] Error dispatching activated order #{o['id']}: {e}")
        except Exception as e:
            logger.debug(f"[ApiRepository] check_and_activate_scheduled_orders error: {e}")

        return activated_ids

    def activate_scheduled_order_now(self, tenant_id: str, order_id: Any) -> Order | None:
        """Activate a scheduled order to confirmed status."""
        return self.update_order_status(tenant_id, order_id, status="confirmed")

    def reschedule_order(
        self, tenant_id: str, order_id: Any, delivery_schedule: str, scheduled_for: str | None = None
    ) -> Order | None:
        """Reschedule an order with a new delivery time."""
        now_dt = datetime.now()
        deadline_dt = normalize_schedule_datetime(scheduled_for, now_dt)
        if not deadline_dt and delivery_schedule:
            deadline_dt = normalize_schedule_datetime(delivery_schedule, now_dt)

        iso_scheduled = to_utc_iso(deadline_dt, now_dt) if deadline_dt else scheduled_for
        display_schedule = delivery_schedule or (format_schedule_display(deadline_dt, now_dt) if deadline_dt else "Horario reprogramado")
        if deadline_dt and (not delivery_schedule or delivery_schedule == "Lo antes posible" or ("t" in str(delivery_schedule).lower() and len(str(delivery_schedule)) >= 19)):
            display_schedule = format_schedule_display(deadline_dt, now_dt)

        return self.update_order_status(
            tenant_id,
            order_id,
            status="scheduled",
            delivery_schedule=display_schedule,
            scheduled_for=iso_scheduled,
        )

    def reassign_order(self, tenant_id: str, order_id: Any, driver_id: Any) -> Order | None:
        """Reassign an order to a new driver in PostgreSQL."""
        return self.assign_order_to_driver(tenant_id, order_id, driver_id)

    def get_order_rejections(self, tenant_id: str = "petroil", unresolved_only: bool = True) -> list[dict[str, Any]]:
        """Get rejected orders from PostgreSQL."""
        try:
            res = api_get("/admin/rejections", params={"tenantId": tenant_id}, timeout=5)
            if isinstance(res, list):
                self._record_api_success()
                return res
        except Exception:
            pass
        return []

    # -------------------------------------------------------------------------
    # Ratings & Tank Readings (PostgreSQL API / Traceability)
    # -------------------------------------------------------------------------

    def save_order_rating(
        self,
        tenant_id: str,
        order_id: Any,
        driver_id: Any = None,
        customer_id: Any = None,
        rating: int = 5,
        feedback_tag: str = "",
        comment: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Save CSAT customer rating to persistent store and remote API."""
        rating_int = max(1, min(5, int(rating)))
        now_iso = datetime.now(timezone.utc).isoformat()

        if not driver_id or not customer_id:
            try:
                order = self.get_order_by_id(tenant_id, order_id)
                if order:
                    if not driver_id:
                        driver_id = order.driver_id
                    if not customer_id:
                        customer_id = order.customer_id
            except Exception:
                pass

        rating_obj = {
            "order_id": str(order_id),
            "driver_id": str(driver_id) if driver_id else None,
            "customer_id": str(customer_id) if customer_id else None,
            "rating": rating_int,
            "feedback_tag": feedback_tag or "",
            "comment": comment or "",
            "created_at": now_iso,
        }
        self._order_ratings[str(order_id)] = rating_obj

        identity_store.save_order_rating(
            order_id=order_id,
            driver_id=driver_id,
            customer_id=customer_id,
            rating=rating_int,
            feedback_tag=feedback_tag,
            comment=comment,
            created_at=now_iso,
        )

        if self.fallback_repo:
            try:
                self.fallback_repo.save_order_rating(
                    tenant_id=tenant_id,
                    order_id=order_id,
                    driver_id=driver_id,
                    customer_id=customer_id,
                    rating=rating_int,
                    feedback_tag=feedback_tag,
                    comment=comment,
                )
            except Exception as e:
                logger.debug(f"[ApiRepository] fallback save_order_rating: {e}")

        try:
            tag_info = f" Aspecto: {feedback_tag}." if feedback_tag else ""
            comm_info = f" Comentario: {comment}." if comment else ""
            body = {
                "status": "ENTREGADO",
                "description": f"⭐ Calificación recibida: {rating_int}/5 estrellas.{tag_info}{comm_info}",
                "actor": "CLIENTE",
            }
            target_uuid = self._resolve_order_uuid(order_id)
            api_patch(f"/orders/{target_uuid}/status", body, timeout=5)
        except Exception:
            pass
        return rating_obj

    def update_order_rating_feedback(
        self,
        tenant_id: str,
        order_id: Any,
        feedback_tag: str | None = None,
        comment: str | None = None,
        **kwargs: Any,
    ) -> bool:
        """Update additional feedback on customer rating."""
        key = str(order_id)
        if key not in self._order_ratings:
            self._order_ratings[key] = {
                "order_id": str(order_id),
                "rating": 5,
                "feedback_tag": "",
                "comment": "",
            }
        if feedback_tag:
            self._order_ratings[key]["feedback_tag"] = feedback_tag
        if comment:
            self._order_ratings[key]["comment"] = comment

        curr = self._order_ratings[key]
        identity_store.save_order_rating(
            order_id=order_id,
            driver_id=curr.get("driver_id"),
            customer_id=curr.get("customer_id"),
            rating=curr.get("rating", 5),
            feedback_tag=curr.get("feedback_tag", ""),
            comment=curr.get("comment", ""),
        )

        if self.fallback_repo:
            try:
                self.fallback_repo.update_order_rating_feedback(
                    tenant_id=tenant_id,
                    order_id=order_id,
                    feedback_tag=feedback_tag,
                    comment=comment,
                )
            except Exception as e:
                logger.debug(f"[ApiRepository] fallback update_order_rating_feedback: {e}")

        try:
            desc_parts = []
            if feedback_tag:
                desc_parts.append(f"Aspecto: {feedback_tag}")
            if comment:
                desc_parts.append(f"Comentario: {comment}")
            desc_text = " | ".join(desc_parts) or "Retroalimentación adicional del cliente"

            body = {
                "status": "ENTREGADO",
                "description": f"💬 {desc_text}",
                "actor": "CLIENTE",
            }
            target_uuid = self._resolve_order_uuid(order_id)
            api_patch(f"/orders/{target_uuid}/status", body, timeout=5)
        except Exception:
            pass
        return True

    def get_order_rating(self, tenant_id: str, order_id: Any) -> dict[str, Any] | None:
        """Get rating and survey details for a specific order."""
        key = str(order_id)
        if key in self._order_ratings:
            return self._order_ratings[key]

        from_store = identity_store.get_order_rating(order_id)
        if from_store:
            self._order_ratings[key] = from_store
            return from_store

        if self.fallback_repo:
            try:
                res = self.fallback_repo.get_order_rating(tenant_id, order_id)
                if res:
                    return res
            except Exception:
                pass

        target_uuid = self._resolve_order_uuid(order_id)
        try:
            res = api_get(f"/orders/{target_uuid}", timeout=5)
            if isinstance(res, dict):
                for tr in (res.get("traceability") or []):
                    desc = str(tr.get("description") or "")
                    if "Calificación recibida:" in desc or "estrellas" in desc:
                        m_stars = re.search(r"(\d+)/5", desc)
                        stars_val = int(m_stars.group(1)) if m_stars else 5
                        rating_obj = {
                            "order_id": str(order_id),
                            "rating": stars_val,
                            "feedback_tag": "",
                            "comment": desc,
                        }
                        self._order_ratings[key] = rating_obj
                        return rating_obj
        except Exception:
            pass

        return {"order_id": str(order_id), "rating": 5, "feedback_tag": "", "comment": ""}

    def get_all_ratings_admin(self, tenant_id: str = "petroil", limit: int = 100) -> list[dict[str, Any]]:
        """Get all CSAT ratings for Admin UI."""
        orders = self.get_all_orders_admin(tenant_id, status="all")
        ratings_list = []
        seen_orders = set()

        for o in orders:
            oid = str(o.get("id"))
            r_val = o.get("driver_rating")
            if r_val is not None:
                seen_orders.add(oid)
                ratings_list.append({
                    "id": oid,
                    "order_id": oid,
                    "driver_id": o.get("driver_id"),
                    "driver_name": o.get("driver_name") or "Operador",
                    "driver_plate": o.get("driver_vehicle") or "",
                    "customer_name": o.get("customer_name") or "Cliente",
                    "delivery_address": o.get("delivery_address") or "",
                    "total_amount": o.get("total_amount") or 0.0,
                    "rating": int(r_val),
                    "feedback_tag": o.get("rating_tag") or "",
                    "comment": o.get("rating_comment") or "",
                    "created_at": o.get("created_at") or datetime.now(timezone.utc).isoformat(),
                })

        # Also pull from IdentityStore if any wasn't captured in orders
        for r in identity_store.get_all_order_ratings():
            oid = str(r.get("order_id", ""))
            if oid and oid not in seen_orders:
                seen_orders.add(oid)
                drv_id = r.get("driver_id")
                drv_name = "Operador"
                if drv_id:
                    drv = self.get_driver(drv_id)
                    if drv:
                        drv_name = drv.name
                ratings_list.append({
                    "id": oid,
                    "order_id": oid,
                    "driver_id": drv_id,
                    "driver_name": drv_name,
                    "driver_plate": "",
                    "customer_name": "Cliente",
                    "delivery_address": "",
                    "total_amount": 0.0,
                    "rating": int(r.get("rating", 5)),
                    "feedback_tag": r.get("feedback_tag", ""),
                    "comment": r.get("comment", ""),
                    "created_at": r.get("created_at") or datetime.now(timezone.utc).isoformat(),
                })

        return ratings_list[:limit]

    def get_driver_ratings(self, tenant_id: str, driver_id: Any, limit: int = 50) -> list[dict[str, Any]]:
        """Get customer ratings for a specific driver."""
        driver_obj = self.get_driver(driver_id)
        d_keys = {str(driver_id).strip().lower()}
        if driver_obj:
            d_keys.add(str(driver_obj.id).strip().lower())
            if driver_obj.telegram_user_id:
                d_keys.add(str(driver_obj.telegram_user_id).strip().lower())
            if driver_obj.name:
                d_keys.add(str(driver_obj.name).strip().lower())
            if driver_obj.phone:
                d_keys.add(re.sub(r"\D", "", str(driver_obj.phone)))

        all_ratings = self.get_all_ratings_admin(tenant_id, limit=500)
        filtered = []
        for r in all_ratings:
            r_drv = str(r.get("driver_id") or "").strip().lower()
            r_name = str(r.get("driver_name") or "").strip().lower()
            if r_drv in d_keys or r_name in d_keys:
                filtered.append(r)
        return filtered[:limit]

    def get_driver_rating_stats(self, tenant_id: str, driver_id: Any) -> dict[str, Any]:
        """Get average rating and breakdown stats for a driver."""
        ratings = self.get_driver_ratings(tenant_id, driver_id, limit=500)
        if not ratings:
            return {
                "average": 5.0,
                "count": 0,
                "breakdown": {5: 0, 4: 0, 3: 0, 2: 0, 1: 0},
            }
        total = len(ratings)
        avg = round(sum(int(r["rating"]) for r in ratings) / total, 1)
        breakdown = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for r in ratings:
            star = int(r.get("rating") or 5)
            if star in breakdown:
                breakdown[star] += 1
            else:
                breakdown[5] += 1
        return {
            "average": avg,
            "count": total,
            "breakdown": breakdown,
        }

    def get_tank_readings_by_driver(self, tenant_id: str, driver_id: Any) -> list[dict[str, Any]]:
        """Get tank readings for driver."""
        return []

    def get_all_tank_readings(self, tenant_id: str = "petroil", limit: int = 100) -> list[dict[str, Any]]:
        """Get all tank readings for Admin UI."""
        return []

    def set_order_live_location(
        self, tenant_id: str, order_id: Any, chat_id: str, message_id: int
    ) -> bool:
        """Store Telegram/WhatsApp live location message ID and chat ID for an active order."""
        key = str(order_id)
        self._order_live_locations[key] = {
            "message_id": message_id,
            "chat_id": str(chat_id),
        }
        if order_id in self._order_id_map:
            cached = self._order_id_map[order_id]
            cached["live_location_message_id"] = message_id
            cached["live_location_chat_id"] = str(chat_id)
        if key in self._order_id_map:
            cached = self._order_id_map[key]
            cached["live_location_message_id"] = message_id
            cached["live_location_chat_id"] = str(chat_id)
        try:
            identity_store.save_order_live_location(order_id, chat_id, message_id)
        except Exception:
            pass
        return True

    def clear_order_live_location(self, tenant_id: str, order_id: Any) -> bool:
        """Clear live location tracking for order."""
        key = str(order_id)
        self._order_live_locations.pop(key, None)
        if order_id in self._order_id_map:
            cached = self._order_id_map[order_id]
            cached["live_location_message_id"] = None
            cached["live_location_chat_id"] = None
        if key in self._order_id_map:
            cached = self._order_id_map[key]
            cached["live_location_message_id"] = None
            cached["live_location_chat_id"] = None
        try:
            identity_store.clear_order_live_location(order_id)
        except Exception:
            pass
        return True

    def add_order_driver_message_id(self, tenant_id: str, order_id: Any, message_id: int) -> bool:
        """Store Telegram message ID sent to the driver for this order."""
        key = str(order_id)
        if not isinstance(getattr(self, "_order_driver_msg_ids", None), dict):
            self._order_driver_msg_ids = {}
        lst = self._order_driver_msg_ids.setdefault(key, [])
        if message_id not in lst:
            lst.append(message_id)
        return True

    def get_order_driver_message_ids(self, tenant_id: str, order_id: Any) -> list[int]:
        """Retrieve all Telegram message IDs sent to the driver for this order."""
        key = str(order_id)
        if not isinstance(getattr(self, "_order_driver_msg_ids", None), dict):
            return []
        return list(self._order_driver_msg_ids.get(key, []))

    def clear_order_driver_message_ids(self, tenant_id: str, order_id: Any) -> bool:
        """Clear the driver message IDs for an order."""
        key = str(order_id)
        if isinstance(getattr(self, "_order_driver_msg_ids", None), dict):
            self._order_driver_msg_ids.pop(key, None)
        return True

    def update_order_status(
        self,
        tenant_id: str,
        order_id: Any,
        status: str = "",
        notes_append: str = "",
        driver_id: Any = None,
        driver_name: str | None = None,
        reason: str | None = None,
        cancelled_by: str | None = None,
        **kwargs: Any,
    ) -> Order | None:
        """Update order status in NestJS API."""
        effective_status = status or kwargs.get("new_status", "pending")
        status_map = {
            "in_route": "EN_RUTA",
            "en_ruta": "EN_RUTA",
            "en_reparto": "EN_RUTA",
            "en_camino": "EN_RUTA",
            "delivered": "ENTREGADO",
            "entregado": "ENTREGADO",
            "cancelled": "CANCELADO",
            "cancelado": "CANCELADO",
            "pending": "PENDIENTE",
            "pendiente": "PENDIENTE",
            "assigned": "ASIGNADO",
            "asignado": "ASIGNADO",
            "scheduled": "PROGRAMADO",
            "programado": "PROGRAMADO",
            "confirmed": "CONFIRMADO",
            "confirmado": "CONFIRMADO",
            "rejected_by_driver": "RECHAZADO",
            "rechazado": "RECHAZADO",
        }
        api_status = status_map.get(effective_status.lower(), effective_status.upper())

        scheduled_for = kwargs.get("scheduled_for")
        delivery_schedule = kwargs.get("delivery_schedule")

        body = {
            "status": api_status,
            "description": reason or notes_append or f"Estado actualizado a {api_status}",
            "actor": "CHOFER" if driver_id else "SISTEMA",
        }
        if driver_id:
            body["driverId"] = str(driver_id)
        if reason:
            body["rejectionReason"] = reason
        if scheduled_for:
            body["scheduledFor"] = to_utc_iso(scheduled_for)
        if delivery_schedule:
            body["deliverySchedule"] = delivery_schedule

        target_uuid = self._resolve_order_uuid(order_id)
        if delivery_schedule or scheduled_for:
            for k in (order_id, str(order_id), target_uuid):
                if k:
                    self._order_schedules[str(k)] = {
                        "delivery_schedule": delivery_schedule,
                        "scheduled_for": scheduled_for,
                    }
                    identity_store.save_order_schedule(k, delivery_schedule, scheduled_for)
        # Update local memory map immediately for all key aliases
        for key in (order_id, str(order_id), target_uuid):
            if key and key in self._order_id_map:
                self._order_id_map[key]["status"] = api_status
                if cancelled_by:
                    self._order_id_map[key]["cancelledBy"] = cancelled_by
                    self._order_id_map[key]["cancelled_by"] = cancelled_by
                if reason:
                    self._order_id_map[key]["rejectionReason"] = reason
                if api_status in ("RECHAZADO", "CANCELADO"):
                    self._order_id_map[key]["driverId"] = None
                    self._order_id_map[key]["driverName"] = None

        # Synchronize fallback repository
        if self.fallback_repo:
            try:
                self.fallback_repo.update_order_status(
                    tenant_id=tenant_id,
                    order_id=order_id,
                    status=effective_status,
                    notes_append=notes_append or reason or "",
                    driver_id=driver_id,
                    **kwargs,
                )
            except Exception:
                pass

        # Central API Driver Status Endpoint:
        # PUT /api/admin/drivers/:driverId/orders/:orderId/status
        # Header: x-tenant-id: petroil
        # Supports: EN_RUTA, ENTREGADO (with signature Base64), CANCELADO (with reason)
        eff_driver_id = driver_id
        if not eff_driver_id and target_uuid:
            cached = self._order_id_map.get(target_uuid) or self._order_id_map.get(order_id)
            if cached and cached.get("driverId"):
                eff_driver_id = cached.get("driverId")

        if eff_driver_id:
            d_obj = self.get_driver(eff_driver_id)
            target_driver_uuid = str(d_obj.id).strip() if (d_obj and d_obj.id) else str(eff_driver_id).strip()
            driver_status_body: dict[str, Any] = {"status": api_status}
            signature = kwargs.get("signature")
            if signature:
                driver_status_body["signature"] = signature
            if api_status in ("CANCELADO", "RECHAZADO") and (reason or notes_append):
                driver_status_body["reason"] = reason or notes_append

            try:
                res = api_put(f"/admin/drivers/{target_driver_uuid}/orders/{target_uuid}/status", driver_status_body, timeout=5)
                if isinstance(res, dict):
                    self._record_api_success()
                    logger.info(f"[ApiRepository] Driver status updated via /admin/drivers/{target_driver_uuid}/orders/{target_uuid}/status -> {api_status}")
                    return self._parse_api_order(res, tenant_id)
            except Exception as e:
                logger.debug(f"[ApiRepository] Note: /admin/drivers/{target_driver_uuid}/orders/{target_uuid}/status fallback: {e}")

        # General order status fallback
        try:
            res = api_patch(f"/orders/{target_uuid}/status", body, timeout=5)
            if isinstance(res, dict):
                self._record_api_success()
                return self._parse_api_order(res, tenant_id)
        except Exception as e:
            self._record_api_failure(e)

        order_obj = self.get_order_by_id(tenant_id, order_id)
        if order_obj:
            order_obj.status = effective_status
            return order_obj
        return None

    def cancel_order(
        self,
        tenant_id: str,
        order_id: Any,
        cancelled_by: str = "el cliente",
        reason: str = "Cancelado a solicitud del cliente",
    ) -> Order | None:
        """Cancel order via REST API."""
        identity_store.save_order_cancellation(order_id, cancelled_by=cancelled_by, reason=reason)
        try:
            from src.services.order_events import _EVENT_DEDUP_CACHE
            import time
            _EVENT_DEDUP_CACHE[f"cancelled:{order_id}"] = time.time()
        except Exception:
            pass
        return self.update_order_status(
            tenant_id=tenant_id,
            order_id=order_id,
            new_status="cancelled",
            reason=reason,
            cancelled_by=cancelled_by,
        )

    def update_order_delivery_coords(
        self, tenant_id: str, order_id: Any, delivery_lat: float, delivery_lng: float, delivery_address: str | None = None
    ) -> bool:
        """Update delivery coordinates and address in cache and fallback repo."""
        target_uuid = self._resolve_order_uuid(order_id)
        for key in (order_id, str(order_id), target_uuid):
            if key and key in self._order_id_map:
                self._order_id_map[key]["deliveryLat"] = delivery_lat
                self._order_id_map[key]["deliveryLng"] = delivery_lng
                if delivery_address:
                    self._order_id_map[key]["deliveryAddress"] = delivery_address

        if self.fallback_repo and hasattr(self.fallback_repo, "update_order_delivery_coords"):
            try:
                return self.fallback_repo.update_order_delivery_coords(tenant_id, order_id, delivery_lat, delivery_lng, delivery_address)
            except Exception:
                pass
        return True

    def cancel_all_orders_for_driver(
        self, tenant_id: str, driver_id: Any, reason: str = "Cancelación múltiple por chofer"
    ) -> int:
        """Release and cancel all active orders currently assigned to a driver in PostgreSQL API."""
        if not driver_id:
            return 0
        driver_obj = self.get_driver(driver_id)
        driver_name = driver_obj.name if driver_obj else f"Chofer #{driver_id}"
        active_orders = self.get_orders_by_driver(tenant_id, driver_id, active_only=True)
        count = 0
        for ord_obj in active_orders:
            try:
                self.update_order_status(
                    tenant_id=tenant_id,
                    order_id=ord_obj.id,
                    status="rejected_by_driver",
                    reason=reason,
                    notes_append=f"Liberado por {driver_name}: {reason}",
                    driver_id=driver_id,
                    driver_name=driver_name,
                )
                count += 1
            except Exception as e:
                logger.warning(f"[ApiRepository] Error cancelling order {ord_obj.id} for driver {driver_id}: {e}")

        # Set driver availability back to True
        try:
            self.set_driver_availability(driver_id, True)
        except Exception as e:
            logger.warning(f"[ApiRepository] Error setting driver availability: {e}")

        # Synchronize fallback repository if present
        if self.fallback_repo and hasattr(self.fallback_repo, "cancel_all_orders_for_driver"):
            try:
                self.fallback_repo.cancel_all_orders_for_driver(tenant_id, driver_id, reason)
            except Exception:
                pass

        return count

    def record_order_rejection(
        self, tenant_id: str, order_id: Any, driver_id: Any, driver_name: str, reason: str
    ) -> dict[str, Any]:
        """Record an incident where a driver rejected or cancelled an assigned order in PostgreSQL API."""
        now_iso = datetime.now(timezone.utc).isoformat()
        clean_reason = (reason or "Rechazado por chofer").strip()

        # Update order status to rejected_by_driver in API and local cache
        self.update_order_status(
            tenant_id=tenant_id,
            order_id=order_id,
            status="rejected_by_driver",
            reason=clean_reason,
            notes_append=f"Rechazado por {driver_name}: {clean_reason}",
            driver_id=driver_id,
            driver_name=driver_name,
        )

        # Restore driver availability to True
        if driver_id:
            try:
                self.set_driver_availability(driver_id, True)
            except Exception as e:
                logger.warning(f"[ApiRepository] Error restoring driver availability after rejection: {e}")

        # Synchronize fallback repository if present
        if self.fallback_repo and hasattr(self.fallback_repo, "record_order_rejection"):
            try:
                return self.fallback_repo.record_order_rejection(
                    tenant_id=tenant_id,
                    order_id=order_id,
                    driver_id=driver_id,
                    driver_name=driver_name,
                    reason=clean_reason,
                )
            except Exception:
                pass

        return {
            "order_id": order_id,
            "driver_id": driver_id,
            "driver_name": driver_name,
            "reason": clean_reason,
            "is_resolved": 0,
            "created_at": now_iso,
        }

    def _parse_api_order(self, ord_dict: dict, tenant_id: str) -> Order:
        """Convert API order dictionary to Order model."""
        items = []
        for it in ord_dict.get("items", []):
            p_info = it.get("product") or {}
            try:
                raw_q = float(it.get("quantity", 1))
                item_qty = int(raw_q) if raw_q.is_integer() else round(raw_q, 2)
            except (ValueError, TypeError):
                item_qty = 1
            items.append(
                OrderItem(
                    product_id=it.get("productId", ""),
                    product_name=it.get("productName", p_info.get("name", "Gas LP")),
                    quantity=item_qty,
                    unit_price=float(it.get("unitPrice", p_info.get("pricePerUnit", 0.0))),
                    subtotal=float(it.get("subtotal", 0.0)),
                )
            )

        raw_id = ord_dict.get("orderNumber") or ord_dict.get("id") or 1
        digits = re.findall(r"\d+", str(raw_id))
        num_id = int(digits[-1]) if digits else (hash(str(raw_id)) % 100000)

        # Store in mapping cache so lookups by num_id, UUID, or orderNumber all succeed
        self._order_id_map[num_id] = ord_dict
        self._order_id_map[str(num_id)] = ord_dict
        if ord_dict.get("id"):
            self._order_id_map[str(ord_dict.get("id"))] = ord_dict
        if ord_dict.get("orderNumber"):
            self._order_id_map[str(ord_dict.get("orderNumber"))] = ord_dict

        cust = ord_dict.get("customer") or {}
        local_status = self._map_api_status_to_local(ord_dict.get("status"))

        # Interceptar error del dashboard externo donde asignación de chofer envía erróneamente ENTREGADO
        if local_status == "delivered":
            last_trace_desc = ""
            is_erroneous_delivery = False
            for tr in (ord_dict.get("traceability") or []):
                tr_status = str(tr.get("status") or "").upper()
                tr_desc = str(tr.get("description") or "").lower()
                tr_actor = str(tr.get("actor") or "").upper()
                if tr_desc:
                    last_trace_desc = tr_desc
                if tr_status in ("ENTREGADO", "DELIVERED"):
                    if any(k in tr_desc for k in ["salir a ruta", "unidad asignada", "asignad", "lista para salir"]) or tr_actor in ("OPERADOR_CENTRAL", "CENTRAL"):
                        if not any(k in tr_desc for k in ["entregado exitosamente", "firma registrada", "foto"]):
                            is_erroneous_delivery = True
            if is_erroneous_delivery or any(k in last_trace_desc for k in ["salir a ruta", "unidad asignada", "lista para salir"]):
                local_status = "assigned"
                try:
                    target_uuid = self._resolve_order_uuid(ord_dict.get("id") or raw_id)
                    api_patch(f"/orders/{target_uuid}/status", {"status": "ASIGNADO", "description": "Auto-corrección: Unidad asignada a chofer", "actor": "SISTEMA"}, timeout=3)
                except Exception:
                    pass

        sched_for = ord_dict.get("scheduledFor") or ord_dict.get("scheduled_for")
        sched_schedule = ord_dict.get("deliverySchedule") or ord_dict.get("delivery_schedule")

        sched_info = (
            self._order_schedules.get(str(num_id))
            or self._order_schedules.get(str(raw_id))
            or self._order_schedules.get(str(ord_dict.get("id")))
            or self._order_schedules.get(str(ord_dict.get("orderNumber")))
            or identity_store.get_order_schedule(num_id)
            or identity_store.get_order_schedule(raw_id)
            or identity_store.get_order_schedule(ord_dict.get("id"))
            or identity_store.get_order_schedule(ord_dict.get("orderNumber"))
        )
        if sched_info:
            sched_schedule = sched_info.get("delivery_schedule") or sched_schedule
            sched_for = sched_info.get("scheduled_for") or sched_for

        now_dt = get_local_now()
        is_order_asap = (
            not sched_schedule
            or sched_schedule == "Lo antes posible"
            or any(w in str(sched_schedule).lower() for w in [
                "lo antes posible", "inmediato", "urgente", "ahorita", "ahora", "asap",
                "lo mas pronto", "lo más pronto", "ya mismo", "ya", "en cuanto puedan", "cuanto antes"
            ])
        )

        if is_order_asap:
            sched_schedule = "Lo antes posible"
            sched_for = None
            deadline_dt = None
            if local_status == "scheduled":
                api_st = str(ord_dict.get("status", "")).upper()
                local_status = "confirmed" if api_st in ("CONFIRMADO", "PENDIENTE") else "pending"
        else:
            deadline_dt = normalize_schedule_datetime(sched_for, now_dt)
            if not deadline_dt and sched_schedule:
                deadline_dt = normalize_schedule_datetime(sched_schedule, now_dt)

            if deadline_dt:
                sched_for = deadline_dt.isoformat()
                if not sched_schedule or ("t" in str(sched_schedule).lower() and len(str(sched_schedule)) >= 19):
                    sched_schedule = format_schedule_display(deadline_dt, now_dt)
            elif not sched_schedule:
                sched_schedule = "Lo antes posible"

            if deadline_dt:
                activation_time = deadline_dt - timedelta(minutes=30)
                if now_dt < activation_time:
                    if local_status in ("confirmed", "pending", "draft", "scheduled"):
                        local_status = "scheduled"
                elif local_status == "scheduled":
                    local_status = "confirmed"
            elif str(ord_dict.get("status", "")).upper() in ("PROGRAMADO", "SCHEDULED"):
                local_status = "scheduled"

        lat = ord_dict.get("deliveryLat") or ord_dict.get("delivery_lat") or ord_dict.get("latitude")
        lng = ord_dict.get("deliveryLng") or ord_dict.get("delivery_lng") or ord_dict.get("longitude")

        # Resolve live location
        live_loc_data = (
            self._order_live_locations.get(str(num_id))
            or self._order_live_locations.get(str(ord_dict.get("id")))
            or self._order_live_locations.get(str(ord_dict.get("orderNumber")))
        )
        if not live_loc_data:
            try:
                live_loc_data = (
                    identity_store.get_order_live_location(num_id)
                    or identity_store.get_order_live_location(str(ord_dict.get("id")))
                    or identity_store.get_order_live_location(str(ord_dict.get("orderNumber")))
                )
            except Exception:
                live_loc_data = None
        live_loc_data = live_loc_data or {}
        live_msg_id = live_loc_data.get("message_id") or ord_dict.get("live_location_message_id")
        live_chat_id = live_loc_data.get("chat_id") or ord_dict.get("live_location_chat_id")

        # Resolve real channel and channel_user_id (memory + persistent store)
        saved_channel_info = (
            self._order_channel_user_ids.get(num_id)
            or self._order_channel_user_ids.get(str(num_id))
            or self._order_channel_user_ids.get(str(ord_dict.get("id")))
            or self._order_channel_user_ids.get(str(ord_dict.get("orderNumber")))
        )
        if not saved_channel_info:
            persisted_info = (
                identity_store.get_order_channel_info(num_id)
                or identity_store.get_order_channel_info(str(ord_dict.get("id")))
                or identity_store.get_order_channel_info(str(ord_dict.get("orderNumber")))
            )
            if persisted_info:
                saved_channel_info = (persisted_info.get("channel", "telegram"), persisted_info.get("channel_user_id", ""))

        if saved_channel_info:
            eff_channel, eff_channel_user_id = saved_channel_info
        else:
            eff_channel = str(ord_dict.get("channel") or "telegram").lower()
            eff_channel_user_id = str(ord_dict.get("channelUserId") or ord_dict.get("channel_user_id") or "")
            if not eff_channel_user_id:
                cust_phone_clean = re.sub(r"\D", "", str(ord_dict.get("customerPhone") or cust.get("phone") or ""))
                tg_chat_id = self.get_telegram_chat_id_for_phone(cust_phone_clean)
                if tg_chat_id and eff_channel not in ("whatsapp", "messenger"):
                    eff_channel_user_id = tg_chat_id
                    eff_channel = "telegram"
                else:
                    eff_channel_user_id = cust_phone_clean

        canc_info = (
            identity_store.get_order_cancellation(num_id)
            or identity_store.get_order_cancellation(str(raw_id))
            or identity_store.get_order_cancellation(str(ord_dict.get("id")))
            or identity_store.get_order_cancellation(str(ord_dict.get("orderNumber")))
        )
        canc_by = (
            ord_dict.get("cancelledBy")
            or ord_dict.get("cancelled_by")
            or (canc_info.get("cancelled_by") if canc_info else None)
        )
        canc_reason = (
            ord_dict.get("rejectionReason")
            or ord_dict.get("cancellation_reason")
            or (canc_info.get("reason") if canc_info else None)
        )

        return Order(
            id=num_id,
            tenant_id=tenant_id,
            channel=eff_channel,
            channel_user_id=eff_channel_user_id,
            customer_name=ord_dict.get("customerName") or cust.get("name") or "Cliente",
            customer_phone=ord_dict.get("customerPhone") or cust.get("phone") or "",
            delivery_address=ord_dict.get("deliveryAddress") or cust.get("address") or "",
            delivery_schedule=sched_schedule,
            total_amount=float(ord_dict.get("totalAmount", 0.0)),
            status=local_status,
            payment_method=ord_dict.get("paymentMethod", "Efectivo"),
            notes=ord_dict.get("notes") or "",
            driver_id=ord_dict.get("driverId"),
            driver_name=ord_dict.get("driverName"),
            delivery_lat=float(lat) if lat else None,
            delivery_lng=float(lng) if lng else None,
            live_location_message_id=live_msg_id,
            live_location_chat_id=live_chat_id,
            scheduled_for=sched_for,
            cancelled_by=canc_by,
            cancellation_reason=canc_reason,
            items=items,
            created_at=ord_dict.get("createdAt") or ord_dict.get("created_at"),
        )

    def assign_order_to_driver(
        self,
        tenant_id: str,
        order_id: Any,
        driver_id: Any,
        delivery_lat: float | None = None,
        delivery_lng: float | None = None,
        force_activate: bool = False,
    ) -> Order | None:
        """Assign an order to a driver in PostgreSQL."""
        driver_obj = self.get_driver(driver_id) if driver_id else None
        driver_name = driver_obj.name if driver_obj else None
        driver_phone = driver_obj.phone if driver_obj else None
        canonical_driver_id = driver_obj.id if driver_obj else driver_id

        now_dt = datetime.now()
        existing_order = self.get_order_by_id(tenant_id, order_id)
        is_future_scheduled = False
        if existing_order and not force_activate and str(existing_order.status).lower() in ("scheduled", "programado"):
            s_for = existing_order.scheduled_for
            s_text = existing_order.delivery_schedule
            deadline_dt = normalize_schedule_datetime(s_for, now_dt)
            if not deadline_dt and s_text:
                deadline_dt = normalize_schedule_datetime(s_text, now_dt)
            if deadline_dt and now_dt < (deadline_dt - timedelta(minutes=30)):
                is_future_scheduled = True

        api_status_val = "PROGRAMADO" if is_future_scheduled else ("ASIGNADO" if canonical_driver_id else "CONFIRMADO")

        # Update cache if present
        for key in (order_id, str(order_id)):
            if key in self._order_id_map:
                ord_data = self._order_id_map[key]
                ord_data["status"] = api_status_val
                ord_data["driverId"] = canonical_driver_id
                ord_data["driverName"] = driver_name
                ord_data["driverPhone"] = driver_phone
                if delivery_lat is not None:
                    ord_data["deliveryLat"] = delivery_lat
                if delivery_lng is not None:
                    ord_data["deliveryLng"] = delivery_lng

        # Try API update
        try:
            body = {
                "status": api_status_val,
                "driverId": str(canonical_driver_id) if canonical_driver_id else None,
                "driverName": driver_name,
                "driverPhone": driver_phone,
            }
            if delivery_lat is not None:
                body["deliveryLat"] = delivery_lat
            if delivery_lng is not None:
                body["deliveryLng"] = delivery_lng
            target_uuid = self._resolve_order_uuid(order_id)
            api_patch(f"/orders/{target_uuid}/status", body, timeout=5)
        except Exception:
            pass

        if self.fallback_repo:
            try:
                self.fallback_repo.assign_order_to_driver(
                    tenant_id=tenant_id,
                    order_id=order_id,
                    driver_id=canonical_driver_id,
                    delivery_lat=delivery_lat,
                    delivery_lng=delivery_lng,
                    force_activate=force_activate,
                )
            except Exception:
                pass

        order = self.get_order_by_id(tenant_id, order_id)
        if order:
            order.status = "scheduled" if is_future_scheduled else ("assigned" if canonical_driver_id else "confirmed")
            order.driver_id = canonical_driver_id
            order.driver_name = driver_name
            if delivery_lat is not None:
                order.delivery_lat = delivery_lat
            if delivery_lng is not None:
                order.delivery_lng = delivery_lng
            return order
        return None

    def __getattr__(self, item: str) -> Any:
        """If fallback_repo is present, delegate; otherwise return a safe no-op callable or None."""
        if self.fallback_repo:
            return getattr(self.fallback_repo, item)
        def _noop(*args: Any, **kwargs: Any) -> Any:
            return None
        return _noop

