import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.main import create_app
from src.services.errors import MiniDashError
from src.services.group_order_service import EmptyParticipantError

# Far from the real current time. 12:00:00 UTC is when restaurant 2 opens (12:00 to 21:30).
START = datetime(2001, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
TWO_HOURS = timedelta(hours=2)

RESTAURANT = 2
ITEM_A, ITEM_B = 5, 6  # restaurant 2 menu: A = 899 cents, B = 1099 cents
OTHER_RESTAURANT_ITEM = 1
ADDRESS = "12 Elm Street"


# ------------------------------------------------------------------ test client
# conftest's client cannot send headers or DELETE requests, and FastAPI's TestClient
# needs httpx (not allowed), so this file calls the ASGI app directly.


class Response:
    def __init__(self, status_code: int, body: bytes):
        self.status_code = status_code
        self.body = body

    def json(self):
        return json.loads(self.body)


class ApiClient:
    def __init__(self, app):
        self._app = app

    def get(self, path, token=None):
        return self.request("GET", path, token=token)

    def post(self, path, body=None, token=None, raw_body=None):
        return self.request("POST", path, body, token, raw_body)

    def patch(self, path, body=None, token=None):
        return self.request("PATCH", path, body, token)

    def delete(self, path, token=None):
        return self.request("DELETE", path, token=token)

    def request(self, method, path, body=None, token=None, raw_body=None) -> Response:
        if raw_body is not None:
            payload = raw_body
        elif body is not None:
            payload = json.dumps(body).encode()
        else:
            payload = b""
        headers = [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode()),
        ]
        if token is not None:  # an empty string is sent as an empty header
            headers.append((b"x-session-token", token.encode()))
        return asyncio.run(self._call(method, path, payload, headers))

    async def _call(self, method, path, payload, headers) -> Response:
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": headers,
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
        sent = False

        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": payload, "more_body": False}
            return {"type": "http.disconnect"}

        status = 500
        chunks: list[bytes] = []

        async def send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))

        await self._app(scope, receive, send)
        return Response(status, b"".join(chunks))


class FakeClock:
    def __init__(self, now: datetime = START):
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta

    def set(self, now: datetime) -> None:
        self._now = now


@pytest.fixture
def fake_clock():
    return FakeClock()


@pytest.fixture
def app(data_file, fake_clock):
    return create_app(data_path=data_file, clock=fake_clock)


@pytest.fixture
def api(app):
    return ApiClient(app)


# ---------------------------------------------------------------------- helpers


def group_path(code, tail=""):
    return f"/group-orders/{code}{tail}"


def items_path(code, participant_id):
    return group_path(code, f"/participants/{participant_id}/items")


def item_path(code, participant_id, menu_item_id):
    return group_path(code, f"/participants/{participant_id}/items/{menu_item_id}")


def new_session(api) -> str:
    response = api.post("/sessions")
    assert response.status_code == 201
    return response.json()["token"]


def new_group(api, restaurant_id=RESTAURANT, name="Host"):
    """Returns (host_token, code)."""
    host = new_session(api)
    response = api.post("/group-orders", {"restaurant_id": restaurant_id, "display_name": name}, token=host)
    assert response.status_code == 201
    return host, response.json()["code"]


def join_group(api, code, name="Guest"):
    """Returns (guest_token, participant_id)."""
    guest = new_session(api)
    response = api.post(group_path(code, "/join"), {"display_name": name}, token=guest)
    assert response.status_code == 201
    return guest, response.json()["participant_id"]


def add_item(api, token, code, participant_id, menu_item_id, quantity):
    return api.post(
        items_path(code, participant_id), {"menu_item_id": menu_item_id, "quantity": quantity}, token=token
    )


def ready_group(api):
    """An OPEN group where the host has A x2 and the guest B x1. Returns a namespace."""
    host, code = new_group(api)
    guest, guest_id = join_group(api, code)
    assert add_item(api, host, code, 1, ITEM_A, 2).status_code == 201
    assert add_item(api, guest, code, guest_id, ITEM_B, 1).status_code == 201
    return SimpleNamespace(host=host, guest=guest, code=code, guest_id=guest_id)


def locked_group(api):
    group = ready_group(api)
    assert api.post(group_path(group.code, "/lock"), token=group.host).status_code == 200
    return group


def assert_error(response, status_code: int, code: str):
    assert response.status_code == status_code, response.body
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]


# ============================================================ R1: POST /sessions


def test_post_sessions_returns_201_and_a_token(api):
    response = api.post("/sessions")

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"token"}
    assert isinstance(body["token"], str) and body["token"]


def test_every_session_token_is_different(api):
    tokens = {new_session(api) for _ in range(20)}

    assert len(tokens) == 20


def test_post_sessions_needs_no_token_or_body(api):
    assert api.post("/sessions", token=None).status_code == 201


def test_a_new_session_token_works_in_later_requests(api):
    token = new_session(api)

    response = api.post("/group-orders", {"restaurant_id": RESTAURANT, "display_name": "Hana"}, token=token)

    assert response.status_code == 201


# ===================================================== POST /group-orders


