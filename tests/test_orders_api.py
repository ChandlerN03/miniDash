import json

import pytest

# Seed menu item ids used below (see src/store/seed.py):
#   restaurant 1: items 1-4, restaurant 2: items 5-8, restaurant 3: items 9-12


def menu_price(client, restaurant_id: int, menu_item_id: int) -> int:
    menu = client.get(f"/restaurants/{restaurant_id}/menu").json()
    return next(item["price_cents"] for item in menu if item["id"] == menu_item_id)


def place_order(client, items=None, restaurant_id=1, address="12 Elm Street"):
    body = {
        "restaurant_id": restaurant_id,
        "address": address,
        "items": items if items is not None else [{"menu_item_id": 1, "quantity": 1}],
    }
    return client.post("/orders", body)


def assert_error(response, status_code: int, code: str):
    assert response.status_code == status_code
    error = response.json()["error"]
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]


# ---------------------------------------------------------------- POST /orders


def test_create_order_returns_201_with_total_in_integer_cents(client, clock):
    response = place_order(
        client,
        items=[{"menu_item_id": 1, "quantity": 2}, {"menu_item_id": 2, "quantity": 1}],
    )

    assert response.status_code == 201
    order = response.json()
    expected_total = 2 * menu_price(client, 1, 1) + menu_price(client, 1, 2)
    assert order["total_cents"] == expected_total
    assert isinstance(order["total_cents"], int)
    assert order["status"] == "PLACED"
    assert order["restaurant_id"] == 1
    assert order["address"] == "12 Elm Street"
    assert order["created_at"] == clock.now().isoformat()
    assert isinstance(order["id"], int)


def test_create_order_returns_order_items_with_unit_prices(client):
    order = place_order(client, items=[{"menu_item_id": 1, "quantity": 3}]).json()

    assert len(order["items"]) == 1
    item = order["items"][0]
    assert item["menu_item_id"] == 1
    assert item["quantity"] == 3
    assert item["unit_price_cents"] == menu_price(client, 1, 1)
    assert item["order_id"] == order["id"]


def test_create_order_merges_duplicate_menu_items(client):
    order = place_order(
        client,
        items=[{"menu_item_id": 1, "quantity": 1}, {"menu_item_id": 1, "quantity": 2}],
    ).json()

    assert len(order["items"]) == 1
    assert order["items"][0]["quantity"] == 3
    assert order["total_cents"] == 3 * menu_price(client, 1, 1)


def test_create_order_assigns_increasing_ids(client):
    first = place_order(client).json()
    second = place_order(client).json()

    assert second["id"] == first["id"] + 1


def test_create_order_unknown_restaurant(client):
    response = place_order(client, restaurant_id=999)

    assert_error(response, 404, "RESTAURANT_NOT_FOUND")


def test_create_order_item_from_another_restaurant(client):
    response = place_order(client, restaurant_id=1, items=[{"menu_item_id": 5, "quantity": 1}])

    assert_error(response, 400, "ITEM_NOT_ON_MENU")


def test_create_order_unknown_menu_item(client):
    response = place_order(client, items=[{"menu_item_id": 999, "quantity": 1}])

    assert_error(response, 400, "ITEM_NOT_ON_MENU")


@pytest.mark.parametrize("quantity", [0, -1])
def test_create_order_rejects_quantity_below_one(client, quantity):
    response = place_order(client, items=[{"menu_item_id": 1, "quantity": quantity}])

    assert_error(response, 400, "INVALID_QUANTITY")


def test_create_order_rejects_empty_items(client):
    response = place_order(client, items=[])

    assert_error(response, 400, "EMPTY_ORDER")


@pytest.mark.parametrize("address", ["", "   "])
def test_create_order_rejects_blank_address(client, address):
    response = place_order(client, address=address)

    assert_error(response, 400, "INVALID_ADDRESS")


def test_create_order_malformed_body_uses_error_format(client):
    response = client.post("/orders", {"restaurant_id": "abc"})

    assert_error(response, 422, "VALIDATION_ERROR")


def test_create_order_fractional_quantity_is_rejected(client):
    response = client.post(
        "/orders",
        {
            "restaurant_id": 1,
            "address": "12 Elm Street",
            "items": [{"menu_item_id": 1, "quantity": 1.5}],
        },
    )

    assert_error(response, 422, "VALIDATION_ERROR")


