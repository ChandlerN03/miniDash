from pathlib import Path

from fastapi import FastAPI

from src.clock import Clock, SystemClock
from src.repository.orders_repo import OrderRepository
from src.repository.restaurants_repo import RestaurantRepository
from src.routes import orders, restaurants
from src.routes.errors import register_error_handlers
from src.services.order_service import OrderService
from src.services.restaurant_service import RestaurantService
from src.store.file_store import FileStore
from src.store.seed import SEED_DATA

DEFAULT_DATA_PATH = Path(__file__).resolve().parent.parent / "data.txt"


def create_app(data_path: Path | str = DEFAULT_DATA_PATH, clock: Clock | None = None) -> FastAPI:
    """Build the app. Tests pass a temporary data file and a fake clock."""
    store = FileStore(data_path)
    store.initialize(SEED_DATA)

    restaurant_repo = RestaurantRepository(store)
    order_repo = OrderRepository(store)

    app = FastAPI(title="MiniDash")
    app.state.restaurant_service = RestaurantService(restaurant_repo)
    app.state.order_service = OrderService(order_repo, restaurant_repo, clock or SystemClock())

    register_error_handlers(app)
    app.include_router(restaurants.router)
    app.include_router(orders.router)
    return app