def test_post_group_orders_returns_201_with_code_and_status(api):
    host = new_session(api)

    response = api.post("/group-orders", {"restaurant_id": RESTAURANT, "display_name": "Hana"}, token=host)

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"code", "status"}
    assert body["status"] == "OPEN"
    assert len(body["code"]) == 6


def test_post_group_orders_unknown_restaurant_gives_404(api):
    host = new_session(api)

    response = api.post("/group-orders", {"restaurant_id": 999, "display_name": "Hana"}, token=host)

    assert_error(response, 404, "RESTAURANT_NOT_FOUND")


def test_post_group_orders_without_a_session_gives_401(api):
    response = api.post("/group-orders", {"restaurant_id": RESTAURANT, "display_name": "Hana"})

    assert_error(response, 401, "INVALID_SESSION")


@pytest.mark.parametrize(
    "body",
    [{}, {"restaurant_id": RESTAURANT}, {"display_name": "Hana"}, {"restaurant_id": "two", "display_name": "Hana"}],
)
def test_post_group_orders_with_a_bad_body_gives_422_in_the_shared_shape(api, body):
    host = new_session(api)

    assert_error(api.post("/group-orders", body, token=host), 422, "VALIDATION_ERROR")


# ================================================ POST /group-orders/{code}/join


def test_join_returns_201_and_the_participant(api):
    _, code = new_group(api, name="Hana")
    guest = new_session(api)

    response = api.post(group_path(code, "/join"), {"display_name": "Bo"}, token=guest)

    assert response.status_code == 201
    body = response.json()
    assert body["participant_id"] == 2
    assert body["display_name"] == "Bo"
    assert isinstance(body["joined_at"], str)


def test_join_does_not_send_the_session_token_back(api):
    _, code = new_group(api)
    guest = new_session(api)

    body = api.post(group_path(code, "/join"), {"display_name": "Bo"}, token=guest).json()

    assert set(body) == {"participant_id", "display_name", "joined_at"}
    assert guest not in json.dumps(body)


def test_join_with_a_wrong_code_gives_404(api):
    guest = new_session(api)

    assert_error(api.post(group_path("nope42", "/join"), {"display_name": "Bo"}, token=guest), 404, "INVALID_CODE")


def test_joining_twice_gives_409(api):
    _, code = new_group(api)
    guest, _ = join_group(api, code)

    response = api.post(group_path(code, "/join"), {"display_name": "Bo again"}, token=guest)

    assert_error(response, 409, "ALREADY_JOINED")


def test_the_11th_participant_gets_409_group_full(api):
    _, code = new_group(api)
    for number in range(2, 11):
        join_group(api, code, f"Guest {number}")
    eleventh = new_session(api)

    response = api.post(group_path(code, "/join"), {"display_name": "Eleven"}, token=eleventh)

    assert_error(response, 409, "GROUP_FULL")


def test_joining_a_locked_group_gives_409(api):
    group = locked_group(api)
    late = new_session(api)

    assert_error(api.post(group_path(group.code, "/join"), {"display_name": "Late"}, token=late), 409, "ORDER_LOCKED")


def test_joining_an_expired_group_gives_409(api, fake_clock):
    _, code = new_group(api)
    fake_clock.advance(TWO_HOURS)
    late = new_session(api)

    assert_error(api.post(group_path(code, "/join"), {"display_name": "Late"}, token=late), 409, "ORDER_EXPIRED")


def test_joining_a_checked_out_group_gives_409(api):
    group = locked_group(api)
    assert api.post(group_path(group.code, "/checkout"), {"address": ADDRESS}, token=group.host).status_code == 201
    late = new_session(api)

    response = api.post(group_path(group.code, "/join"), {"display_name": "Late"}, token=late)

    assert_error(response, 409, "ORDER_CHECKED_OUT")


def test_join_without_a_display_name_gives_422(api):
    _, code = new_group(api)

    assert_error(api.post(group_path(code, "/join"), {}, token=new_session(api)), 422, "VALIDATION_ERROR")


# ===================================== POST /group-orders/{code}/participants/{id}/items


def test_add_item_returns_201_and_the_item(api):
    host, code = new_group(api)

    response = add_item(api, host, code, 1, ITEM_A, 2)

    assert response.status_code == 201
    assert response.json() == {"participant_id": 1, "menu_item_id": ITEM_A, "quantity": 2}


def test_adding_the_same_item_again_adds_to_the_quantity(api):
    host, code = new_group(api)
    add_item(api, host, code, 1, ITEM_A, 2)

    response = add_item(api, host, code, 1, ITEM_A, 3)

    assert response.status_code == 201
    assert response.json()["quantity"] == 5


@pytest.mark.parametrize("quantity", [0, 10, -1])
def test_add_item_with_a_quantity_outside_1_to_9_gives_400(api, quantity):
    host, code = new_group(api)

    assert_error(add_item(api, host, code, 1, ITEM_A, quantity), 400, "INVALID_QUANTITY")


def test_add_item_pushing_the_total_above_9_gives_400(api):
    host, code = new_group(api)
    add_item(api, host, code, 1, ITEM_A, 8)

    assert_error(add_item(api, host, code, 1, ITEM_A, 2), 400, "INVALID_QUANTITY")


