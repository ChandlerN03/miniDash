from fastapi import APIRouter, Request

from src.services.restaurant_service import RestaurantService

router = APIRouter()


def _service(request: Request) -> RestaurantService:
    return request.app.state.restaurant_service


@router.get("/restaurants")
def list_restaurants(request: Request):
    return _service(request).list_restaurants()


@router.get("/restaurants/{restaurant_id}/menu")
def get_menu(restaurant_id: int, request: Request):
    return _service(request).get_menu(restaurant_id)