def test_rejected_order_is_not_stored(client, data_file):
    place_order(client, address="  ")
    place_order(client, restaurant_id=999)

    assert json.loads(data_file.read_text())["orders"] == []
    assert client.get("/orders/1").status_code == 404


def test_order_is_saved_in_the_json_file(client, data_file):
    order = place_order(client).json()

    data = json.loads(data_file.read_text())
    assert [o["id"] for o in data["orders"]] == [order["id"]]
    assert len(data["order_items"]) == 1


# ------------------------------------------------------------- GET /orders/{id}


def test_get_order_returns_the_order_with_items(client):
    created = place_order(client, items=[{"menu_item_id": 2, "quantity": 2}]).json()

    response = client.get(f"/orders/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_order_unknown_id_returns_404(client):
    response = client.get("/orders/999")

    assert_error(response, 404, "ORDER_NOT_FOUND")


# ------------------------------------------------ PATCH /orders/{id}/status


def set_status(client, order_id: int, status: str):
    return client.patch(f"/orders/{order_id}/status", {"status": status})


def test_status_moves_through_the_delivery_flow(client):
    order_id = place_order(client).json()["id"]

    for status in ["PREPARING", "OUT_FOR_DELIVERY", "DELIVERED"]:
        response = set_status(client, order_id, status)
        assert response.status_code == 200
        assert response.json()["status"] == status
        assert response.json()["id"] == order_id

    assert client.get(f"/orders/{order_id}").json()["status"] == "DELIVERED"


def test_status_update_returns_full_order(client):
    created = place_order(client).json()

    updated = set_status(client, created["id"], "PREPARING").json()

    assert updated == {**created, "status": "PREPARING"}


def test_status_cannot_skip_a_step(client):
    order_id = place_order(client).json()["id"]

    response = set_status(client, order_id, "DELIVERED")

    assert_error(response, 409, "INVALID_STATUS_TRANSITION")
    assert client.get(f"/orders/{order_id}").json()["status"] == "PLACED"


def test_status_cannot_go_backwards(client):
    order_id = place_order(client).json()["id"]
    set_status(client, order_id, "PREPARING")

    response = set_status(client, order_id, "PLACED")

    assert_error(response, 409, "INVALID_STATUS_TRANSITION")


def test_status_same_as_current_is_rejected(client):
    order_id = place_order(client).json()["id"]

    response = set_status(client, order_id, "PLACED")

    assert_error(response, 409, "INVALID_STATUS_TRANSITION")


@pytest.mark.parametrize("before", [[], ["PREPARING"]])
def test_order_can_be_cancelled_before_it_leaves_the_restaurant(client, before):
    order_id = place_order(client).json()["id"]
    for status in before:
        set_status(client, order_id, status)

    response = set_status(client, order_id, "CANCELLED")

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"


def test_order_cannot_be_cancelled_once_out_for_delivery(client):
    order_id = place_order(client).json()["id"]
    set_status(client, order_id, "PREPARING")
    set_status(client, order_id, "OUT_FOR_DELIVERY")

    response = set_status(client, order_id, "CANCELLED")

    assert_error(response, 409, "INVALID_STATUS_TRANSITION")


@pytest.mark.parametrize("final", ["DELIVERED", "CANCELLED"])
def test_final_statuses_cannot_change(client, final):
    order_id = place_order(client).json()["id"]
    if final == "DELIVERED":
        for status in ["PREPARING", "OUT_FOR_DELIVERY", "DELIVERED"]:
            set_status(client, order_id, status)
    else:
        set_status(client, order_id, "CANCELLED")

    response = set_status(client, order_id, "PREPARING")

    assert_error(response, 409, "INVALID_STATUS_TRANSITION")
    assert client.get(f"/orders/{order_id}").json()["status"] == final


def test_status_value_must_be_known(client):
    order_id = place_order(client).json()["id"]

    response = set_status(client, order_id, "TELEPORTED")

    assert_error(response, 400, "INVALID_STATUS")


def test_status_update_unknown_order_returns_404(client):
    response = set_status(client, 999, "PREPARING")

    assert_error(response, 404, "ORDER_NOT_FOUND")


def test_status_update_missing_field_uses_error_format(client):
    order_id = place_order(client).json()["id"]

    response = client.patch(f"/orders/{order_id}/status", {})

    assert_error(response, 422, "VALIDATION_ERROR")