def test_add_item_from_another_restaurant_gives_400(api):
    host, code = new_group(api)

    assert_error(add_item(api, host, code, 1, OTHER_RESTAURANT_ITEM, 1), 400, "ITEM_NOT_ON_MENU")


def test_add_item_for_another_participant_gives_403(api):
    group = ready_group(api)

    assert_error(add_item(api, group.guest, group.code, 1, ITEM_B, 1), 403, "NOT_ALLOWED")


def test_add_item_with_a_wrong_code_gives_404(api):
    host, _ = new_group(api)

    assert_error(add_item(api, host, "nope42", 1, ITEM_A, 1), 404, "INVALID_CODE")


def test_add_item_to_a_locked_group_gives_409(api):
    group = locked_group(api)

    assert_error(add_item(api, group.host, group.code, 1, ITEM_B, 1), 409, "ORDER_LOCKED")


def test_add_item_to_an_expired_group_gives_409(api, fake_clock):
    host, code = new_group(api)
    fake_clock.advance(TWO_HOURS)

    assert_error(add_item(api, host, code, 1, ITEM_A, 1), 409, "ORDER_EXPIRED")


@pytest.mark.parametrize(
    "body",
    [{}, {"menu_item_id": ITEM_A}, {"quantity": 1}, {"menu_item_id": ITEM_A, "quantity": 1.5},
     {"menu_item_id": ITEM_A, "quantity": "2"}, {"menu_item_id": "five", "quantity": 1}],
)
def test_add_item_with_a_bad_body_gives_422(api, body):
    host, code = new_group(api)

    assert_error(api.post(items_path(code, 1), body, token=host), 422, "VALIDATION_ERROR")


def test_a_participant_id_that_is_not_a_number_gives_422(api):
    host, code = new_group(api)

    response = api.post(items_path(code, "one"), {"menu_item_id": ITEM_A, "quantity": 1}, token=host)

    assert_error(response, 422, "VALIDATION_ERROR")


# ======================= PATCH /group-orders/{code}/participants/{id}/items/{menu_item_id}


def test_patch_item_returns_204_with_no_body_and_changes_the_quantity(api):
    group = ready_group(api)

    response = api.patch(item_path(group.code, group.guest_id, ITEM_B), {"quantity": 4}, token=group.guest)

    assert response.status_code == 204
    assert response.body == b""
    summary = api.get(group_path(group.code, "/summary"), token=group.host).json()
    assert summary["participants"][1]["subtotal_cents"] == 4 * 1099


def test_patch_item_of_another_participant_gives_403(api):
    group = ready_group(api)

    response = api.patch(item_path(group.code, 1, ITEM_A), {"quantity": 4}, token=group.guest)

    assert_error(response, 403, "NOT_ALLOWED")


def test_the_host_cannot_change_another_participants_quantity(api):
    group = ready_group(api)

    response = api.patch(item_path(group.code, group.guest_id, ITEM_B), {"quantity": 4}, token=group.host)

    assert_error(response, 403, "NOT_ALLOWED")


def test_patch_item_the_participant_does_not_have_gives_404(api):
    group = ready_group(api)

    response = api.patch(item_path(group.code, group.guest_id, ITEM_A), {"quantity": 2}, token=group.guest)

    assert_error(response, 404, "ITEM_NOT_IN_ORDER")


@pytest.mark.parametrize("quantity", [0, 10])
def test_patch_item_with_a_bad_quantity_gives_400(api, quantity):
    group = ready_group(api)

    response = api.patch(item_path(group.code, group.guest_id, ITEM_B), {"quantity": quantity}, token=group.guest)

    assert_error(response, 400, "INVALID_QUANTITY")


def test_patch_item_on_a_locked_group_gives_409(api):
    group = locked_group(api)

    response = api.patch(item_path(group.code, group.guest_id, ITEM_B), {"quantity": 2}, token=group.guest)

    assert_error(response, 409, "ORDER_LOCKED")


def test_patch_item_without_a_quantity_gives_422(api):
    group = ready_group(api)

    response = api.patch(item_path(group.code, group.guest_id, ITEM_B), {}, token=group.guest)

    assert_error(response, 422, "VALIDATION_ERROR")


# ====================== DELETE /group-orders/{code}/participants/{id}/items/{menu_item_id}


def test_delete_item_returns_204_with_no_body_and_removes_it(api):
    group = ready_group(api)

    response = api.delete(item_path(group.code, group.guest_id, ITEM_B), token=group.guest)

    assert response.status_code == 204
    assert response.body == b""
    summary = api.get(group_path(group.code, "/summary"), token=group.host).json()
    assert summary["participants"][1]["subtotal_cents"] == 0


def test_the_host_can_delete_another_participants_item(api):
    group = ready_group(api)

    response = api.delete(item_path(group.code, group.guest_id, ITEM_B), token=group.host)

    assert response.status_code == 204
    summary = api.get(group_path(group.code, "/summary"), token=group.host).json()
    assert summary["participants"][1]["subtotal_cents"] == 0


