import json

from src.main import create_app
from tests.conftest import AsgiClient


def test_list_restaurants_returns_the_four_seeded_restaurants(client):
    response = client.get("/restaurants")

    assert response.status_code == 200
    restaurants = response.json()
    assert len(restaurants) == 4
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
    assert len(data["restaurants"]) == 4
    assert data["orders"] == []


def test_existing_data_is_not_reseeded(data_file, clock):
    first = AsgiClient(create_app(data_path=data_file, clock=clock))
    first.post(
        "/orders",
        {"restaurant_id": 1, "address": "1 Main St", "items": [{"menu_item_id": 1, "quantity": 1}]},
    )

    second = AsgiClient(create_app(data_path=data_file, clock=clock))

    assert second.get("/orders/1").status_code == 200


# ------------------------------------------------------------------ the 24/7 diner


def diner(client) -> dict:
    return next(r for r in client.get("/restaurants").json() if r["name"] == "Starlight Diner")


def test_there_is_a_diner_that_is_open_24_hours_a_day(client):
    restaurant = diner(client)

    assert restaurant["id"] == 4
    assert restaurant["cuisine"] == "American"
    assert (restaurant["opens_at"], restaurant["closes_at"]) == ("00:00", "24:00")  # all day, every day
    assert isinstance(restaurant["avg_prep_minutes"], int) and restaurant["avg_prep_minutes"] > 0
    assert isinstance(restaurant["image_url"], str) and restaurant["image_url"]


def test_the_diner_has_a_menu_with_whole_cent_prices(client):
    menu = client.get(f"/restaurants/{diner(client)['id']}/menu").json()

    assert len(menu) >= 5
    assert all(item["restaurant_id"] == 4 and type(item["price_cents"]) is int and item["price_cents"] > 0 for item in menu)
    assert len({item["name"] for item in menu}) == len(menu)


def test_menu_item_ids_are_unique_across_all_restaurants(client):
    ids = [item["id"] for r in client.get("/restaurants").json() for item in client.get(f"/restaurants/{r['id']}/menu").json()]

    assert len(ids) == len(set(ids))


def test_the_other_three_restaurants_and_their_hours_are_unchanged(client):
    hours = {r["id"]: (r["name"], r["opens_at"], r["closes_at"]) for r in client.get("/restaurants").json()}

    assert hours[1] == ("Luigi's Pizzeria", "11:00", "22:00")
    assert hours[2] == ("Sakura Sushi", "12:00", "21:30")
    assert hours[3] == ("Taco Loco", "10:00", "23:00")


def test_an_order_can_be_placed_at_the_diner(client):
    item = client.get("/restaurants/4/menu").json()[0]

    response = client.post("/orders", {"restaurant_id": 4, "address": "1 Main St", "items": [{"menu_item_id": item["id"], "quantity": 2}]})

    assert response.status_code == 201 and response.json()["total_cents"] == 2 * item["price_cents"]
