import os
import sys
import unittest
from unittest.mock import patch

if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from src.config.tenant_config import get_tenant
from src.database import init_db
from src.repositories import get_repository
from src.services.address_validator import validate_address_with_llm
from src.services.flow_router import FlowState, flow_router


class TestGascytsaBot(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        os.environ["DATA_SOURCE"] = "sqlite"
        init_db()
        self.repo = get_repository()
        self.tenant_id = "gascytsa"

    def test_tenant_config_gascytsa(self):
        """Verifica que la configuración del tenant Gascytsa sea correcta y tenga la identidad indicada."""
        tenant = get_tenant(self.tenant_id)
        self.assertEqual(tenant.tenant_id, "gascytsa")
        self.assertEqual(tenant.business_name, "Gas a tu Puerta Gascytsa")
        self.assertIn("Culiacán", tenant.agent.personality)
        self.assertIn("Gas a tu Puerta Gascytsa", tenant.agent.personality)

    def test_products_isolation_gascytsa(self):
        """Verifica que los productos de Gascytsa existan en la BD y no se mezclen con otros tenants."""
        from src.database.connection import get_db_connection

        gascytsa_prods = self.repo.get_all_products("gascytsa")
        self.assertGreater(len(gascytsa_prods), 0)

        petroil_prods = self.repo.get_all_products("petroil")
        self.assertGreater(len(petroil_prods), 0)

        with get_db_connection() as conn:
            g_rows = conn.execute("SELECT tenant_id FROM products WHERE tenant_id = 'gascytsa'").fetchall()
            self.assertGreater(len(g_rows), 0)
            for r in g_rows:
                self.assertEqual(r["tenant_id"], "gascytsa")

    async def test_address_validation_culiacan_accepted(self):
        """Verifica que direcciones dentro de Culiacán sean aceptadas para Gascytsa."""
        addr = "Blvd. Pedro Infante 2200, Desarrollo Urbano Tres Ríos, Culiacán"
        res = await validate_address_with_llm(addr, tenant_id=self.tenant_id)
        self.assertTrue(res.is_valid, f"Se esperaba dirección válida pero fue rechazada: {res.user_feedback}")

    async def test_address_validation_out_of_city_rejected(self):
        """Verifica que direcciones de otras ciudades (Mazatlán, Mochis, Navolato) sean estrictamente rechazadas."""
        ciudades_fuera = [
            "Av. del Mar 500, Mazatlán, Sinaloa",
            "Blvd. Antonio Rosales 120, Los Mochis, Sinaloa",
            "Calle Benito Juárez 45, Navolato, Sinaloa",
            "Av. Vallarta 1400, Guadalajara, Jalisco",
        ]
        for dir_fuera in ciudades_fuera:
            res = await validate_address_with_llm(dir_fuera, tenant_id=self.tenant_id)
            self.assertFalse(res.is_valid, f"Dirección fuera de Culiacán no debió ser aceptada: {dir_fuera}")
            self.assertIn("Culiacán", res.user_feedback)

    async def test_flow_router_location_geofence_culiacan(self):
        """Verifica que el router bloquee ubicaciones GPS que no pertenezcan a Culiacán."""
        session_id = "test_gascytsa_geofence_gps"
        # Coordenadas en Mazatlán (a ~200 km de Culiacán)
        gps_mazatlan = {"latitude": 23.2014, "longitude": -106.4215}

        res = await flow_router.process_event(
            session_id=session_id,
            location=gps_mazatlan,
            channel="telegram",
            channel_user_id="test_user_culiacan",
            tenant_id=self.tenant_id,
        )

        self.assertIn("cobertura", res.text.lower())
        self.assertIn("culiacán", res.text.lower())

    def test_database_order_isolation_gascytsa(self):
        """Verifica que una orden creada para Gascytsa quede estrictamente aislada en el tenant gascytsa."""
        order = self.repo.create_order(
            tenant_id=self.tenant_id,
            customer_name="Juan Perez Culiacan",
            customer_phone="6671234567",
            delivery_address="Blvd. Pedro Infante 2200, Tres Ríos, Culiacán",
            items=[{"product_name": "Cilindro de Gas 30 kg", "quantity": 1, "unit_price": 720.0}],
            channel="telegram",
        )
        self.assertIsNotNone(order)
        self.assertEqual(order.tenant_id, "gascytsa")

        # Debe encontrarse con tenant_id="gascytsa"
        found = self.repo.get_order_by_id("gascytsa", order.id)
        self.assertIsNotNone(found)
        self.assertEqual(found.customer_name, "Juan Perez Culiacan")

        # NO debe encontrarse con tenant_id="petroil"
        not_found = self.repo.get_order_by_id("petroil", order.id)
        self.assertIsNone(not_found)
