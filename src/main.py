from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from src.clock import Clock, SystemClock
from src.repository.group_orders_repo import GroupOrderRepository
from src.repository.orders_repo import OrderRepository
from src.repository.restaurants_repo import RestaurantRepository
from src.routes import group_orders, orders, restaurants
from src.routes.errors import register_error_handlers
from src.services.group_order_service import GroupOrderService
from src.services.order_service import OrderService
from src.services.restaurant_service import RestaurantService
from src.store.file_store import FileStore
from src.store.seed import SEED_DATA

DEFAULT_DATA_PATH = Path(__file__).resolve().parent.parent / "data.txt"
INDEX_PATH = Path(__file__).resolve().parent / "static" / "index.html"


def create_app(data_path: Path | str = DEFAULT_DATA_PATH, clock: Clock | None = None) -> FastAPI:
    """Build the app. Tests pass a temporary data file and a fake clock."""
    clock = clock or SystemClock()
    store = FileStore(data_path)
    store.initialize(SEED_DATA)

    restaurant_repo = RestaurantRepository(store)
    order_repo = OrderRepository(store)
    group_order_repo = GroupOrderRepository(store)

    order_service = OrderService(order_repo, restaurant_repo, clock)

    app = FastAPI(title="MiniDash")
    app.state.restaurant_service = RestaurantService(restaurant_repo)
    app.state.order_service = order_service
    # Group orders share the one store and the one order service, so checkout is atomic.
    app.state.group_order_service = GroupOrderService(group_order_repo, restaurant_repo, clock, orders=order_service)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> HTMLResponse:
        """The group order page: one HTML file with its CSS and JavaScript inline."""
        return HTMLResponse(INDEX_PATH.read_text(encoding="utf-8"))

    register_error_handlers(app)
    app.include_router(restaurants.router)
    app.include_router(orders.router)
    app.include_router(group_orders.router)
    return app
