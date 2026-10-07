"""Unit tests for Scheduled Orders Agenda and 30-minute Pre-Deadline Activation."""

import os
import unittest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

from src.app import app
from src.repositories.sqlite_repo import SqliteRepository, parse_schedule_deadline


class TestScheduledAgenda(unittest.TestCase):
    def setUp(self):
        self.orig_data_source = os.environ.get("DATA_SOURCE")
        os.environ["DATA_SOURCE"] = "sqlite"
        self.repo = SqliteRepository()
        self.tenant_id = "petroil"
        self.client = TestClient(app)

    def tearDown(self):
        if self.orig_data_source is not None:
            os.environ["DATA_SOURCE"] = self.orig_data_source
        else:
            os.environ.pop("DATA_SOURCE", None)

    def test_parse_schedule_deadline(self):
        ref = datetime(2026, 9, 3, 14, 0, 0)
        
        # Hoy a las 5:00 PM -> 2026-09-03 17:00
        dt = parse_schedule_deadline("Hoy a las 5:00 PM", ref)
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 9)
        self.assertEqual(dt.day, 3)
        self.assertEqual(dt.hour, 17)
        self.assertEqual(dt.minute, 0)

        # Mañana a las 10:30 AM -> 2026-09-04 10:30
        dt2 = parse_schedule_deadline("Mañana a las 10:30 AM", ref)
        self.assertIsNotNone(dt2)
        self.assertEqual(dt2.day, 4)
        self.assertEqual(dt2.hour, 10)
        self.assertEqual(dt2.minute, 30)

        # Lo antes posible -> None (immediate)
        dt3 = parse_schedule_deadline("Lo antes posible", ref)
        self.assertIsNone(dt3)

    def test_future_order_stays_in_agenda_and_not_in_active_table(self):
        now = datetime.now()
        # Scheduled for 3 hours from now (> 30 min)
        future_dt = now + timedelta(hours=3)
        schedule_text = f"Hoy a las {future_dt.strftime('%I:%M %p')}"

        order = self.repo.create_order(
            tenant_id=self.tenant_id,
            customer_name="Cliente Test Agenda Futuro",
            customer_phone="6699990001",
            delivery_address="Av. Del Mar 123, Mazatlán",
            items=[{"product_name": "Cilindro de Gas LP 30 kg", "quantity": 1, "unit_price": 650.0}],
            delivery_schedule=schedule_text,
            scheduled_for=future_dt.isoformat(),
        )

        self.assertIsNotNone(order.id)
        self.assertEqual(order.status, "scheduled")
        self.assertIsNotNone(order.scheduled_for)

        # Verify it appears in the Agenda
        agenda = self.repo.get_scheduled_agenda(self.tenant_id)
        agenda_ids = [item["id"] for item in agenda]
        self.assertIn(order.id, agenda_ids)

        # Locate item in agenda and verify computed properties
        agenda_item = next(item for item in agenda if item["id"] == order.id)
        self.assertFalse(agenda_item["is_activated"])
        self.assertGreater(agenda_item["minutes_until_activation"], 0)

        # Verify it DOES NOT appear in the active orders table (because it's > 30m away)
        active_orders = self.repo.get_all_orders_admin(self.tenant_id, status="active")
        active_ids = [o["id"] for o in active_orders]
        self.assertNotIn(order.id, active_ids)

    def test_order_within_30_minutes_is_activated_in_orders_table(self):
        now = datetime.now()
        # Scheduled for 15 minutes from now (<= 30 min)
        soon_dt = now + timedelta(minutes=15)
        schedule_text = f"Hoy a las {soon_dt.strftime('%I:%M %p')}"

        order = self.repo.create_order(
            tenant_id=self.tenant_id,
            customer_name="Cliente Test Proximo",
            customer_phone="6699990002",
            delivery_address="Zona Dorada 456, Mazatlán",
            items=[{"product_name": "Cilindro de Gas LP 20 kg", "quantity": 1, "unit_price": 450.0}],
            delivery_schedule=schedule_text,
            scheduled_for=soon_dt.isoformat(),
        )

        # Because it is within 30 min, initial_status should be confirmed and active
        self.assertEqual(order.status, "confirmed")

        # Verify it appears in active orders table
        active_orders = self.repo.get_all_orders_admin(self.tenant_id, status="active")
        active_ids = [o["id"] for o in active_orders]
        self.assertIn(order.id, active_ids)

    def test_manual_activate_now_endpoint(self):
        now = datetime.now()
        # Create order scheduled 4 hours from now
        future_dt = now + timedelta(hours=4)
        order = self.repo.create_order(
            tenant_id=self.tenant_id,
            customer_name="Cliente Test Manual Activate",
            customer_phone="6699990003",
            delivery_address="Centro Histórico 789, Mazatlán",
            items=[{"product_name": "Cilindro de Gas LP 30 kg", "quantity": 1, "unit_price": 650.0}],
            delivery_schedule="Hoy en la tarde",
            scheduled_for=future_dt.isoformat(),
        )

        self.assertEqual(order.status, "scheduled")

        # Call POST /api/admin/orders/{id}/activate-now
        res = self.client.post(f"/api/admin/orders/{order.id}/activate-now")
        self.assertEqual(res.status_code, 200)

        # Verify it is now confirmed, assigned or in_route (active)
        updated = self.repo.get_order_by_id(self.tenant_id, order.id)
        self.assertIn(updated.status, ("confirmed", "assigned", "in_route"))

        # And appears in active orders
        active_orders = self.repo.get_all_orders_admin(self.tenant_id, status="active", limit=200)
        active_ids = [o["id"] for o in active_orders]
        self.assertIn(order.id, active_ids)

    def test_reschedule_endpoint(self):
        now = datetime.now()
        order = self.repo.create_order(
            tenant_id=self.tenant_id,
            customer_name="Cliente Test Reschedule",
            customer_phone="6699990004",
            delivery_address="Marina Mazatlán 101",
            items=[{"product_name": "Gas Estacionario 200L", "quantity": 1, "unit_price": 2600.0}],
            delivery_schedule="Hoy a las 4:00 PM",
        )

        # Reschedule for tomorrow 11:00 AM
        tomorrow_11am = (now + timedelta(days=1)).replace(hour=11, minute=0, second=0, microsecond=0)
        res = self.client.post(
            f"/api/admin/orders/{order.id}/reschedule",
            json={
                "delivery_schedule": "Mañana a las 11:00 AM",
                "scheduled_for": tomorrow_11am.isoformat(),
            }
        )
        self.assertEqual(res.status_code, 200)

        updated = self.repo.get_order_by_id(self.tenant_id, order.id)
        self.assertEqual(updated.delivery_schedule, "Mañana a las 11:00 AM")
        self.assertEqual(updated.status, "scheduled")

        agenda = self.repo.get_scheduled_agenda(self.tenant_id)
        item = next((x for x in agenda if x["id"] == order.id), None)
        self.assertIsNotNone(item)
        self.assertIn("Mañana", item["deadline_display"])

    def test_agenda_ordered_by_deadline_ascending(self):
        """Verify that scheduled agenda orders are sorted strictly by scheduled delivery time ascending."""
        now = datetime.now()
        # Create orders out of chronological order
        t_late = now + timedelta(hours=5)
        t_early = now + timedelta(hours=2)
        t_tomorrow = now + timedelta(days=1, hours=3)

        o_late = self.repo.create_order(
            tenant_id=self.tenant_id,
            customer_name="Cliente Tarde",
            customer_phone="6699990010",
            delivery_address="Dirección 1",
            items=[{"product_name": "Gas 30kg", "quantity": 1, "unit_price": 600.0}],
            delivery_schedule=f"Hoy a las {t_late.strftime('%I:%M %p')}",
            scheduled_for=t_late.isoformat(),
        )
        o_early = self.repo.create_order(
            tenant_id=self.tenant_id,
            customer_name="Cliente Temprano",
            customer_phone="6699990011",
            delivery_address="Dirección 2",
            items=[{"product_name": "Gas 30kg", "quantity": 1, "unit_price": 600.0}],
            delivery_schedule=f"Hoy a las {t_early.strftime('%I:%M %p')}",
            scheduled_for=t_early.isoformat(),
        )
        o_tomorrow = self.repo.create_order(
            tenant_id=self.tenant_id,
            customer_name="Cliente Manana",
            customer_phone="6699990012",
            delivery_address="Dirección 3",
            items=[{"product_name": "Gas 30kg", "quantity": 1, "unit_price": 600.0}],
            delivery_schedule=f"Mañana a las {t_tomorrow.strftime('%I:%M %p')}",
            scheduled_for=t_tomorrow.isoformat(),
        )

        agenda = self.repo.get_scheduled_agenda(self.tenant_id)
        agenda_ids = [item["id"] for item in agenda]

        # Verify all 3 are in the agenda
        self.assertIn(o_early.id, agenda_ids)
        self.assertIn(o_late.id, agenda_ids)
        self.assertIn(o_tomorrow.id, agenda_ids)

        idx_early = agenda_ids.index(o_early.id)
        idx_late = agenda_ids.index(o_late.id)
        idx_tomorrow = agenda_ids.index(o_tomorrow.id)

        # Early must come before Late, which must come before Tomorrow
        self.assertLess(idx_early, idx_late, "Earlier scheduled order should appear before later scheduled order")
        self.assertLess(idx_late, idx_tomorrow, "Today's scheduled order should appear before tomorrow's scheduled order")

    def test_gasera_operating_hours_deadline_parsing(self):
        """Test that operating hours (8:00 AM - 7:00 PM) are strictly respected."""
        # 1. Daytime order (11:30 AM) for 5:00 PM -> Must be TODAY at 17:00, NEVER tomorrow
        ref_day = datetime(2026, 10, 2, 11, 30, 0)
        dt_5pm = parse_schedule_deadline("Hoy a las 5:00 PM", ref_day)
        self.assertEqual(dt_5pm.date(), ref_day.date(), "5:00 PM ordered at 11:30 AM must be for TODAY")
        self.assertEqual(dt_5pm.hour, 17)
        self.assertEqual(dt_5pm.minute, 0)

        dt_5pm_alt = parse_schedule_deadline("a las 5", ref_day)
        self.assertEqual(dt_5pm_alt.date(), ref_day.date(), "'a las 5' during daytime must be TODAY")
        self.assertEqual(dt_5pm_alt.hour, 17)

        # 2. Order for 6:30 PM (before 7:00 PM closing) -> Must be TODAY
        dt_630pm = parse_schedule_deadline("hoy a las 6:30 PM", ref_day)
        self.assertEqual(dt_630pm.date(), ref_day.date())
        self.assertEqual(dt_630pm.hour, 18)
        self.assertEqual(dt_630pm.minute, 30)

        # 3. Order falling at/after 7:00 PM (19:00 closing) -> Goes to next day at 8:00 AM
        dt_7pm = parse_schedule_deadline("a las 7 de la tarde", ref_day)
        self.assertEqual(dt_7pm.date(), ref_day.date() + timedelta(days=1), "7:00 PM closing rolls over to tomorrow")
        self.assertEqual(dt_7pm.hour, 8, "Opens at 8:00 AM next day")

        # 4. Order placed after hours (e.g. 7:15 PM) with 'Lo antes posible' must NOT be auto-scheduled
        ref_night = datetime(2026, 10, 2, 19, 15, 0)
        from src.repositories.sqlite_repo import normalize_schedule_datetime
        dt_asap_night = normalize_schedule_datetime("Lo antes posible", ref_night)
        self.assertIsNone(dt_asap_night, "ASAP orders must never be auto-scheduled without explicit future date/time")

    def test_scheduled_order_at_5pm_activates_at_430pm_not_at_2pm(self):
        """Test that an order for 5:00 PM activates exactly at 4:30 PM, NOT at 2:00 PM even if driver is assigned."""
        now = datetime.now()
        # Today at 5:00 PM
        target_5pm = datetime.combine(now.date(), datetime.min.time()).replace(hour=17, minute=0, second=0)
        # If running test after 5pm, use tomorrow 5pm
        if now >= target_5pm:
            target_5pm += timedelta(days=1)

        order = self.repo.create_order(
            tenant_id=self.tenant_id,
            customer_name="Cliente Test 5PM",
            customer_phone="6699990020",
            delivery_address="Calle Test 123",
            items=[{"product_name": "Cilindro 30kg", "quantity": 1, "unit_price": 650.0}],
            delivery_schedule="Hoy a las 5:00 PM",
            scheduled_for=target_5pm.isoformat(),
        )

        # Verify initial status is scheduled
        self.assertEqual(order.status, "scheduled")

        # Check in agenda
        agenda = self.repo.get_scheduled_agenda(self.tenant_id)
        item = next((x for x in agenda if x["id"] == order.id), None)
        self.assertIsNotNone(item)
        expected_act = target_5pm - timedelta(minutes=30)
        from src.repositories.sqlite_repo import MAZATLAN_TZ
        act_dt = datetime.fromisoformat(item["activation_at"])
        if act_dt.tzinfo:
            act_dt = act_dt.astimezone(MAZATLAN_TZ).replace(tzinfo=None)
        self.assertEqual(act_dt, expected_act)

        # Pre-assign driver (simulating assigning driver at 2:00 PM)
        drivers = self.repo.get_all_drivers(self.tenant_id)
        if drivers:
            d = drivers[0]
            self.repo.assign_order_to_driver(self.tenant_id, order.id, d.id)

            # Order status MUST REMAIN 'scheduled' before T-30!
            updated = self.repo.get_order_by_id(self.tenant_id, order.id)
            self.assertEqual(updated.status, "scheduled", "Status must remain scheduled even when driver pre-assigned")
            self.assertEqual(str(updated.driver_id), str(d.id), "Driver must be recorded on order")

            # Must NOT appear on active orders table
            active = self.repo.get_all_orders_admin(self.tenant_id, status="active")
            active_ids = [o["id"] for o in active]
            self.assertNotIn(order.id, active_ids, "Scheduled order must not leak into active table before T-30")


if __name__ == "__main__":
    unittest.main()
