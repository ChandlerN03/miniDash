from fastapi import APIRouter, Request

from src.routes.schemas import OrderIn, StatusIn
from src.services.order_service import OrderService

router = APIRouter()


def _service(request: Request) -> OrderService:
    return request.app.state.order_service


@router.post("/orders", status_code=201)
def create_order(body: OrderIn, request: Request):
    return _service(request).create_order(
        restaurant_id=body.restaurant_id,
        address=body.address,
        items=[item.model_dump() for item in body.items],
    )


@router.get("/orders/{order_id}")
def get_order(order_id: int, request: Request):
    return _service(request).get_order(order_id)


@router.patch("/orders/{order_id}/status")
def update_order_status(order_id: int, body: StatusIn, request: Request):
    return _service(request).update_status(order_id, body.status)