def test_a_guest_cannot_delete_the_hosts_item(api):
    group = ready_group(api)

    assert_error(api.delete(item_path(group.code, 1, ITEM_A), token=group.guest), 403, "NOT_ALLOWED")


def test_delete_item_the_participant_does_not_have_gives_404(api):
    group = ready_group(api)

    assert_error(
        api.delete(item_path(group.code, group.guest_id, ITEM_A), token=group.guest), 404, "ITEM_NOT_IN_ORDER"
    )


def test_delete_item_on_a_locked_group_gives_409(api):
    group = locked_group(api)

    assert_error(
        api.delete(item_path(group.code, group.guest_id, ITEM_B), token=group.guest), 409, "ORDER_LOCKED"
    )


def test_delete_item_not_on_the_menu_gives_400(api):
    group = ready_group(api)

    response = api.delete(item_path(group.code, group.guest_id, OTHER_RESTAURANT_ITEM), token=group.guest)

    assert_error(response, 400, "ITEM_NOT_ON_MENU")


# ============================================== GET /group-orders/{code}/summary


def test_summary_returns_200_with_each_participant_in_join_order(api):
    group = ready_group(api)

    response = api.get(group_path(group.code, "/summary"), token=group.guest)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "OPEN"
    assert body["delivery_fee_cents"] == 499
    host_entry, guest_entry = body["participants"]
    assert host_entry == {
        "participant_id": 1,
        "display_name": "Host",
        "subtotal_cents": 2 * 899,
        "fee_share_cents": 249,
        "total_cents": 2 * 899 + 249,
    }
    assert guest_entry == {
        "participant_id": 2,
        "display_name": "Guest",
        "subtotal_cents": 1099,
        "fee_share_cents": 250,
        "total_cents": 1099 + 250,
    }


def test_summary_with_a_wrong_code_gives_404(api):
    host, _ = new_group(api)

    assert_error(api.get(group_path("nope42", "/summary"), token=host), 404, "INVALID_CODE")


def test_summary_for_someone_outside_the_group_gives_403(api):
    _, code = new_group(api)

    assert_error(api.get(group_path(code, "/summary"), token=new_session(api)), 403, "NOT_ALLOWED")


def test_summary_of_an_expired_group_still_returns_200_with_status_expired(api, fake_clock):
    host, code = new_group(api)
    fake_clock.advance(TWO_HOURS)

    response = api.get(group_path(code, "/summary"), token=host)

    assert response.status_code == 200
    assert response.json()["status"] == "EXPIRED"


# =================================================== POST /group-orders/{code}/lock


def test_lock_returns_200_and_status_locked(api):
    group = ready_group(api)

    response = api.post(group_path(group.code, "/lock"), token=group.host)

    assert response.status_code == 200
    assert response.json() == {"code": group.code, "status": "LOCKED"}
    assert api.get(group_path(group.code, "/summary"), token=group.host).json()["status"] == "LOCKED"


def test_lock_by_a_guest_gives_403(api):
    group = ready_group(api)

    assert_error(api.post(group_path(group.code, "/lock"), token=group.guest), 403, "NOT_HOST")


def test_lock_with_an_empty_participant_gives_409_and_names_them(api):
    host, code = new_group(api)
    join_group(api, code, "Sleepy")
    add_item(api, host, code, 1, ITEM_A, 1)

    response = api.post(group_path(code, "/lock"), token=host)

    assert_error(response, 409, "EMPTY_PARTICIPANT")
    assert "Sleepy" in response.json()["error"]["message"]


def test_lock_on_an_expired_group_gives_409(api, fake_clock):
    group = ready_group(api)
    fake_clock.advance(TWO_HOURS)

    assert_error(api.post(group_path(group.code, "/lock"), token=group.host), 409, "ORDER_EXPIRED")


def test_lock_with_a_wrong_code_gives_404(api):
    host, _ = new_group(api)

    assert_error(api.post(group_path("nope42", "/lock"), token=host), 404, "INVALID_CODE")


def test_locking_twice_gives_409(api):
    group = locked_group(api)

    assert_error(api.post(group_path(group.code, "/lock"), token=group.host), 409, "ORDER_LOCKED")


# ================================================ POST /group-orders/{code}/checkout


def test_checkout_returns_201_with_the_order_id(api):
    group = locked_group(api)

    response = api.post(group_path(group.code, "/checkout"), {"address": ADDRESS}, token=group.host)

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"order_id", "status", "total_cents"}
    assert body["status"] == "CHECKED_OUT"
    assert body["total_cents"] == 2 * 899 + 1099 + 499


def test_checkout_by_a_guest_gives_403(api):
    group = locked_group(api)

    response = api.post(group_path(group.code, "/checkout"), {"address": ADDRESS}, token=group.guest)

    assert_error(response, 403, "NOT_HOST")


def test_checkout_of_an_open_group_gives_409(api):
    group = ready_group(api)

    response = api.post(group_path(group.code, "/checkout"), {"address": ADDRESS}, token=group.host)

    assert_error(response, 409, "NOT_LOCKED")


