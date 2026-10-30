import json

from src.main import create_app
from tests.conftest import AsgiClient


def test_list_restaurants_returns_three_seeded_restaurants(client):
    response = client.get("/restaurants")

    assert response.status_code == 200
    restaurants = response.json()
    assert len(restaurants) == 3
    for restaurant in restaurants:
        assert set(restaurant) == {
            "id",
            "name",
            "cuisine",
            "opens_at",
            "closes_at",
            "avg_prep_minutes",
            "image_url",
        }
        assert isinstance(restaurant["avg_prep_minutes"], int)
        assert isinstance(restaurant["image_url"], str) and restaurant["image_url"]


def test_menu_returns_only_items_of_that_restaurant(client):
    restaurants = client.get("/restaurants").json()
    restaurant_id = restaurants[0]["id"]

    response = client.get(f"/restaurants/{restaurant_id}/menu")

    assert response.status_code == 200
    menu = response.json()
    assert len(menu) >= 3
    for item in menu:
        assert set(item) == {"id", "restaurant_id", "name", "price_cents", "image_url"}
        assert item["restaurant_id"] == restaurant_id
        assert isinstance(item["price_cents"], int)
        assert isinstance(item["image_url"], str) and item["image_url"]


def test_every_seeded_restaurant_has_a_menu(client):
    for restaurant in client.get("/restaurants").json():
        menu = client.get(f"/restaurants/{restaurant['id']}/menu").json()
        assert len(menu) >= 3


def test_menu_for_unknown_restaurant_returns_404(client):
    response = client.get("/restaurants/999/menu")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESTAURANT_NOT_FOUND"
    assert "message" in response.json()["error"]


def test_seed_data_is_written_to_the_given_json_file(client, data_file):
    client.get("/restaurants")

    data = json.loads(data_file.read_text())
    assert len(data["restaurants"]) == 3
    assert data["orders"] == []


def test_existing_data_is_not_reseeded(data_file, clock):
    first = AsgiClient(create_app(data_path=data_file, clock=clock))
    first.post(
        "/orders",
        {"restaurant_id": 1, "address": "1 Main St", "items": [{"menu_item_id": 1, "quantity": 1}]},
    )

    second = AsgiClient(create_app(data_path=data_file, clock=clock))

    assert second.get("/orders/1").status_code == 200
