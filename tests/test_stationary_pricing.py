import sys
import unittest

sys.stdout.reconfigure(encoding='utf-8')

from src.models.order import OrderItem
from src.services.flow_router import (
    parse_stationary_request_deterministic,
    build_order_summary_text,
    DraftOrder,
)
from src.tools.create_order import create_order
from src.repositories import get_repository

class TestStationaryPricing(unittest.TestCase):
    def test_parse_stationary_pesos(self):
        # 500 pesos
        res = parse_stationary_request_deterministic("Quiero $500 para un tanque estacionario", "petroil")
        self.assertIsNotNone(res)
        self.assertEqual(len(res), 1)
        item = res[0]
        self.assertAlmostEqual(item["quantity"], 37.88, places=2)
        self.assertEqual(item["unit_price"], 13.20)
        self.assertIn("37.88 L", item["product_name"])
        self.assertIn("500.00 MXN", item["product_name"])
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
            product_name="Gas LP Estacionario",
            quantity=37.88,
            unit_price=13.20,
            subtotal=500.02,
        )
        self.assertEqual(it.quantity, 37.88)
        self.assertIn("37.88x", it.to_display())

    def test_summary_text(self):
        draft = DraftOrder(
            customer_name="Test Customer",
            customer_phone="6691234567",
            delivery_address="Calle Test 123",
            payment_method="Efectivo",
            delivery_schedule="Lo antes posible",
            items=[{
                "product_id": "gas-estacionario-litro",
                "product_name": "Gas LP Estacionario (Litro)",
                "quantity": 37.88,
                "unit_price": 13.20,
            }]
        )
        summary = build_order_summary_text(draft)
        self.assertIn("37.88x", summary)
        self.assertIn("$500.02 MXN", summary)

if __name__ == "__main__":
    unittest.main()
