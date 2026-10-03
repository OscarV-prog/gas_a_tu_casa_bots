import time
import unittest
from src.repositories import get_repository
from src.tools.delete_customer_address import delete_customer_address


class TestAddressDeleteConfirmation(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.repo = get_repository()
        self.tenant_id = "petroil"
        self.phone = f"669{int(time.time()*10000)%10000000:07d}"
        self.uid = f"user_{self.phone}"

        # Create customer with 2 addresses
        self.customer = self.repo.save_or_update_customer(
            tenant_id=self.tenant_id,
            channel="telegram",
            channel_user_id=self.uid,
            name="Cliente Prueba Confirmación",
            phone=self.phone,
            address="Avenida Del Mar 500, Mazatlán",
        )
        self.repo.add_customer_address(
            customer_id=self.customer.id,
            address="Calle Benito Juárez 123, Mazatlán",
        )
        # Reload customer
        self.customer = self.repo.get_customer_by_phone(self.tenant_id, self.phone)
        self.assertEqual(len(self.customer.addresses), 2)

    def test_tool_requires_confirmation_before_deleting(self):
        # 1. Calling tool without confirm=True must NOT delete the address
        res = delete_customer_address.invoke({
            "address_identifier": "1",
            "phone": self.phone,
            "confirm": False,
        })
        self.assertIn("¿Estás seguro de que deseas eliminar", res)

        # Address must still exist in database
        refreshed = self.repo.get_customer_by_phone(self.tenant_id, self.phone)
        self.assertEqual(len(refreshed.addresses), 2)

        # 2. Calling tool WITH confirm=True deletes the address
        res_confirmed = delete_customer_address.invoke({
            "address_identifier": "1",
            "phone": self.phone,
            "confirm": True,
        })
        self.assertIn("ha sido eliminada exitosamente", res_confirmed)

    async def test_telegram_callback_asks_confirmation_before_deleting(self):
        from unittest.mock import AsyncMock, MagicMock
        from telegram_bot import manejar_callback_cliente

        addr_to_del = self.customer.addresses[0]

        # Step 1: User taps address to delete -> client_addr_del:{id}:1
        tg_uid = int(self.phone)
        query = MagicMock()
        query.data = f"client_addr_del:{addr_to_del.id}:1"
        query.from_user.id = tg_uid
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()

        update = MagicMock()
        update.callback_query = query
        update.effective_user.id = tg_uid
        update.effective_chat.id = tg_uid

        context = MagicMock()
        context.user_data = {"phone": self.phone}

        await manejar_callback_cliente(update, context)

        # Verify confirmation prompt was shown
        query.edit_message_text.assert_called_once()
        call_kwargs = query.edit_message_text.call_args.kwargs
        self.assertIn("¿Estás seguro de que deseas eliminar esta dirección?", call_kwargs["text"])
        
        # Verify buttons presented: Sí, eliminar vs No, cancelar
        buttons = call_kwargs["reply_markup"].inline_keyboard
        self.assertEqual(len(buttons), 2)
        self.assertIn("client_addr_del_confirm", buttons[0][0].callback_data)
        self.assertEqual(buttons[1][0].callback_data, "client_addr_del_menu")

        # Address is NOT yet deleted in database
        refreshed = self.repo.get_customer_by_phone(self.tenant_id, self.phone)
        self.assertEqual(len(refreshed.addresses), 2)

        # Step 2: User confirms deletion -> client_addr_del_confirm:{id}:1
        query.reset_mock()
        query.data = f"client_addr_del_confirm:{addr_to_del.id}:1"
        await manejar_callback_cliente(update, context)

        # Address is now deleted
        refreshed2 = self.repo.get_customer_by_phone(self.tenant_id, self.phone)
        self.assertEqual(len(refreshed2.addresses), 1)


if __name__ == "__main__":
    unittest.main()
