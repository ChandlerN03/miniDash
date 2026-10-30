from src.clock import Clock
from src.repository.orders_repo import OrderRepository
from src.repository.restaurants_repo import RestaurantRepository
from src.services.errors import MiniDashError

PLACED = "PLACED"
PREPARING = "PREPARING"
OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
DELIVERED = "DELIVERED"
CANCELLED = "CANCELLED"

# Which statuses an order may move to from each status.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    PLACED: {PREPARING, CANCELLED},
    PREPARING: {OUT_FOR_DELIVERY, CANCELLED},
    OUT_FOR_DELIVERY: {DELIVERED},
    DELIVERED: set(),
    CANCELLED: set(),
}


class OrderService:
    def __init__(
        self,
        orders: OrderRepository,
        restaurants: RestaurantRepository,
        clock: Clock,
    ):
        self._orders = orders
        self._restaurants = restaurants
        self._clock = clock

    def create_order(self, restaurant_id: int, address: str, items: list[dict]) -> dict:
        """Create an order. `items` is a list of {"menu_item_id", "quantity"}."""
        if self._restaurants.get_restaurant(restaurant_id) is None:
            raise MiniDashError("RESTAURANT_NOT_FOUND", f"Restaurant {restaurant_id} does not exist.")

        address = address.strip()
        if not address:
            raise MiniDashError("INVALID_ADDRESS", "A delivery address is required.")

        if not items:
            raise MiniDashError("EMPTY_ORDER", "An order needs at least one item.")

        quantities: dict[int, int] = {}
        for item in items:
            if item["quantity"] < 1:
                raise MiniDashError("INVALID_QUANTITY", "Quantity must be a whole number of at least 1.")
            menu_item_id = item["menu_item_id"]
            quantities[menu_item_id] = quantities.get(menu_item_id, 0) + item["quantity"]

        prices = {m["id"]: m["price_cents"] for m in self._restaurants.list_menu(restaurant_id)}
        order_items = []
        total_cents = 0
        for menu_item_id, quantity in quantities.items():
            if menu_item_id not in prices:
                raise MiniDashError(
                    "ITEM_NOT_ON_MENU",
                    f"Menu item {menu_item_id} is not on the menu of restaurant {restaurant_id}.",
                )
            unit_price = prices[menu_item_id]
            total_cents += unit_price * quantity
            order_items.append(
                {"menu_item_id": menu_item_id, "quantity": quantity, "unit_price_cents": unit_price}
            )

        return self._orders.add(
            restaurant_id=restaurant_id,
            status=PLACED,
            total_cents=total_cents,
            address=address,
            created_at=self._clock.now().isoformat(),
            items=order_items,
        )

    def get_order(self, order_id: int) -> dict:
        order = self._orders.get(order_id)
        if order is None:
            raise _order_not_found(order_id)
        return order

    def update_status(self, order_id: int, new_status: str) -> dict:
        if new_status not in ALLOWED_TRANSITIONS:
            raise MiniDashError(
                "INVALID_STATUS",
                f"Status must be one of: {', '.join(ALLOWED_TRANSITIONS)}.",
            )

        def decide(current_status: str) -> str:
            if new_status not in ALLOWED_TRANSITIONS[current_status]:
                raise MiniDashError(
                    "INVALID_STATUS_TRANSITION",
                    f"An order that is {current_status} cannot become {new_status}.",
                )
            return new_status

        order = self._orders.change_status(order_id, decide)
        if order is None:
            raise _order_not_found(order_id)
        return order


def _order_not_found(order_id: int) -> MiniDashError:
    return MiniDashError("ORDER_NOT_FOUND", f"Order {order_id} does not exist.")
