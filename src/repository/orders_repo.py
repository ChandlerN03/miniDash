from typing import Callable

from src.store.file_store import FileStore


class OrderRepository:
    def __init__(self, store: FileStore):
        self._store = store

    def add(
        self,
        restaurant_id: int,
        status: str,
        total_cents: int,
        address: str,
        created_at: str,
        items: list[dict],
    ) -> dict:
        """Store an order and its items. Each item has menu_item_id, quantity, unit_price_cents."""
        with self._store.transaction() as data:
            order_id = max((o["id"] for o in data["orders"]), default=0) + 1
            next_item_id = max((i["id"] for i in data["order_items"]), default=0) + 1
            order = {
                "id": order_id,
                "restaurant_id": restaurant_id,
                "status": status,
                "total_cents": total_cents,
                "address": address,
                "created_at": created_at,
            }
            data["orders"].append(order)
            stored_items = []
            for offset, item in enumerate(items):
                stored = {"id": next_item_id + offset, "order_id": order_id, **item}
                data["order_items"].append(stored)
                stored_items.append(stored)
            return {**order, "items": stored_items}

    def get(self, order_id: int) -> dict | None:
        data = self._store.read()
        for order in data["orders"]:
            if order["id"] == order_id:
                items = [i for i in data["order_items"] if i["order_id"] == order_id]
                return {**order, "items": items}
        return None

    def change_status(
        self, order_id: int, decide: Callable[[str], str]
    ) -> dict | None:
        """Update an order's status inside one transaction.

        `decide` receives the current status and returns the new one. If it
        raises, nothing is saved. Returns None when the order does not exist.
        """
        with self._store.transaction() as data:
            for order in data["orders"]:
                if order["id"] == order_id:
                    order["status"] = decide(order["status"])
                    items = [i for i in data["order_items"] if i["order_id"] == order_id]
                    return {**order, "items": items}
        return None