def test_checkout_while_the_restaurant_is_closed_gives_409(api, fake_clock):
    fake_clock.set(datetime(2001, 1, 1, 11, 0, 0, tzinfo=timezone.utc))  # restaurant 2 opens at 12:00
    group = locked_group(api)

    response = api.post(group_path(group.code, "/checkout"), {"address": ADDRESS}, token=group.host)

    assert_error(response, 409, "RESTAURANT_CLOSED")


@pytest.mark.parametrize("body", [{"address": ""}, {"address": "   "}, {"address": None}, {"address": 123}, {}])
def test_checkout_with_a_missing_or_blank_address_gives_400(api, body):
    group = locked_group(api)

    assert_error(api.post(group_path(group.code, "/checkout"), body, token=group.host), 400, "INVALID_ADDRESS")


def test_checkout_with_no_body_at_all_gives_400_invalid_address(api):
    group = locked_group(api)

    assert_error(api.post(group_path(group.code, "/checkout"), token=group.host), 400, "INVALID_ADDRESS")


def test_a_second_checkout_gives_409(api):
    group = locked_group(api)
    api.post(group_path(group.code, "/checkout"), {"address": ADDRESS}, token=group.host)

    response = api.post(group_path(group.code, "/checkout"), {"address": ADDRESS}, token=group.host)

    assert_error(response, 409, "ORDER_CHECKED_OUT")


def test_checkout_on_an_expired_group_gives_409(api, fake_clock):
    group = locked_group(api)
    fake_clock.advance(TWO_HOURS)

    response = api.post(group_path(group.code, "/checkout"), {"address": ADDRESS}, token=group.host)

    assert_error(response, 409, "ORDER_EXPIRED")


def test_checkout_with_a_wrong_code_gives_404(api):
    host, _ = new_group(api)

    assert_error(api.post(group_path("nope42", "/checkout"), {"address": ADDRESS}, token=host), 404, "INVALID_CODE")


# ============================================ R2: the X-Session-Token header


def protected_requests(code):
    """Every group-order request that needs a session: (id, method, path, body)."""
    return [
        ("create-group", "POST", "/group-orders", {"restaurant_id": RESTAURANT, "display_name": "Hana"}),
        ("join", "POST", group_path(code, "/join"), {"display_name": "Bo"}),
        ("add-item", "POST", items_path(code, 1), {"menu_item_id": ITEM_A, "quantity": 1}),
        ("change-item", "PATCH", item_path(code, 1, ITEM_A), {"quantity": 2}),
        ("remove-item", "DELETE", item_path(code, 1, ITEM_A), None),
        ("summary", "GET", group_path(code, "/summary"), None),
        ("lock", "POST", group_path(code, "/lock"), None),
        ("checkout", "POST", group_path(code, "/checkout"), {"address": ADDRESS}),
    ]


PROTECTED_IDS = [row[0] for row in protected_requests("x")]


@pytest.mark.parametrize("index", range(len(PROTECTED_IDS)), ids=PROTECTED_IDS)
def test_a_missing_session_token_gives_401_invalid_session(api, index):
    _, code = new_group(api)
    _, method, path, body = protected_requests(code)[index]

    assert_error(api.request(method, path, body), 401, "INVALID_SESSION")


@pytest.mark.parametrize("index", range(len(PROTECTED_IDS)), ids=PROTECTED_IDS)
@pytest.mark.parametrize("token", ["", "never-issued"])
def test_an_empty_or_unknown_session_token_gives_401_invalid_session(api, index, token):
    _, code = new_group(api)
    _, method, path, body = protected_requests(code)[index]

    assert_error(api.request(method, path, body, token=token), 401, "INVALID_SESSION")


def test_the_token_is_only_read_from_the_header_not_the_body(api):
    _, code = new_group(api)
    token = new_session(api)

    response = api.post(
        group_path(code, "/join"), {"display_name": "Bo", "token": token, "session_token": token}
    )

    assert_error(response, 401, "INVALID_SESSION")


def test_the_session_check_comes_before_the_code_check(api):
    assert_error(api.post(group_path("nope42", "/join"), {"display_name": "Bo"}), 401, "INVALID_SESSION")


# =========================================== R39: every error has the shared shape


