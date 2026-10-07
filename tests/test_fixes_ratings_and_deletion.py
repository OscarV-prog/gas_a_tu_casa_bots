"""Unit tests verifying:
1. Scheduled order activation is strictly 30 minutes before customer requested delivery time.
2. Address deletion flow never selects the address as delivery address.
3. Driver ratings are saved, averaged correctly, and reflected in driver operational stats.
"""

import os
import time
import unittest
from datetime import datetime, timedelta

from src.models.customer import CustomerAddress
from src.repositories import get_repository
from src.repositories.sqlite_repo import SqliteRepository, MAZATLAN_TZ
from src.services.flow_router import FlowState, flow_router, clear_session


class TestFixesRatingsAndDeletion(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.orig_data_source = os.environ.get("DATA_SOURCE")
        os.environ["DATA_SOURCE"] = "sqlite"
        self.repo = SqliteRepository()
        self.tenant_id = "petroil"
        self.phone = f"669{int(time.time()*10000)%10000000:07d}"
        self.channel_user_id = f"test_user_{self.phone}"

    def tearDown(self):
        if self.orig_data_source is not None:
            os.environ["DATA_SOURCE"] = self.orig_data_source
        else:
            os.environ.pop("DATA_SOURCE", None)

    async def test_scheduled_agenda_activation_30_min_prior(self):
        """Verify activation_at is strictly 30 minutes before customer's delivery time (e.g., 12:00 PM -> 11:30 AM)."""
        now = datetime.now()
        # Schedule for tomorrow at 12:00 PM to guarantee it is in future agenda
        target_12pm = datetime.combine(now.date() + timedelta(days=1), datetime.min.time()).replace(hour=12, minute=0, second=0)
        schedule_str = "Mañana a las 12:00 PM"

        order = self.repo.create_order(
            tenant_id=self.tenant_id,
            customer_name="Cliente Test 12PM",
            customer_phone=self.phone,
            delivery_address="Estadio Teodoro Mariscal, Mazatlán",
            items=[{"product_name": "Cilindro 30kg", "quantity": 1, "unit_price": 650.0}],
            delivery_schedule=schedule_str,
            scheduled_for=target_12pm.isoformat(),
        )

        agenda = self.repo.get_scheduled_agenda(self.tenant_id)
        item = next((x for x in agenda if x["id"] == order.id), None)
        self.assertIsNotNone(item, f"Order {order.id} should be present in scheduled agenda")

        # Parse activation_at to Mazatlán local time
        act_dt = datetime.fromisoformat(item["activation_at"])
        if act_dt.tzinfo:
            act_dt = act_dt.astimezone(MAZATLAN_TZ).replace(tzinfo=None)

        expected_activation = target_12pm - timedelta(minutes=30)
        self.assertEqual(act_dt, expected_activation)
        self.assertEqual(act_dt.hour, 11)
        self.assertEqual(act_dt.minute, 30)
        self.assertIn("11:30", item["activation_display"])

    async def test_address_deletion_flow_does_not_select_as_delivery(self):
        """When user is in deletion mode, selecting '1' must prompt confirmation to delete, NOT set delivery address."""
        # 1. Create customer with 2 addresses
        cust = self.repo.save_or_update_customer(
            tenant_id=self.tenant_id,
            channel="whatsapp",
            channel_user_id=self.phone,
            name="Cliente Borrar Domicilio",
            phone=self.phone,
            address="Calle Principal 100, Mazatlán",
        )
        self.repo.add_customer_address(cust.id, "Avenida Secundaria 200, Mazatlán")
        cust = self.repo.get_customer_by_phone(self.tenant_id, self.phone)
        self.assertEqual(len(cust.addresses), 2)

        session_id = f"test_session_{self.phone}"
        clear_session(session_id)
        sess = flow_router.get_session(session_id)
        sess.channel = "whatsapp"
        sess.channel_user_id = self.phone
        sess.tenant_id = self.tenant_id
        sess.state = FlowState.WAITING_FOR_ADDRESS_SELECTION
        sess.draft_order.customer_phone = self.phone

        # 2. User requests address deletion menu
        res_del_menu = await flow_router.process_event(
            session_id=session_id,
            callback_data="client_addr:del_menu",
            channel="whatsapp",
            channel_user_id=self.phone,
            tenant_id=self.tenant_id,
        )
        self.assertEqual(res_del_menu.action_performed, "show_delete_address_buttons")
        self.assertTrue(getattr(sess, "_is_deleting_address", False))
        self.assertFalse(sess.draft_order.delivery_address)

        # 3. User selects "1" (which address to delete)
        res_select = await flow_router.process_event(
            session_id=session_id,
            text="1",
            channel="whatsapp",
            channel_user_id=self.phone,
            tenant_id=self.tenant_id,
        )
        # CRUCIAL CHECK: Must NOT set delivery address and must NOT transition to WAITING_FOR_SCHEDULE
        self.assertFalse(sess.draft_order.delivery_address)
        self.assertEqual(sess.state, FlowState.WAITING_FOR_ADDRESS_SELECTION)
        self.assertEqual(res_select.action_performed, "show_delete_confirm_buttons")
        self.assertIn("¿Estás seguro de que deseas eliminar esta dirección?", res_select.text)

        # 4. User confirms deletion
        res_confirm = await flow_router.process_event(
            session_id=session_id,
            text="Sí, eliminar",
            channel="whatsapp",
            channel_user_id=self.phone,
            tenant_id=self.tenant_id,
        )
        self.assertIn("eliminada con éxito", res_confirm.text)
        self.assertFalse(getattr(sess, "_is_deleting_address", False))

        # Check DB: only 1 address remaining
        updated_cust = self.repo.get_customer_by_phone(self.tenant_id, self.phone)
        self.assertEqual(len(updated_cust.addresses), 1)

        # 5. Now normal flow: user selects remaining address "1" for delivery
        res_order = await flow_router.process_event(
            session_id=session_id,
            text="1",
            channel="whatsapp",
            channel_user_id=self.phone,
            tenant_id=self.tenant_id,
        )
        self.assertEqual(sess.state, FlowState.WAITING_FOR_SCHEDULE)
        self.assertTrue(sess.draft_order.delivery_address)
        self.assertIn("Avenida Secundaria 200", sess.draft_order.delivery_address)

    def test_driver_ratings_saved_and_averaged_in_dashboard(self):
        """Driver ratings given across orders must be stored, averaged and reflected in operational status."""
        drivers = self.repo.get_all_drivers(self.tenant_id)
        if not drivers:
            self.skipTest("No drivers found")
        driver = drivers[0]

        # Create two test orders assigned to driver
        order1 = self.repo.create_order(
            tenant_id=self.tenant_id,
            customer_name="Cliente Rating 1",
            customer_phone=self.phone,
            delivery_address="Dirección 1",
            items=[{"product_name": "Cilindro 30kg", "quantity": 1, "unit_price": 650.0}],
        )
        self.repo.update_order_status(self.tenant_id, order1.id, "delivered")
        self.repo.assign_order_to_driver(self.tenant_id, order1.id, driver.id)

        order2 = self.repo.create_order(
            tenant_id=self.tenant_id,
            customer_name="Cliente Rating 2",
            customer_phone=self.phone,
            delivery_address="Dirección 2",
            items=[{"product_name": "Cilindro 30kg", "quantity": 1, "unit_price": 650.0}],
        )
        self.repo.update_order_status(self.tenant_id, order2.id, "delivered")
        self.repo.assign_order_to_driver(self.tenant_id, order2.id, driver.id)

        # Save ratings: 5 stars for order1, 4 stars for order2
        self.repo.save_order_rating(
            tenant_id=self.tenant_id,
            order_id=order1.id,
            rating=5,
            driver_id=driver.id,
        )
        self.repo.save_order_rating(
            tenant_id=self.tenant_id,
            order_id=order2.id,
            rating=4,
            driver_id=driver.id,
        )

        # Check driver rating stats
        stats = self.repo.get_driver_rating_stats(self.tenant_id, driver.id)
        self.assertGreaterEqual(stats["total_reviews"], 2)
        self.assertAlmostEqual(stats["average_rating"], 4.5, delta=0.5)

        # Check operational status reflects the real driver rating
        op_status = self.repo.get_all_drivers_operational_status()
        d_status = next((d for d in op_status if d["id"] == driver.id), None)
        self.assertIsNotNone(d_status)
        self.assertGreaterEqual(d_status["rating_count"], 2)
        self.assertGreater(d_status["rating"], 0.0)


if __name__ == "__main__":
    unittest.main()
