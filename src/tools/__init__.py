"""All tools available to the sales agent."""

from src.tools.search_products import search_products
from src.tools.search_by_image import search_by_image
from src.tools.get_promotions import get_promotions
from src.tools.send_product_image import send_product_image
from src.tools.create_order import create_order
from src.tools.get_order_status import get_order_status
from src.tools.customer_info import get_customer_info
from src.tools.cancel_order import cancel_order
from src.tools.delete_customer_address import delete_customer_address
from src.tools.check_schedule_availability import check_schedule_availability

ALL_TOOLS = [
    search_products,
    search_by_image,
    get_promotions,
    send_product_image,
    create_order,
    get_order_status,
    get_customer_info,
    cancel_order,
    delete_customer_address,
    check_schedule_availability,
]

__all__ = [
    "search_products",
    "search_by_image",
    "get_promotions",
    "send_product_image",
    "create_order",
    "get_order_status",
    "get_customer_info",
    "cancel_order",
    "delete_customer_address",
    "check_schedule_availability",
    "ALL_TOOLS",
]