def error_cases():
    """Functions that each make one rejected request. They take (api, fake_clock)."""

    def no_token(api, clock):
        return api.post("/group-orders", {"restaurant_id": RESTAURANT, "display_name": "H"})

    def unknown_restaurant(api, clock):
        return api.post("/group-orders", {"restaurant_id": 999, "display_name": "H"}, token=new_session(api))

    def bad_body(api, clock):
        return api.post("/group-orders", {"restaurant_id": "x"}, token=new_session(api))

    def broken_json(api, clock):
        return api.post("/group-orders", token=new_session(api), raw_body=b"{not json")

    def wrong_code(api, clock):
        return api.post(group_path("nope42", "/join"), {"display_name": "B"}, token=new_session(api))

    def already_joined(api, clock):
        group = ready_group(api)
        return api.post(group_path(group.code, "/join"), {"display_name": "B"}, token=group.guest)

    def bad_quantity(api, clock):
        host, code = new_group(api)
        return add_item(api, host, code, 1, ITEM_A, 0)

    def not_on_menu(api, clock):
        host, code = new_group(api)
        return add_item(api, host, code, 1, OTHER_RESTAURANT_ITEM, 1)

    def not_allowed(api, clock):
        group = ready_group(api)
        return add_item(api, group.guest, group.code, 1, ITEM_B, 1)

    def item_not_in_order(api, clock):
        group = ready_group(api)
        return api.delete(item_path(group.code, group.guest_id, ITEM_A), token=group.guest)

    def summary_outsider(api, clock):
        _, code = new_group(api)
        return api.get(group_path(code, "/summary"), token=new_session(api))

    def not_host(api, clock):
        group = ready_group(api)
        return api.post(group_path(group.code, "/lock"), token=group.guest)

    def empty_participant(api, clock):
        host, code = new_group(api)
        join_group(api, code)
        return api.post(group_path(code, "/lock"), token=host)

    def not_locked(api, clock):
        group = ready_group(api)
        return api.post(group_path(group.code, "/checkout"), {"address": ADDRESS}, token=group.host)

    def blank_address(api, clock):
        group = locked_group(api)
        return api.post(group_path(group.code, "/checkout"), {"address": " "}, token=group.host)

    def expired(api, clock):
        group = locked_group(api)
        clock.advance(TWO_HOURS)
        return api.post(group_path(group.code, "/checkout"), {"address": ADDRESS}, token=group.host)

    def restaurant_closed(api, clock):
        clock.set(datetime(2001, 1, 1, 11, 0, 0, tzinfo=timezone.utc))
        group = locked_group(api)
        return api.post(group_path(group.code, "/checkout"), {"address": ADDRESS}, token=group.host)

    def bad_path_parameter(api, clock):
        host, code = new_group(api)
        return api.post(items_path(code, "one"), {"menu_item_id": ITEM_A, "quantity": 1}, token=host)

    return [
        no_token, unknown_restaurant, bad_body, broken_json, wrong_code, already_joined, bad_quantity,
        not_on_menu, not_allowed, item_not_in_order, summary_outsider, not_host, empty_participant, not_locked,
        blank_address, expired, restaurant_closed, bad_path_parameter,
    ]


@pytest.mark.parametrize("make_request", error_cases(), ids=lambda f: f.__name__)
def test_every_error_response_is_shaped_error_code_message(api, fake_clock, make_request):
    response = make_request(api, fake_clock)

    assert 400 <= response.status_code < 500
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    assert isinstance(body["error"]["code"], str) and body["error"]["code"]
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    assert body["error"]["code"].isupper() or "_" in body["error"]["code"]


# ============================== R39: each error code maps to its HTTP status


class RaisingService:
    """Stands in for GroupOrderService and raises the error it is given."""

    def __init__(self, error):
        self._error = error

    def get_summary(self, token, code):
        raise self._error


STATUS_BY_CODE = [
    # 400
    ("INVALID_QUANTITY", 400), ("INVALID_ADDRESS", 400), ("ITEM_NOT_ON_MENU", 400),
    # 401
    ("INVALID_SESSION", 401),
    # 403
    ("NOT_HOST", 403), ("NOT_ALLOWED", 403),
    # 404
    ("INVALID_CODE", 404), ("RESTAURANT_NOT_FOUND", 404), ("ITEM_NOT_IN_ORDER", 404),
    # 409
    ("GROUP_FULL", 409), ("ALREADY_JOINED", 409), ("ORDER_LOCKED", 409), ("ORDER_EXPIRED", 409),
    ("ORDER_CHECKED_OUT", 409), ("NOT_LOCKED", 409), ("EMPTY_PARTICIPANT", 409), ("RESTAURANT_CLOSED", 409),
]


@pytest.mark.parametrize(("code", "status_code"), STATUS_BY_CODE, ids=[c for c, _ in STATUS_BY_CODE])
def test_each_error_code_has_its_http_status(app, api, code, status_code):
    app.state.group_order_service = RaisingService(MiniDashError(code, "a message"))

    response = api.get(group_path("Ab3dEf", "/summary"), token="t")

    assert_error(response, status_code, code)
    assert response.json()["error"]["message"] == "a message"


def test_the_empty_participant_error_is_sent_as_409_in_the_shared_shape(app, api):
    error = EmptyParticipantError([{"participant_id": 2, "display_name": "Sleepy"}])
    app.state.group_order_service = RaisingService(error)

    response = api.get(group_path("Ab3dEf", "/summary"), token="t")

    assert_error(response, 409, "EMPTY_PARTICIPANT")
    assert "Sleepy" in response.json()["error"]["message"]


def test_the_existing_order_error_statuses_are_unchanged(api):
    assert_error(api.get("/orders/999"), 404, "ORDER_NOT_FOUND")
    assert_error(api.get("/restaurants/999/menu"), 404, "RESTAURANT_NOT_FOUND")
    response = api.post("/orders", {"restaurant_id": RESTAURANT, "address": " ", "items": []})
    assert_error(response, 400, "INVALID_ADDRESS")


# ===================== routes only parse the request and call the service (no rules)


