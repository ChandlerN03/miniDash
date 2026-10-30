from src.repository.restaurants_repo import RestaurantRepository
from src.services.errors import MiniDashError


class RestaurantService:
    def __init__(self, restaurants: RestaurantRepository):
        self._restaurants = restaurants

    def list_restaurants(self) -> list[dict]:
        return self._restaurants.list_restaurants()

    def get_menu(self, restaurant_id: int) -> list[dict]:
        if self._restaurants.get_restaurant(restaurant_id) is None:
            raise MiniDashError("RESTAURANT_NOT_FOUND", f"Restaurant {restaurant_id} does not exist.")
        return self._restaurants.list_menu(restaurant_id)
