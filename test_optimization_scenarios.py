"""Automated verification script for Petroil Gas LLM Optimization Scenarios.

Validates that:
1. Standard button/callback flows run with 0 LLM calls.
2. Standard text order flows run deterministically.
3. Stationary tank flows operate correctly.
4. Voice transcriptions feed seamlessly into the deterministic router.
5. Out-of-flow questions are answered and preserve conversational state.
6. Real-time telemetry accurately monitors token usage and cost savings.
"""

import asyncio
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path

# Set project root in path
sys.path.insert(0, str(Path(__file__).parent))

from src.services.flow_router import flow_router, FlowState
from src.services.telemetry import telemetry
from src.repositories import get_repository

TENANT_ID = "petroil"


class TestOptimizationScenarios(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        telemetry.reset()
        self.repo = get_repository()

    async def test_scenario_1_button_flow_zero_llm(self):
        """Scenario 1: Complete button-driven order flow must use EXACTLY 0 LLM calls."""
        session_id = "test_btn_user_001"
        initial_llm_calls = telemetry.llm_calls

        # Step 1: /start
        r1 = await flow_router.process_event(session_id=session_id, text="/start", tenant_id=TENANT_ID)
        self.assertIn("Gas a Tu Puerta", r1.text)

        # Step 2: Select Cylinder service
        r2 = await flow_router.process_event(session_id=session_id, callback_data="client_svc:cilindro", tenant_id=TENANT_ID)
        self.assertIn("Cilindros", r2.text)

        # Step 3: Add 30kg cylinder to cart and checkout
        r3 = await flow_router.process_event(session_id=session_id, text="Deseo ordenar: 1x Cilindro 30kg", tenant_id=TENANT_ID)
        self.assertTrue("celular" in r3.text.lower() or "teléfono" in r3.text.lower())
        self.assertEqual(r3.state, FlowState.WAITING_FOR_PHONE)

        # Step 4: Enter 10-digit phone
        # Register test customer in repo first so addresses exist
        cust = self.repo.get_customer_by_phone(TENANT_ID, "6691234567")
        if not cust:
            cust = self.repo.create_customer(
                tenant_id=TENANT_ID,
                name="Carlos Ruiz",
                phone="6691234567",
                address="Av del Mar 100, Mazatlán",
                channel="telegram",
                channel_user_id="user_test_001",
            )
        
        r4 = await flow_router.process_event(session_id=session_id, text="6691234567", tenant_id=TENANT_ID)
        self.assertEqual(r4.state, FlowState.WAITING_FOR_ADDRESS_SELECTION)

        # Step 5: Select saved address via callback
        r5 = await flow_router.process_event(session_id=session_id, callback_data="client_addr:1", tenant_id=TENANT_ID)
        self.assertEqual(r5.state, FlowState.WAITING_FOR_SCHEDULE)

        # Step 6: Select schedule
        r6 = await flow_router.process_event(session_id=session_id, text="Lo antes posible", tenant_id=TENANT_ID)
        self.assertEqual(r6.state, FlowState.WAITING_FOR_PAYMENT_METHOD)

        # Step 7: Select payment method via callback
        r7 = await flow_router.process_event(session_id=session_id, callback_data="client_pay:efectivo", tenant_id=TENANT_ID)
        self.assertEqual(r7.state, FlowState.WAITING_FOR_CONFIRMATION)
        self.assertIn("Resumen de tu Pedido", r7.text)

        # Step 8: Confirm order via callback
        r8 = await flow_router.process_event(session_id=session_id, callback_data="client_confirm:yes", tenant_id=TENANT_ID)
        self.assertEqual(r8.state, FlowState.COMPLETED)
        self.assertIn("confirmado", r8.text.lower())

        # Verify 0 LLM calls were made!
        self.assertEqual(telemetry.llm_calls, initial_llm_calls, "Button order flow used LLM calls when it should be 0!")
        print("[OK] Scenario 1 (Zero-LLM Button Order Flow): PASSED (0 LLM calls)")

    async def test_scenario_2_new_user_text_flow(self):
        """Scenario 2: New user text flow asking for products, phone, name, address, schedule, payment, confirm."""
        session_id = f"test_text_new_user_{int(datetime.now().timestamp())}"
        new_phone = f"669{int(datetime.now().timestamp() * 1000) % 10000000:07d}"

        # Request product by text
        r1 = await flow_router.process_event(session_id=session_id, text="Buenas tardes, quiero pedir dos cilindros de 30 kilos", tenant_id=TENANT_ID)
        self.assertEqual(r1.state, FlowState.WAITING_FOR_PHONE)
        self.assertIn("2x", r1.text)
        self.assertIn("30 kg", r1.text)

        # Send new phone
        r2 = await flow_router.process_event(session_id=session_id, text=f"Mi cel es {new_phone}", tenant_id=TENANT_ID)
        self.assertEqual(r2.state, FlowState.WAITING_FOR_NEW_CUSTOMER_NAME)

        # Send name
        r3 = await flow_router.process_event(session_id=session_id, text="María González", tenant_id=TENANT_ID)
        self.assertEqual(r3.state, FlowState.WAITING_FOR_NEW_CUSTOMER_ADDRESS)

        # Send address
        r4 = await flow_router.process_event(session_id=session_id, text="Calle Gaviotas 456, Zona Dorada, Mazatlán", tenant_id=TENANT_ID)
        self.assertEqual(r4.state, FlowState.WAITING_FOR_SCHEDULE)

        # Send schedule
        r5 = await flow_router.process_event(session_id=session_id, text="Hoy a las 5:00 PM", tenant_id=TENANT_ID)
        if r5.action_performed == "show_schedule_alternative":
            r5 = await flow_router.process_event(session_id=session_id, text="Sí, acepto", tenant_id=TENANT_ID)
        self.assertEqual(r5.state, FlowState.WAITING_FOR_PAYMENT_METHOD)

        # Send payment
        r6 = await flow_router.process_event(session_id=session_id, text="Con terminal por favor", tenant_id=TENANT_ID)
        self.assertEqual(r6.state, FlowState.WAITING_FOR_CONFIRMATION)

        # Confirm
        r7 = await flow_router.process_event(session_id=session_id, text="Sí, confirmo", tenant_id=TENANT_ID)
        self.assertEqual(r7.state, FlowState.COMPLETED)
        self.assertTrue(any(k in r7.text.lower() for k in ["confirmado", "programado", "registrado"]))
        print("[OK] Scenario 2 (New User Full Text Flow): PASSED")

    async def test_scenario_3_stationary_tank_flow(self):
        """Scenario 3: Stationary tank refill flow."""
        session_id = "test_stationary_user_003"

        # Request stationary service
        r1 = await flow_router.process_event(session_id=session_id, text="Quiero cargar gas para mi tanque estacionario", tenant_id=TENANT_ID)
        self.assertEqual(r1.state, FlowState.WAITING_FOR_STATIONARY_DETAILS)

        # Specify amount in pesos
        r2 = await flow_router.process_event(session_id=session_id, text="Quiero $800 pesos", tenant_id=TENANT_ID)
        self.assertEqual(r2.state, FlowState.WAITING_FOR_PHONE)

        # Provide phone
        r3 = await flow_router.process_event(session_id=session_id, text="6691234567", tenant_id=TENANT_ID)
        self.assertEqual(r3.state, FlowState.WAITING_FOR_ADDRESS_SELECTION)

        # Select address
        r4 = await flow_router.process_event(session_id=session_id, callback_data="client_addr:1", tenant_id=TENANT_ID)
        self.assertEqual(r4.state, FlowState.WAITING_FOR_SCHEDULE)

        # Schedule
        r5 = await flow_router.process_event(session_id=session_id, text="Lo antes posible", tenant_id=TENANT_ID)
        self.assertEqual(r5.state, FlowState.WAITING_FOR_PAYMENT_METHOD)

        # Payment
        r6 = await flow_router.process_event(session_id=session_id, callback_data="client_pay:efectivo", tenant_id=TENANT_ID)
        self.assertEqual(r6.state, FlowState.WAITING_FOR_CONFIRMATION)
        self.assertIn("Estacionario", r6.text)

        # Confirm
        r7 = await flow_router.process_event(session_id=session_id, callback_data="client_confirm:yes", tenant_id=TENANT_ID)
        self.assertEqual(r7.state, FlowState.COMPLETED)
        print("[OK] Scenario 3 (Stationary Tank Order Flow): PASSED")

    async def test_scenario_4_voice_transcription_flow(self):
        """Scenario 4: Audio transcribed text is cleanly routed without LLM overhead."""
        session_id = "test_voice_user_004"

        # Simulated transcribed text from voice note
        transcribed_voice = "Hola buenas tardes necesito que me manden un cilindro de gas de 30 kilos"
        r1 = await flow_router.process_event(session_id=session_id, text=transcribed_voice, tenant_id=TENANT_ID)
        self.assertEqual(r1.state, FlowState.WAITING_FOR_PHONE)
        self.assertIn("30 kg", r1.text)
        print("[OK] Scenario 4 (Voice Note Audio Transcription Flow): PASSED")

    async def test_scenario_5_out_of_flow_question_preserves_state(self):
        """Scenario 5: Inquiries (price check) answer immediately and PRESERVE current flow step."""
        session_id = "test_question_preserve_state_005"

        # Start an order
        await flow_router.process_event(session_id=session_id, text="Quiero un cilindro de 20 kg", tenant_id=TENANT_ID)
        await flow_router.process_event(session_id=session_id, text="6691234567", tenant_id=TENANT_ID)
        await flow_router.process_event(session_id=session_id, callback_data="client_addr:1", tenant_id=TENANT_ID)
        await flow_router.process_event(session_id=session_id, text="Lo antes posible", tenant_id=TENANT_ID)
        
        # Now the customer is in WAITING_FOR_PAYMENT_METHOD
        state = flow_router.get_state(session_id)
        self.assertEqual(state.state, FlowState.WAITING_FOR_PAYMENT_METHOD)

        # Customer asks out-of-flow question about price of 30kg cylinder
        r_question = await flow_router.process_event(session_id=session_id, text="¿Cuánto cuesta el cilindro de 30 kg?", tenant_id=TENANT_ID)
        
        # Verify price is answered
        self.assertIn("30 kg", r_question.text)
        self.assertIn("$", r_question.text)
        # Verify prompt reminds customer of current step
        self.assertIn("método de pago", r_question.text.lower())
        
        # State MUST STILL BE WAITING_FOR_PAYMENT_METHOD
        state_after = flow_router.get_state(session_id)
        self.assertEqual(state_after.state, FlowState.WAITING_FOR_PAYMENT_METHOD, "Out-of-flow inquiry reset the conversational step!")

        # Customer answers with payment method
        r_next = await flow_router.process_event(session_id=session_id, text="Efectivo", tenant_id=TENANT_ID)
        self.assertEqual(r_next.state, FlowState.WAITING_FOR_CONFIRMATION)
        print("[OK] Scenario 5 (Out-of-flow Question Preserving State): PASSED")

    async def test_scenario_6_telemetry_metrics(self):
        """Scenario 6: Verify telemetry metrics tracking and calculation."""
        # Process an event to have non-zero metrics
        await flow_router.process_event(session_id="test_tel_01", text="/start", tenant_id=TENANT_ID)
        metrics = telemetry.get_metrics()
        self.assertIn("total_messages", metrics)
        self.assertIn("non_llm_messages", metrics)
        self.assertIn("llm_calls", metrics)
        self.assertIn("ratio_saved_percentage", metrics)
        self.assertGreater(metrics["non_llm_messages"], 0)
        print(f"[OK] Scenario 6 (Telemetry Metrics): PASSED -> {metrics['ratio_saved_percentage']}% messages handled without LLM")


if __name__ == "__main__":
    unittest.main()