class RecordingService:
    def __init__(self):
        self.calls = []

    def create_session(self):
        self.calls.append(("create_session",))
        return "tok-new"

    def create_group_order(self, token, restaurant_id, display_name):
        self.calls.append(("create_group_order", token, restaurant_id, display_name))
        return {"code": "Ab3dEf", "status": "OPEN"}

    def join(self, token, code, display_name):
        self.calls.append(("join", token, code, display_name))
        return {"participant_id": 2, "token": token, "display_name": display_name, "joined_at": "t"}

    def add_item(self, token, code, participant_id, menu_item_id, quantity):
        self.calls.append(("add_item", token, code, participant_id, menu_item_id, quantity))
        return {"participant_id": participant_id, "menu_item_id": menu_item_id, "quantity": quantity}

    def change_item(self, token, code, participant_id, menu_item_id, quantity):
        self.calls.append(("change_item", token, code, participant_id, menu_item_id, quantity))
        return {"participant_id": participant_id, "menu_item_id": menu_item_id, "quantity": quantity}

    def remove_item(self, token, code, participant_id, menu_item_id):
        self.calls.append(("remove_item", token, code, participant_id, menu_item_id))

    def get_summary(self, token, code):
        self.calls.append(("get_summary", token, code))
        return {"status": "OPEN", "delivery_fee_cents": 499, "participants": []}

    def lock(self, token, code):
        self.calls.append(("lock", token, code))
        return {"code": code, "status": "LOCKED"}

    def checkout(self, token, code, address):
        self.calls.append(("checkout", token, code, address))
        return {"order_id": 7, "status": "CHECKED_OUT", "total_cents": 123}


@pytest.fixture
def recorder(app):
    service = RecordingService()
    app.state.group_order_service = service
    return service


def test_post_sessions_calls_create_session(api, recorder):
    response = api.post("/sessions")

    assert (response.status_code, response.json()) == (201, {"token": "tok-new"})
    assert recorder.calls == [("create_session",)]


def test_post_group_orders_passes_the_header_and_body_to_the_service(api, recorder):
    response = api.post("/group-orders", {"restaurant_id": 3, "display_name": "Hana"}, token="tok-1")

    assert (response.status_code, response.json()) == (201, {"code": "Ab3dEf", "status": "OPEN"})
    assert recorder.calls == [("create_group_order", "tok-1", 3, "Hana")]


def test_join_passes_the_header_code_and_name(api, recorder):
    response = api.post(group_path("Ab3dEf", "/join"), {"display_name": "Bo"}, token="tok-2")

    assert response.status_code == 201
    assert recorder.calls == [("join", "tok-2", "Ab3dEf", "Bo")]
    assert response.json() == {"participant_id": 2, "display_name": "Bo", "joined_at": "t"}  # no token


def test_add_item_passes_integer_path_parameters_and_the_body(api, recorder):
    response = api.post(items_path("Ab3dEf", 3), {"menu_item_id": 5, "quantity": 2}, token="tok-3")

    assert response.status_code == 201
    assert recorder.calls == [("add_item", "tok-3", "Ab3dEf", 3, 5, 2)]


def test_patch_item_passes_the_path_parameters_and_the_quantity(api, recorder):
    response = api.patch(item_path("Ab3dEf", 3, 5), {"quantity": 4}, token="tok-3")

    assert (response.status_code, response.body) == (204, b"")
    assert recorder.calls == [("change_item", "tok-3", "Ab3dEf", 3, 5, 4)]


def test_delete_item_passes_the_path_parameters(api, recorder):
    response = api.delete(item_path("Ab3dEf", 3, 5), token="tok-3")

    assert (response.status_code, response.body) == (204, b"")
    assert recorder.calls == [("remove_item", "tok-3", "Ab3dEf", 3, 5)]


def test_summary_lock_and_checkout_pass_the_header_and_code(api, recorder):
    summary = api.get(group_path("Ab3dEf", "/summary"), token="tok-4")
    lock = api.post(group_path("Ab3dEf", "/lock"), token="tok-4")
    checkout = api.post(group_path("Ab3dEf", "/checkout"), {"address": ADDRESS}, token="tok-4")

    assert (summary.status_code, lock.status_code, checkout.status_code) == (200, 200, 201)
    assert recorder.calls == [
        ("get_summary", "tok-4", "Ab3dEf"),
        ("lock", "tok-4", "Ab3dEf"),
        ("checkout", "tok-4", "Ab3dEf", ADDRESS),
    ]


def test_the_route_does_not_decide_about_a_missing_header_it_passes_none(api, recorder):
    api.post(group_path("Ab3dEf", "/lock"))  # no X-Session-Token

    assert recorder.calls == [("lock", None, "Ab3dEf")]


@pytest.mark.parametrize(("body", "expected"), [({}, None), ({"address": None}, None), ({"address": 5}, 5), (None, None)])
def test_checkout_passes_whatever_address_it_got_and_lets_the_service_decide(api, recorder, body, expected):
    api.post(group_path("Ab3dEf", "/checkout"), body, token="tok-4")

    assert recorder.calls == [("checkout", "tok-4", "Ab3dEf", expected)]


