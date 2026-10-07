import unittest
from unittest.mock import patch, MagicMock
from src.repositories.api_repo import ApiRepository
from src.models.product import Product
from src.services.flow_router import build_order_summary_text, DraftOrder

class TestPromotionPricing(unittest.TestCase):
    @patch("src.repositories.api_repo.api_get")
    def test_promotion_discount_applied_to_product_price(self, mock_api_get):
        mock_api_get.return_value = [
            {
                "id": "prod-promo-1",
                "name": "Cilindro de Gas 10 kg prueba2",
                "pricePerUnit": 235.0,
                "isPromotion": True,
                "promoDiscount": 10.0,
                "category": "CILINDRO",
            },
            {
                "id": "prod-regular-1",
                "name": "Cilindro de Gas 20 kg",
                "pricePerUnit": 470.0,
                "isPromotion": False,
                "promoDiscount": 0.0,
                "category": "CILINDRO",
            }
        ]

        repo = ApiRepository()
        products = repo.get_all_products("petroil")
        promo_prod = next(p for p in products if p.id == "prod-promo-1")
        reg_prod = next(p for p in products if p.id == "prod-regular-1")

        # El producto en promoción debe tener el precio efectivo con descuento ($225.00)
        self.assertEqual(promo_prod.price, 225.0)
        self.assertEqual(promo_prod.original_price, 235.0)
        self.assertEqual(promo_prod.promo_discount, 10.0)

        # El producto regular debe conservar su precio original ($470.00)
        self.assertEqual(reg_prod.price, 470.0)
        self.assertIsNone(reg_prod.original_price)

    def test_summary_and_draft_total_consistency(self):
        draft = DraftOrder(
            customer_name="Oscar",
            customer_phone="6699123501",
            delivery_address="Misión San Javier 5246",
            payment_method="Tarjeta",
            items=[
                {
                    "product_id": "prod-promo-1",
                    "product_name": "Cilindro de Gas 10 kg prueba2",
                    "quantity": 1,
                    "unit_price": 225.0,
                }
            ]
        )
        summary = build_order_summary_text(draft)
        self.assertIn("$225.00 MXN", summary)
        self.assertNotIn("$235.00", summary)

if __name__ == "__main__":
    unittest.main()
