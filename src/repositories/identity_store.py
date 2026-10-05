"""Persistent Cross-Process Identity and Channel Store for Telegram and WhatsApp.

Ensures that customer Telegram Chat IDs, WhatsApp numbers, and Order Channel mappings
are shared reliably across separate processes (telegram_bot.py, driver_bot.py, uvicorn).
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
CACHE_FILE = DATA_DIR / "channel_identity_cache.json"


class IdentityStore:
    """Thread-safe and process-safe identity and order-channel mapping store."""

    _instance: IdentityStore | None = None

    def __init__(self) -> None:
        self._phone_to_tg: dict[str, str] = {}
        self._tg_to_phone: dict[str, str] = {}
        self._order_channels: dict[str, dict[str, str]] = {}
        self._order_ratings: dict[str, dict[str, Any]] = {}
        self._order_schedules: dict[str, dict[str, Any]] = {}
        self._order_client_messages: dict[str, list[dict[str, Any]]] = {}
        self._order_live_locations: dict[str, dict[str, Any]] = {}
        self._chat_live_locations: dict[str, dict[str, Any]] = {}
        self._deleted_addresses: dict[str, list[str]] = {}
        self._order_cancellations: dict[str, dict[str, Any]] = {}
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._load()

    @classmethod
    def get_instance(cls) -> IdentityStore:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load(self) -> None:
        if not CACHE_FILE.exists():
            return
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    self._phone_to_tg = data.get("phone_to_tg", {})
                    self._tg_to_phone = data.get("tg_to_phone", {})
                    self._order_channels = data.get("order_channels", {})
                    self._order_ratings = data.get("order_ratings", {})
                    self._order_schedules = data.get("order_schedules", {})
                    self._order_client_messages = data.get("order_client_messages", {})
                    self._order_live_locations = data.get("order_live_locations", {})
                    self._chat_live_locations = data.get("chat_live_locations", {})
                    self._deleted_addresses = data.get("deleted_addresses", {})
                    self._order_cancellations = data.get("order_cancellations", {})
        except Exception as e:
            logger.debug(f"[IdentityStore] Error loading identity cache: {e}")

    def _save(self) -> None:
        try:
            temp_file = CACHE_FILE.with_suffix(".tmp")
            payload = {
                "phone_to_tg": self._phone_to_tg,
                "tg_to_phone": self._tg_to_phone,
                "order_channels": self._order_channels,
                "order_ratings": self._order_ratings,
                "order_schedules": self._order_schedules,
                "order_client_messages": self._order_client_messages,
                "order_live_locations": self._order_live_locations,
                "chat_live_locations": self._chat_live_locations,
                "deleted_addresses": self._deleted_addresses,
                "order_cancellations": self._order_cancellations,
            }
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            temp_file.replace(CACHE_FILE)
        except Exception as e:
            logger.debug(f"[IdentityStore] Error saving identity cache: {e}")

    def mark_address_deleted(self, phone: str, address_text: str) -> None:
        """Mark an address as explicitly deleted by the user for their phone number."""
        clean_p = re.sub(r"\D", "", str(phone or ""))
        if len(clean_p) > 10:
            clean_p = clean_p[-10:]
        if not clean_p or not address_text:
            return
        addr_key = address_text.strip().lower()
        curr = self._deleted_addresses.setdefault(clean_p, [])
        if addr_key not in curr:
            curr.append(addr_key)
            self._save()

    def is_address_deleted(self, phone: str, address_text: str) -> bool:
        """Check if an address has been deleted by the user."""
        clean_p = re.sub(r"\D", "", str(phone or ""))
        if len(clean_p) > 10:
            clean_p = clean_p[-10:]
        if not clean_p or not address_text:
            return False
        addr_key = address_text.strip().lower()
        curr = self._deleted_addresses.get(clean_p, [])
        return any(d == addr_key or d in addr_key or addr_key in d for d in curr)

    def unmark_address_deleted(self, phone: str, address_text: str) -> None:
        """If a user re-adds an address, unmark it."""
        clean_p = re.sub(r"\D", "", str(phone or ""))
        if len(clean_p) > 10:
            clean_p = clean_p[-10:]
        if not clean_p or not address_text:
            return
        addr_key = address_text.strip().lower()
        curr = self._deleted_addresses.get(clean_p, [])
        if addr_key in curr:
            curr.remove(addr_key)
            self._save()

    def bind_telegram_user_phone(self, telegram_user_id: str | int, phone: str) -> None:
        """Bind customer's phone number to their Telegram Chat ID."""
        if not telegram_user_id or not phone:
            return
        tg_id = str(telegram_user_id).strip()
        clean_digits = re.sub(r"\D", "", str(phone))
        if not tg_id or not clean_digits:
            return

        self._load()  # Sync latest from disk
        if len(clean_digits) >= 10:
            suffix_10 = clean_digits[-10:]
            self._phone_to_tg[suffix_10] = tg_id
            self._phone_to_tg[clean_digits] = tg_id

        self._phone_to_tg[tg_id] = tg_id
        self._tg_to_phone[tg_id] = clean_digits[-10:] if len(clean_digits) >= 10 else clean_digits
        self._save()
        logger.info(f"🔗 [IdentityStore] Bound Telegram Chat ID {tg_id} <-> Phone {clean_digits}")

    def get_telegram_chat_id(self, phone_or_user_id: str | int | None) -> str | None:
        """Resolve a phone number or user ID to a Telegram Chat ID."""
        if not phone_or_user_id:
            return None
        val_str = str(phone_or_user_id).strip()
        self._load()

        # If it's already in the cache
        if val_str in self._phone_to_tg:
            return self._phone_to_tg[val_str]

        clean_digits = re.sub(r"\D", "", val_str)
        if len(clean_digits) >= 10:
            suffix_10 = clean_digits[-10:]
            if suffix_10 in self._phone_to_tg:
                return self._phone_to_tg[suffix_10]
            if clean_digits in self._phone_to_tg:
                return self._phone_to_tg[clean_digits]

        return None

    def save_order_channel_info(
        self,
        order_id: Any,
        channel: str,
        channel_user_id: str,
        phone: str = "",
    ) -> None:
        """Store channel and recipient identifier for an order."""
        if not order_id:
            return
        self._load()
        s_id = str(order_id).strip()
        keys = [s_id]
        is_uuid = len(s_id) == 36 and s_id.count("-") == 4
        if not is_uuid:
            digits = re.findall(r"\d+", s_id)
            if digits:
                keys.append(str(int(digits[-1])))
                keys.append(digits[-1])

        info = {
            "channel": str(channel or "telegram").lower(),
            "channel_user_id": str(channel_user_id or ""),
            "phone": str(phone or ""),
        }
        for k in set(keys):
            self._order_channels[k] = info

        if phone and channel_user_id and str(channel).lower() == "telegram":
            self.bind_telegram_user_phone(channel_user_id, phone)

        self._save()

    def get_order_channel_info(self, order_id: Any) -> dict[str, str] | None:
        """Retrieve stored channel info for an order."""
        if not order_id:
            return None
        self._load()
        s_id = str(order_id).strip()
        if s_id in self._order_channels:
            return self._order_channels[s_id]
        is_uuid = len(s_id) == 36 and s_id.count("-") == 4
        if not is_uuid:
            digits = re.findall(r"\d+", s_id)
            if digits:
                num_str = str(int(digits[-1]))
                if num_str in self._order_channels:
                    return self._order_channels[num_str]
                if digits[-1] in self._order_channels:
                    return self._order_channels[digits[-1]]
        return None

    def get_phone_for_channel_user(self, channel: str, channel_user_id: str) -> str | None:
        """Resolve phone number for a channel user ID across registered orders or repositories."""
        if not channel_user_id:
            return None
        self._load()
        c_str = str(channel_user_id).strip()
        # 1. Search in order_channels
        for info in self._order_channels.values():
            if str(info.get("channel", "")).lower() == str(channel).lower():
                if str(info.get("channel_user_id", "")).strip() == c_str:
                    phone = info.get("phone")
                    if phone:
                        return phone
        # 2. Search in tg mapping if telegram
        if str(channel).lower() == "telegram":
            if c_str in self._tg_to_phone:
                return self._tg_to_phone[c_str]
        # 3. Fallback to repository
        try:
            from src.repositories import get_repository
            repo = get_repository()
            cust = repo.get_customer("petroil", str(channel).lower(), c_str)
            if cust and getattr(cust, "phone", None):
                return cust.phone
        except Exception:
            pass
        return None

    def save_order_rating(
        self,
        order_id: Any,
        driver_id: Any = None,
        customer_id: Any = None,
        rating: int = 5,
        feedback_tag: str = "",
        comment: str = "",
        created_at: str = "",
    ) -> dict[str, Any]:
        """Save a customer rating to persistent cross-process storage."""
        if not order_id:
            return {}
        self._load()
        rating_int = max(1, min(5, int(rating)))
        obj = {
            "order_id": str(order_id),
            "driver_id": str(driver_id) if driver_id else None,
            "customer_id": str(customer_id) if customer_id else None,
            "rating": rating_int,
            "feedback_tag": str(feedback_tag or ""),
            "comment": str(comment or ""),
            "created_at": created_at or None,
        }
        keys = [str(order_id)]
        digits = re.findall(r"\d+", str(order_id))
        if digits:
            keys.append(digits[-1])

        for k in keys:
            self._order_ratings[k] = obj

        self._save()
        logger.info(f"⭐ [IdentityStore] Saved persistent rating for Order #{order_id} -> {rating_int}/5 stars (Driver: {driver_id})")
        return obj

    def get_order_rating(self, order_id: Any) -> dict[str, Any] | None:
        """Get rating for a specific order."""
        if not order_id:
            return None
        self._load()
        s_id = str(order_id).strip()
        if s_id in self._order_ratings:
            return self._order_ratings[s_id]
        digits = re.findall(r"\d+", s_id)
        if digits and digits[-1] in self._order_ratings:
            return self._order_ratings[digits[-1]]
        return None

    def get_all_order_ratings(self) -> list[dict[str, Any]]:
        """Get all unique order ratings."""
        self._load()
        seen = set()
        unique = []
        for r in self._order_ratings.values():
            oid = str(r.get("order_id", ""))
            if oid and oid not in seen:
                seen.add(oid)
                unique.append(r)
        return unique

    def get_driver_ratings(self, driver_id: Any) -> list[dict[str, Any]]:
        """Get all ratings belonging to a specific driver."""
        if not driver_id:
            return []
        d_str = str(driver_id).strip()
        all_r = self.get_all_order_ratings()
        return [r for r in all_r if str(r.get("driver_id") or "").strip() == d_str]

    def save_order_schedule(
        self,
        order_id: Any,
        delivery_schedule: str,
        scheduled_for: str | None = None,
    ) -> None:
        """Store scheduled delivery time for an order across processes."""
        if not order_id:
            return
        self._load()
        keys = [str(order_id)]
        digits = re.findall(r"\d+", str(order_id))
        if digits:
            keys.append(digits[-1])

        info = {
            "delivery_schedule": str(delivery_schedule or "Lo antes posible"),
            "scheduled_for": str(scheduled_for) if scheduled_for else None,
        }
        for k in keys:
            self._order_schedules[k] = info
        self._save()

    def get_order_schedule(self, order_id: Any) -> dict[str, Any] | None:
        """Get scheduled delivery time for an order."""
        if not order_id:
            return None
        self._load()
        s_id = str(order_id).strip()
        if s_id in self._order_schedules:
            return self._order_schedules[s_id]
        digits = re.findall(r"\d+", s_id)
        if digits and digits[-1] in self._order_schedules:
            return self._order_schedules[digits[-1]]
        return None

    def save_order_cancellation(
        self,
        order_id: Any,
        cancelled_by: str = "el cliente",
        reason: str = "",
    ) -> None:
        """Store cancellation details for an order across processes."""
        if not order_id:
            return
        self._load()
        keys = [str(order_id)]
        digits = re.findall(r"\d+", str(order_id))
        if digits:
            keys.append(digits[-1])

        info = {
            "order_id": str(order_id),
            "cancelled_by": str(cancelled_by or "el cliente"),
            "reason": str(reason or ""),
        }
        for k in keys:
            self._order_cancellations[k] = info
        self._save()

    def get_order_cancellation(self, order_id: Any) -> dict[str, Any] | None:
        """Retrieve stored cancellation details for an order."""
        if not order_id:
            return None
        self._load()
        s_id = str(order_id).strip()
        if s_id in self._order_cancellations:
            return self._order_cancellations[s_id]
        digits = re.findall(r"\d+", s_id)
        if digits and digits[-1] in self._order_cancellations:
            return self._order_cancellations[digits[-1]]
        return None

    def add_order_client_message(self, order_id: Any, chat_id: str | int, message_id: int) -> None:
        """Store Telegram message ID sent to client for an order so buttons can be updated dynamically."""
        if not order_id or not message_id or not chat_id:
            return
        self._load()
        keys = [str(order_id)]
        digits = re.findall(r"\d+", str(order_id))
        if digits:
            keys.append(digits[-1])

        entry = {"chat_id": str(chat_id), "message_id": int(message_id)}
        for k in keys:
            lst = self._order_client_messages.setdefault(k, [])
            if not any(item.get("chat_id") == str(chat_id) and item.get("message_id") == int(message_id) for item in lst):
                lst.append(entry)
                self._order_client_messages[k] = lst[-20:]
        self._save()

    def get_order_client_messages(self, order_id: Any) -> list[dict[str, Any]]:
        """Retrieve all recorded Telegram message IDs sent to client for an order."""
        if not order_id:
            return []
        self._load()
        s_id = str(order_id).strip()
        if s_id in self._order_client_messages:
            return list(self._order_client_messages[s_id])
        digits = re.findall(r"\d+", s_id)
        if digits and digits[-1] in self._order_client_messages:
            return list(self._order_client_messages[digits[-1]])
        return []

    def clear_order_client_messages(self, order_id: Any, keep_message_id: int | None = None) -> list[dict[str, Any]]:
        """
        Clear or update client messages for an order.
        If keep_message_id is provided, retains only the entry matching keep_message_id.
        Returns the list of removed message entries.
        """
        if not order_id:
            return []
        self._load()
        keys = [str(order_id)]
        digits = re.findall(r"\d+", str(order_id))
        if digits:
            keys.append(digits[-1])

        removed: list[dict[str, Any]] = []
        for k in keys:
            current_list = self._order_client_messages.get(k, [])
            if keep_message_id is not None:
                new_list = [item for item in current_list if int(item.get("message_id", 0)) == int(keep_message_id)]
                for item in current_list:
                    if int(item.get("message_id", 0)) != int(keep_message_id) and item not in removed:
                        removed.append(item)
                self._order_client_messages[k] = new_list
            else:
                for item in current_list:
                    if item not in removed:
                        removed.append(item)
                self._order_client_messages.pop(k, None)

        self._save()
        return removed

    def save_order_live_location(self, order_id: Any, chat_id: str | int, message_id: int) -> None:
        """Store Telegram/WhatsApp live location pin message ID and chat ID for an active order."""
        if not order_id or not message_id:
            return
        self._load()
        keys = [str(order_id)]
        digits = re.findall(r"\d+", str(order_id))
        if digits:
            keys.append(digits[-1])

        entry = {
            "message_id": int(message_id),
            "chat_id": str(chat_id),
            "order_id": str(order_id),
        }
        for k in keys:
            self._order_live_locations[k] = entry

        if chat_id:
            c_str = str(chat_id).strip()
            self._chat_live_locations[c_str] = {
                "message_id": int(message_id),
                "order_id": str(order_id),
            }
            c_digits = re.sub(r"\D", "", c_str)
            if c_digits:
                self._chat_live_locations[c_digits] = {
                    "message_id": int(message_id),
                    "order_id": str(order_id),
                }

        self._save()

    def get_order_live_location(self, order_id: Any) -> dict[str, Any] | None:
        """Retrieve live location info for an order."""
        if not order_id:
            return None
        self._load()
        s_id = str(order_id).strip()
        if s_id in self._order_live_locations:
            return dict(self._order_live_locations[s_id])
        digits = re.findall(r"\d+", s_id)
        if digits and digits[-1] in self._order_live_locations:
            return dict(self._order_live_locations[digits[-1]])
        return None

    def get_chat_live_location(self, chat_id: str | int | None) -> dict[str, Any] | None:
        """Retrieve active live location info by chat_id or phone."""
        if not chat_id:
            return None
        self._load()
        c_str = str(chat_id).strip()
        if c_str in self._chat_live_locations:
            return dict(self._chat_live_locations[c_str])
        c_digits = re.sub(r"\D", "", c_str)
        if c_digits and c_digits in self._chat_live_locations:
            return dict(self._chat_live_locations[c_digits])
        if len(c_digits) >= 10 and c_digits[-10:] in self._chat_live_locations:
            return dict(self._chat_live_locations[c_digits[-10:]])
        return None

    def clear_order_live_location(self, order_id: Any) -> dict[str, Any] | None:
        """Clear live location tracking for an order and its associated chat."""
        if not order_id:
            return None
        self._load()
        keys = [str(order_id)]
        digits = re.findall(r"\d+", str(order_id))
        if digits:
            keys.append(digits[-1])

        removed: dict[str, Any] | None = None
        for k in keys:
            entry = self._order_live_locations.pop(k, None)
            if entry and not removed:
                removed = entry

        if removed and removed.get("chat_id"):
            c_str = str(removed["chat_id"]).strip()
            self._chat_live_locations.pop(c_str, None)
            c_digits = re.sub(r"\D", "", c_str)
            if c_digits:
                self._chat_live_locations.pop(c_digits, None)
                if len(c_digits) >= 10:
                    self._chat_live_locations.pop(c_digits[-10:], None)

        self._save()
        return removed


# Global singleton instance
identity_store = IdentityStore.get_instance()
