from src.store.file_store import FileStore


class RestaurantRepository:
    def __init__(self, store: FileStore):
        self._store = store

    def list_restaurants(self) -> list[dict]:
        return self._store.read()["restaurants"]

    def get_restaurant(self, restaurant_id: int) -> dict | None:
        for restaurant in self._store.read()["restaurants"]:
            if restaurant["id"] == restaurant_id:
                return restaurant
        return None

    def list_menu(self, restaurant_id: int) -> list[dict]:
        return [
            item
            for item in self._store.read()["menu_items"]
            if item["restaurant_id"] == restaurant_id
        ]