def test_the_route_does_not_validate_quantity_ranges(api, recorder):
    api.post(items_path("Ab3dEf", 1), {"menu_item_id": 5, "quantity": 99}, token="tok")  # the service decides

    assert recorder.calls == [("add_item", "tok", "Ab3dEf", 1, 5, 99)]


# ============================================== one route per row of the design


def test_every_endpoint_of_the_design_exists(app):
    paths = app.openapi()["paths"]
    expected = {
        ("post", "/sessions"),
        ("post", "/group-orders"),
        ("post", "/group-orders/{code}/join"),
        ("post", "/group-orders/{code}/participants/{participant_id}/items"),
        ("patch", "/group-orders/{code}/participants/{participant_id}/items/{menu_item_id}"),
        ("delete", "/group-orders/{code}/participants/{participant_id}/items/{menu_item_id}"),
        ("get", "/group-orders/{code}/summary"),
        ("post", "/group-orders/{code}/lock"),
        ("post", "/group-orders/{code}/checkout"),
    }

    actual = {(method, path) for path in paths for method in paths[path] if path.startswith(("/sessions", "/group-orders"))}

    assert actual == expected


def test_the_existing_routes_are_still_there(app):
    paths = app.openapi()["paths"]

    for path in ["/restaurants", "/restaurants/{restaurant_id}/menu", "/orders", "/orders/{order_id}", "/orders/{order_id}/status"]:
        assert path in paths


# ================================================================ end to end


def test_the_whole_flow_session_group_join_items_summary_lock_checkout(api, fake_clock, data_file):
    # create session and group
    host = new_session(api)
    created = api.post("/group-orders", {"restaurant_id": RESTAURANT, "display_name": "Hana"}, token=host)
    assert created.status_code == 201
    code = created.json()["code"]

    # a friend joins with the code
    guest = new_session(api)
    joined = api.post(group_path(code, "/join"), {"display_name": "Bo"}, token=guest)
    assert joined.status_code == 201
    guest_id = joined.json()["participant_id"]

    # both add items (the same item is merged at checkout)
    assert add_item(api, host, code, 1, ITEM_A, 2).status_code == 201
    assert add_item(api, host, code, 1, ITEM_B, 1).status_code == 201
    assert add_item(api, guest, code, guest_id, ITEM_A, 1).status_code == 201

    # the summary
    fake_clock.advance(timedelta(minutes=10))
    summary = api.get(group_path(code, "/summary"), token=guest)
    assert summary.status_code == 200
    entries = summary.json()["participants"]
    assert [e["display_name"] for e in entries] == ["Hana", "Bo"]
    assert [e["subtotal_cents"] for e in entries] == [2 * 899 + 1099, 899]
    assert [e["fee_share_cents"] for e in entries] == [249, 250]
    assert [e["total_cents"] for e in entries] == [2 * 899 + 1099 + 249, 899 + 250]

    # lock, then nobody can change anything
    assert api.post(group_path(code, "/lock"), token=host).json() == {"code": code, "status": "LOCKED"}
    assert_error(add_item(api, guest, code, guest_id, ITEM_B, 1), 409, "ORDER_LOCKED")

    # checkout creates one normal order
    checkout = api.post(group_path(code, "/checkout"), {"address": ADDRESS}, token=host)
    assert checkout.status_code == 201
    order_id = checkout.json()["order_id"]
    expected_total = 3 * 899 + 1099 + 499  # A x3 merged, B x1, plus the delivery fee
    assert checkout.json()["total_cents"] == expected_total
    assert expected_total == sum(e["total_cents"] for e in entries)

    # the order is a normal MiniDash order, readable through the existing route
    order = api.get(f"/orders/{order_id}")
    assert order.status_code == 200
    body = order.json()
    assert body["total_cents"] == expected_total
    assert body["restaurant_id"] == RESTAURANT
    assert body["address"] == ADDRESS
    assert body["status"] == "PLACED"
    assert {(i["menu_item_id"], i["quantity"]) for i in body["items"]} == {(ITEM_A, 3), (ITEM_B, 1)}

    # the group is checked out and cannot be checked out again
    assert api.get(group_path(code, "/summary"), token=host).json()["status"] == "CHECKED_OUT"
    assert_error(api.post(group_path(code, "/checkout"), {"address": ADDRESS}, token=host), 409, "ORDER_CHECKED_OUT")
    assert len(json.loads(data_file.read_text())["orders"]) == 1

    # and the normal order status endpoint works on it
    assert api.patch(f"/orders/{order_id}/status", {"status": "PREPARING"}).status_code == 200


def test_group_orders_survive_restarting_the_app(data_file, fake_clock):
    first = ApiClient(create_app(data_path=data_file, clock=fake_clock))
    group = ready_group(first)

    second = ApiClient(create_app(data_path=data_file, clock=fake_clock))  # a new app on the same file

    summary = second.get(group_path(group.code, "/summary"), token=group.host)
    assert summary.status_code == 200
    assert len(summary.json()["participants"]) == 2
    assert second.post(group_path(group.code, "/lock"), token=group.host).status_code == 200
