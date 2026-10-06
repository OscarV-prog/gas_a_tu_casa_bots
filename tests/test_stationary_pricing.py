import sys
import unittest
from datetime import datetime, timezone, timedelta

sys.stdout.reconfigure(encoding='utf-8')

from src.models.order import OrderItem
from src.services.flow_router import (
    parse_stationary_request_deterministic,
    build_order_summary_text,
    DraftOrder,
)
from src.repositories.sqlite_repo import (
    get_local_now,
    normalize_schedule_datetime,
    parse_schedule_deadline,
    format_schedule_display,
    SqliteRepository,
)
from src.repositories.api_repo import ApiRepository

class TestStationaryPricingAndScheduling(unittest.TestCase):
    def test_parse_stationary_pesos(self):
        # 500 pesos
        res = parse_stationary_request_deterministic("Quiero $500 para un tanque estacionario", "petroil")
        self.assertIsNotNone(res)
        self.assertEqual(len(res), 1)
        item = res[0]
        self.assertAlmostEqual(item["quantity"], 37.88, places=2)
        self.assertEqual(item["unit_price"], 13.20)
        self.assertIn("Estacionario", item["product_name"])
        total = round(item["quantity"] * item["unit_price"], 2)
        self.assertAlmostEqual(total, 500.02, places=2)

    def test_parse_stationary_plain_number(self):
        # Just "500"
        res = parse_stationary_request_deterministic("500", "petroil")
        self.assertIsNotNone(res)
        item = res[0]
        self.assertAlmostEqual(item["quantity"], 37.88, places=2)
        self.assertEqual(item["unit_price"], 13.20)

    def test_parse_stationary_words(self):
        # "quinientos pesos"
        res = parse_stationary_request_deterministic("quinientos pesos", "petroil")
        self.assertIsNotNone(res)
        item = res[0]
        self.assertAlmostEqual(item["quantity"], 37.88, places=2)
        self.assertEqual(item["unit_price"], 13.20)

    def test_parse_stationary_liters(self):
        # 100 litros
        res = parse_stationary_request_deterministic("Quiero 100 litros", "petroil")
        self.assertIsNotNone(res)
        item = res[0]
        self.assertEqual(item["quantity"], 100.0)
        self.assertEqual(item["unit_price"], 13.20)
        total = round(item["quantity"] * item["unit_price"], 2)
        self.assertEqual(total, 1320.0)

    def test_order_item_model(self):
        it = OrderItem(
            product_id="test",
            product_name="Gas LP Estacionario (Litro)",
            quantity=37.88,
            unit_price=13.20,
            subtotal=500.02,
        )
        self.assertEqual(it.quantity, 37.88)
        self.assertIn("37.88", it.to_display())

    def test_summary_text_shows_liters_and_price(self):
        draft = DraftOrder(
            customer_name="Oscar",
            customer_phone="6699123501",
            delivery_address="Caoba 361, Col. Los Mangos 1",
            payment_method="Efectivo",
            delivery_schedule="Lo antes posible",
            items=[{
                "product_id": "7666a354-5892-42d5-9a56-3c36a85851ca",
                "product_name": "Gas LP Estacionario (Litro)",
                "quantity": 37.88,
                "unit_price": 13.20,
            }]
        )
        summary = build_order_summary_text(draft)
        self.assertIn("37.88 L Gas LP Estacionario", summary)
        self.assertIn("$500.02 MXN", summary)
        self.assertIn("Lo antes posible", summary)

    def test_asap_order_never_scheduled_in_sqlite(self):
        repo = SqliteRepository()
        order = repo.create_order(
            tenant_id="petroil",
            customer_name="Test ASAP",
            customer_phone="6691112233",
            delivery_address="Calle Falsa 123",
            items=[{"product_id": "gas-estacionario-litro", "product_name": "Gas LP Estacionario (Litro)", "quantity": 37.88, "unit_price": 13.20}],
            delivery_schedule="Lo antes posible",
            payment_method="Efectivo",
        )
        self.assertEqual(order.status, "confirmed")
        self.assertEqual(order.delivery_schedule, "Lo antes posible")
        self.assertIsNone(order.scheduled_for)

    def test_asap_order_never_scheduled_in_api_repo_parse(self):
        api_repo = ApiRepository()
        mock_raw = {
            "id": "11111111-2222-3333-4444-555555555555",
            "orderNumber": "ORD-PETR-9999",
            "tenantId": "petroil",
            "status": "PROGRAMADO",
            "totalAmount": 500.02,
            "scheduledFor": "2026-10-07T08:00:00.000Z",
            "deliverySchedule": "Lo antes posible",
            "customer": {"name": "Oscar", "phone": "6699123501", "address": "Caoba 361"},
            "items": [{"productId": "7666a354-5892-42d5-9a56-3c36a85851ca", "quantity": 37.88, "unitPrice": 13.2, "subtotal": 500.02}],
        }
        parsed = api_repo._parse_api_order(mock_raw, "petroil")
        self.assertEqual(parsed.delivery_schedule, "Lo antes posible")
        self.assertIsNone(parsed.scheduled_for)
        self.assertNotEqual(parsed.status, "scheduled")

    def test_local_mazatlan_time_is_not_utc(self):
        local_now = get_local_now()
        # Mazatlan is UTC-7, so local hour is different from UTC hour unless UTC is between 0-6
        utc_now = datetime.now(timezone.utc)
        self.assertIsNone(local_now.tzinfo)
        diff_hours = (utc_now.hour - local_now.hour) % 24
        self.assertEqual(diff_hours, 7)

if __name__ == "__main__":
    unittest.main()
