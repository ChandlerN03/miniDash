import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.repository.group_orders_repo import GroupOrderRepository
from src.repository.restaurants_repo import RestaurantRepository
from src.services.errors import MiniDashError
from src.services.group_order_service import GroupOrderService
from src.store.file_store import FileStore
from src.store.seed import SEED_DATA

# Far from the real current time, so reading the real clock would show up.
START = datetime(2001, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
TWO_HOURS = timedelta(hours=2)
ONE_SECOND = timedelta(seconds=1)

# Seed data: restaurant 2 has menu items 5-8, restaurant 1 has items 1-4.
RESTAURANT = 2
ITEM_A, ITEM_B, ITEM_C = 5, 6, 7  # on the menu of restaurant 2
OTHER_RESTAURANT_ITEM = 1  # on the menu of restaurant 1 only
UNKNOWN_ITEM = 999

OPS = ["add", "change", "remove"]


class FakeClock:
    def __init__(self, now: datetime = START):
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


@pytest.fixture
def fake_clock():
    return FakeClock()


@pytest.fixture
def repo(data_file):
    store = FileStore(data_file)
    store.initialize(SEED_DATA)
    return GroupOrderRepository(store)


@pytest.fixture
def service(data_file, repo, fake_clock):
    restaurants = RestaurantRepository(FileStore(data_file))
    return GroupOrderService(repo, restaurants, fake_clock)


@pytest.fixture
def scene(service):
    """A group at restaurant 2. Host is participant 1, guest is participant 2.

    The host has item A x2 and the guest has item A x3.
    """
    host = service.create_session()
    code = service.create_group_order(host, RESTAURANT, "Host")["code"]
    guest = service.create_session()
    service.join(guest, code, "Guest")
    service.add_item(host, code, 1, ITEM_A, 2)
    service.add_item(guest, code, 2, ITEM_A, 3)
    return SimpleNamespace(code=code, host=host, guest=guest)


# ---------------------------------------------------------------------- helpers


def do(service, op, token, code, participant_id, menu_item_id, quantity=1):
    """Run add, change or remove with the same arguments."""
    if op == "add":
        return service.add_item(token, code, participant_id, menu_item_id, quantity)
    if op == "change":
        return service.change_item(token, code, participant_id, menu_item_id, quantity)
    return service.remove_item(token, code, participant_id, menu_item_id)


def assert_rejected(code, func, *args):
    with pytest.raises(MiniDashError) as caught:
        func(*args)
    assert caught.value.code == code
    assert isinstance(caught.value.message, str) and caught.value.message


def items_of(repo, code, participant_id=None):
    items = repo.get_group_order(code)["items"]
    if participant_id is None:
        return items
    return [i for i in items if i["participant_id"] == participant_id]


def quantity_of(repo, code, participant_id, menu_item_id):
    for item in items_of(repo, code, participant_id):
        if item["menu_item_id"] == menu_item_id:
            return item["quantity"]
    return None


def set_status(repo, code, status):
    repo.update_group_order(code, lambda group: group.update(status=status))


def add_user(service, code, name) -> str:
    token = service.create_session()
    service.join(token, code, name)
    return token


# ============================================================ R13: adding items


def test_add_item_records_it_under_the_participant(service, repo):
    host = service.create_session()
    code = service.create_group_order(host, RESTAURANT, "Host")["code"]

    service.add_item(host, code, 1, ITEM_A, 2)

    assert items_of(repo, code) == [{"participant_id": 1, "menu_item_id": ITEM_A, "quantity": 2}]


def test_add_item_returns_the_item(service, scene):
    result = service.add_item(scene.guest, scene.code, 2, ITEM_B, 4)

    assert result == {"participant_id": 2, "menu_item_id": ITEM_B, "quantity": 4}


def test_a_guest_can_add_items_under_their_own_participant_id(service, repo, scene):
    service.add_item(scene.guest, scene.code, 2, ITEM_B, 1)

    assert quantity_of(repo, scene.code, 2, ITEM_B) == 1
    assert quantity_of(repo, scene.code, 1, ITEM_B) is None


def test_adding_the_same_item_twice_merges_the_quantity_into_one_record(service, repo):
    host = service.create_session()
    code = service.create_group_order(host, RESTAURANT, "Host")["code"]

    service.add_item(host, code, 1, ITEM_A, 2)
    result = service.add_item(host, code, 1, ITEM_A, 3)

    assert result["quantity"] == 5
    assert items_of(repo, code) == [{"participant_id": 1, "menu_item_id": ITEM_A, "quantity": 5}]


def test_the_same_menu_item_for_two_participants_is_two_separate_records(repo, scene):
    assert quantity_of(repo, scene.code, 1, ITEM_A) == 2
    assert quantity_of(repo, scene.code, 2, ITEM_A) == 3
    assert len(items_of(repo, scene.code)) == 2


def test_different_menu_items_for_one_participant_are_separate_records(service, repo, scene):
    service.add_item(scene.host, scene.code, 1, ITEM_B, 1)
    service.add_item(scene.host, scene.code, 1, ITEM_C, 4)

    assert {(i["menu_item_id"], i["quantity"]) for i in items_of(repo, scene.code, 1)} == {
        (ITEM_A, 2),
        (ITEM_B, 1),
        (ITEM_C, 4),
    }


def test_add_does_not_change_status_host_or_participants(service, repo, scene):
    before = repo.get_group_order(scene.code)

    service.add_item(scene.host, scene.code, 1, ITEM_B, 1)

    after = repo.get_group_order(scene.code)
    assert after["status"] == "OPEN"
    assert after["host_token"] == before["host_token"]
    assert after["participants"] == before["participants"]


# =========================================================== R14: the quantity


@pytest.mark.parametrize("quantity", [1, 5, 9])
def test_quantities_1_to_9_are_accepted(service, repo, quantity):
    host = service.create_session()
    code = service.create_group_order(host, RESTAURANT, "Host")["code"]

    service.add_item(host, code, 1, ITEM_A, quantity)

    assert quantity_of(repo, code, 1, ITEM_A) == quantity


@pytest.mark.parametrize("quantity", [0, 10, -1, 100, 1.5, "2", None, True])
def test_add_rejects_a_quantity_that_is_not_a_whole_number_from_1_to_9(service, repo, quantity):
    host = service.create_session()
    code = service.create_group_order(host, RESTAURANT, "Host")["code"]

    assert_rejected("INVALID_QUANTITY", service.add_item, host, code, 1, ITEM_A, quantity)

    assert items_of(repo, code) == []


def test_8_then_2_is_a_total_of_10_and_is_rejected_leaving_8(service, repo):
    host = service.create_session()
    code = service.create_group_order(host, RESTAURANT, "Host")["code"]
    service.add_item(host, code, 1, ITEM_A, 8)

    assert_rejected("INVALID_QUANTITY", service.add_item, host, code, 1, ITEM_A, 2)

    assert quantity_of(repo, code, 1, ITEM_A) == 8


def test_8_then_1_is_a_total_of_9_and_is_accepted(service, repo):
    host = service.create_session()
    code = service.create_group_order(host, RESTAURANT, "Host")["code"]
    service.add_item(host, code, 1, ITEM_A, 8)

    service.add_item(host, code, 1, ITEM_A, 1)

    assert quantity_of(repo, code, 1, ITEM_A) == 9


def test_9_then_1_is_rejected(service, repo):
    host = service.create_session()
    code = service.create_group_order(host, RESTAURANT, "Host")["code"]
    service.add_item(host, code, 1, ITEM_A, 9)

    assert_rejected("INVALID_QUANTITY", service.add_item, host, code, 1, ITEM_A, 1)

    assert quantity_of(repo, code, 1, ITEM_A) == 9


def test_the_limit_of_9_is_per_participant_and_item_not_for_the_whole_group(service, repo, scene):
    service.add_item(scene.host, scene.code, 1, ITEM_B, 9)
    service.add_item(scene.guest, scene.code, 2, ITEM_B, 9)

    assert quantity_of(repo, scene.code, 1, ITEM_B) == 9
    assert quantity_of(repo, scene.code, 2, ITEM_B) == 9


@pytest.mark.parametrize("quantity", [1, 5, 9])
def test_change_sets_the_quantity_to_a_value_from_1_to_9(service, repo, scene, quantity):
    service.change_item(scene.guest, scene.code, 2, ITEM_A, quantity)

    assert quantity_of(repo, scene.code, 2, ITEM_A) == quantity


@pytest.mark.parametrize("quantity", [0, 10, -1, 1.5, "2", None, True])
def test_change_rejects_a_quantity_that_is_not_a_whole_number_from_1_to_9(service, repo, scene, quantity):
    assert_rejected("INVALID_QUANTITY", service.change_item, scene.guest, scene.code, 2, ITEM_A, quantity)

    assert quantity_of(repo, scene.code, 2, ITEM_A) == 3


# ====================================================== R15: item on the menu


def test_item_from_another_restaurant_gives_item_not_on_menu(service, repo):
    host = service.create_session()
    code = service.create_group_order(host, RESTAURANT, "Host")["code"]

    assert_rejected("ITEM_NOT_ON_MENU", service.add_item, host, code, 1, OTHER_RESTAURANT_ITEM, 1)

    assert items_of(repo, code) == []


def test_unknown_menu_item_gives_item_not_on_menu(service, repo):
    host = service.create_session()
    code = service.create_group_order(host, RESTAURANT, "Host")["code"]

    assert_rejected("ITEM_NOT_ON_MENU", service.add_item, host, code, 1, UNKNOWN_ITEM, 1)

    assert items_of(repo, code) == []


@pytest.mark.parametrize("op", ["change", "remove"])
def test_change_or_remove_of_an_item_not_on_the_menu_gives_item_not_on_menu(service, scene, op):
    assert_rejected("ITEM_NOT_ON_MENU", do, service, op, scene.guest, scene.code, 2, OTHER_RESTAURANT_ITEM, 1)


def test_the_menu_is_that_of_the_groups_restaurant(service, repo):
    host = service.create_session()
    code = service.create_group_order(host, 1, "Host")["code"]  # restaurant 1

    service.add_item(host, code, 1, OTHER_RESTAURANT_ITEM, 1)  # item 1 is on restaurant 1's menu
    assert_rejected("ITEM_NOT_ON_MENU", service.add_item, host, code, 1, ITEM_A, 1)  # item 5 is not

    assert quantity_of(repo, code, 1, OTHER_RESTAURANT_ITEM) == 1


# ===================================================== R16: change and remove


def test_change_item_sets_the_new_quantity_and_returns_the_item(service, repo, scene):
    result = service.change_item(scene.guest, scene.code, 2, ITEM_A, 7)

    assert result == {"participant_id": 2, "menu_item_id": ITEM_A, "quantity": 7}
    assert quantity_of(repo, scene.code, 2, ITEM_A) == 7


def test_change_item_changes_only_that_item(service, repo, scene):
    service.add_item(scene.guest, scene.code, 2, ITEM_B, 4)
    before = repo.get_group_order(scene.code)

    service.change_item(scene.guest, scene.code, 2, ITEM_A, 8)

    after = repo.get_group_order(scene.code)
    assert quantity_of(repo, scene.code, 2, ITEM_A) == 8
    assert quantity_of(repo, scene.code, 2, ITEM_B) == 4  # same participant, other item
    assert quantity_of(repo, scene.code, 1, ITEM_A) == 2  # same item, other participant
    assert after["participants"] == before["participants"]
    assert after["status"] == before["status"]
    assert len(after["items"]) == len(before["items"])


def test_change_item_keeps_the_order_of_the_items(service, repo, scene):
    service.add_item(scene.host, scene.code, 1, ITEM_B, 1)
    order_before = [(i["participant_id"], i["menu_item_id"]) for i in items_of(repo, scene.code)]

    service.change_item(scene.host, scene.code, 1, ITEM_A, 9)

    order_after = [(i["participant_id"], i["menu_item_id"]) for i in items_of(repo, scene.code)]
    assert order_after == order_before


def test_remove_item_removes_only_that_item(service, repo, scene):
    service.add_item(scene.guest, scene.code, 2, ITEM_B, 4)

    result = service.remove_item(scene.guest, scene.code, 2, ITEM_A)

    assert result is None
    assert quantity_of(repo, scene.code, 2, ITEM_A) is None
    assert quantity_of(repo, scene.code, 2, ITEM_B) == 4  # same participant, other item
    assert quantity_of(repo, scene.code, 1, ITEM_A) == 2  # same item, other participant


def test_a_participant_can_remove_all_their_items(service, repo, scene):
    service.remove_item(scene.guest, scene.code, 2, ITEM_A)

    assert items_of(repo, scene.code, 2) == []
    assert len(repo.get_group_order(scene.code)["participants"]) == 2  # still a participant


def test_a_removed_item_can_be_added_again_from_scratch(service, repo, scene):
    service.remove_item(scene.guest, scene.code, 2, ITEM_A)

    service.add_item(scene.guest, scene.code, 2, ITEM_A, 1)

    assert quantity_of(repo, scene.code, 2, ITEM_A) == 1  # not 3 + 1


@pytest.mark.parametrize("op", ["change", "remove"])
def test_change_or_remove_of_an_item_the_participant_does_not_have(service, repo, scene, op):
    before = repo.get_group_order(scene.code)

    assert_rejected("ITEM_NOT_IN_ORDER", do, service, op, scene.guest, scene.code, 2, ITEM_B, 2)

    assert repo.get_group_order(scene.code) == before


# ===================================================== R17: other people's items


@pytest.mark.parametrize("op", OPS)
def test_acting_for_another_participant_gives_not_allowed_and_changes_nothing(service, repo, fake_clock, scene, op):
    fake_clock.advance(timedelta(minutes=10))
    before = repo.get_group_order(scene.code)

    # The guest (participant 2) tries to act on the host's items (participant 1).
    assert_rejected("NOT_ALLOWED", do, service, op, scene.guest, scene.code, 1, ITEM_A, 5)

    assert repo.get_group_order(scene.code) == before


def test_the_other_participants_item_keeps_its_quantity(service, repo, scene):
    assert_rejected("NOT_ALLOWED", service.change_item, scene.guest, scene.code, 1, ITEM_A, 9)
    assert_rejected("NOT_ALLOWED", service.remove_item, scene.guest, scene.code, 1, ITEM_A)

    assert quantity_of(repo, scene.code, 1, ITEM_A) == 2


@pytest.mark.parametrize("op", OPS)
def test_a_participant_id_that_does_not_exist_gives_not_allowed(service, repo, scene, op):
    before = repo.get_group_order(scene.code)

    assert_rejected("NOT_ALLOWED", do, service, op, scene.guest, scene.code, 99, ITEM_A, 1)

    assert repo.get_group_order(scene.code) == before


@pytest.mark.parametrize("op", OPS)
def test_a_user_who_never_joined_gets_not_allowed(service, repo, scene, op):
    outsider = service.create_session()  # valid session, but not in this group
    before = repo.get_group_order(scene.code)

    assert_rejected("NOT_ALLOWED", do, service, op, outsider, scene.code, 1, ITEM_A, 1)
    assert_rejected("NOT_ALLOWED", do, service, op, outsider, scene.code, 2, ITEM_A, 1)

    assert repo.get_group_order(scene.code) == before


# ================================================================= R2: session


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("token", [None, "", "never-issued"])
def test_a_missing_or_unknown_session_gives_invalid_session(service, repo, scene, op, token):
    before = repo.get_group_order(scene.code)

    assert_rejected("INVALID_SESSION", do, service, op, token, scene.code, 1, ITEM_A, 1)

    assert repo.get_group_order(scene.code) == before


# ========================================================= R9-style: wrong code


@pytest.mark.parametrize("op", OPS)
def test_a_wrong_code_gives_invalid_code(service, scene, op):
    assert_rejected("INVALID_CODE", do, service, op, scene.guest, "nope42", 2, ITEM_A, 1)


# ============================================== R28: locked, and checked out


@pytest.mark.parametrize("op", OPS)
def test_items_cannot_change_while_locked(service, repo, fake_clock, scene, op):
    set_status(repo, scene.code, "LOCKED")
    fake_clock.advance(timedelta(minutes=10))
    before = repo.get_group_order(scene.code)

    assert_rejected("ORDER_LOCKED", do, service, op, scene.guest, scene.code, 2, ITEM_A, 5)

    assert repo.get_group_order(scene.code) == before


@pytest.mark.parametrize("op", OPS)
def test_items_cannot_change_once_checked_out(service, repo, fake_clock, scene, op):
    set_status(repo, scene.code, "CHECKED_OUT")
    fake_clock.advance(timedelta(minutes=10))
    before = repo.get_group_order(scene.code)

    assert_rejected("ORDER_CHECKED_OUT", do, service, op, scene.guest, scene.code, 2, ITEM_A, 5)

    assert repo.get_group_order(scene.code) == before


def test_items_can_change_again_after_the_group_is_back_to_open(service, repo, scene):
    set_status(repo, scene.code, "LOCKED")
    assert_rejected("ORDER_LOCKED", service.change_item, scene.guest, scene.code, 2, ITEM_A, 5)

    set_status(repo, scene.code, "OPEN")  # as if the host unlocked it
    service.change_item(scene.guest, scene.code, 2, ITEM_A, 5)

    assert quantity_of(repo, scene.code, 2, ITEM_A) == 5


# ===================================================== R31, R32: expiry on items


@pytest.mark.parametrize("op", OPS)
def test_at_exactly_2_hours_the_item_request_gives_order_expired_and_saves_expired(
    service, repo, fake_clock, scene, op
):
    before = repo.get_group_order(scene.code)
    fake_clock.advance(TWO_HOURS)

    assert_rejected("ORDER_EXPIRED", do, service, op, scene.guest, scene.code, 2, ITEM_A, 5)

    after = repo.get_group_order(scene.code)
    assert after["status"] == "EXPIRED"  # saved even though the request was rejected
    assert after == {**before, "status": "EXPIRED"}  # nothing else changed


@pytest.mark.parametrize("op", OPS)
def test_at_1_59_59_the_item_request_still_works(service, repo, fake_clock, scene, op):
    fake_clock.advance(TWO_HOURS - ONE_SECOND)

    do(service, op, scene.guest, scene.code, 2, ITEM_A, 4)

    assert repo.get_group_order(scene.code)["status"] == "OPEN"


@pytest.mark.parametrize("op", OPS)
def test_an_already_expired_group_keeps_rejecting_item_requests(service, repo, scene, op):
    set_status(repo, scene.code, "EXPIRED")

    assert_rejected("ORDER_EXPIRED", do, service, op, scene.guest, scene.code, 2, ITEM_A, 4)

    assert quantity_of(repo, scene.code, 2, ITEM_A) == 3


def test_a_locked_group_can_expire_when_an_item_change_is_attempted(service, repo, fake_clock, scene):
    set_status(repo, scene.code, "LOCKED")
    fake_clock.advance(TWO_HOURS)

    assert_rejected("ORDER_EXPIRED", service.add_item, scene.guest, scene.code, 2, ITEM_B, 1)

    assert repo.get_group_order(scene.code)["status"] == "EXPIRED"


def test_a_checked_out_group_never_expires_on_item_requests(service, repo, fake_clock, scene):
    set_status(repo, scene.code, "CHECKED_OUT")
    fake_clock.advance(timedelta(days=30))

    assert_rejected("ORDER_CHECKED_OUT", service.add_item, scene.guest, scene.code, 2, ITEM_B, 1)

    assert repo.get_group_order(scene.code)["status"] == "CHECKED_OUT"


def test_expiry_is_applied_before_not_allowed_and_before_quantity_checks(service, fake_clock, scene):
    fake_clock.advance(TWO_HOURS)

    # Wrong participant_id and a bad quantity, but the group has expired first.
    assert_rejected("ORDER_EXPIRED", service.add_item, scene.guest, scene.code, 1, ITEM_A, 0)


# ===================================================== R30: what counts as activity


@pytest.mark.parametrize("op", OPS)
def test_a_successful_item_request_moves_last_activity(service, repo, fake_clock, scene, op):
    before = repo.get_group_order(scene.code)["last_activity_at"]
    fake_clock.advance(timedelta(hours=1))

    do(service, op, scene.guest, scene.code, 2, ITEM_A, 4)

    after = repo.get_group_order(scene.code)["last_activity_at"]
    assert after != before
    assert after == fake_clock.now().isoformat()


@pytest.mark.parametrize("op", OPS)
def test_a_successful_item_request_restarts_the_2_hour_countdown(service, repo, fake_clock, scene, op):
    fake_clock.advance(timedelta(hours=1, minutes=30))
    do(service, op, scene.guest, scene.code, 2, ITEM_A, 4)  # activity at 1:30

    fake_clock.advance(TWO_HOURS - ONE_SECOND)  # 1:59:59 after that, 3:29:59 after creation
    service.add_item(scene.host, scene.code, 1, ITEM_B, 1)  # still works

    assert repo.get_group_order(scene.code)["status"] == "OPEN"


@pytest.mark.parametrize("op", OPS)
def test_exactly_2_hours_after_a_successful_item_request_the_group_expires(service, repo, fake_clock, scene, op):
    fake_clock.advance(timedelta(hours=1))
    do(service, op, scene.guest, scene.code, 2, ITEM_A, 4)

    fake_clock.advance(TWO_HOURS)

    assert_rejected("ORDER_EXPIRED", service.add_item, scene.host, scene.code, 1, ITEM_B, 1)
    assert repo.get_group_order(scene.code)["status"] == "EXPIRED"


REJECTIONS = [
    pytest.param("add", dict(menu_item_id=ITEM_A, quantity=0), "INVALID_QUANTITY", id="add-invalid-quantity"),
    pytest.param("add", dict(menu_item_id=ITEM_A, quantity=7), "INVALID_QUANTITY", id="add-total-above-9"),
    pytest.param("add", dict(menu_item_id=UNKNOWN_ITEM, quantity=1), "ITEM_NOT_ON_MENU", id="add-not-on-menu"),
    pytest.param("change", dict(menu_item_id=ITEM_A, quantity=10), "INVALID_QUANTITY", id="change-invalid-quantity"),
    pytest.param("change", dict(menu_item_id=ITEM_B, quantity=2), "ITEM_NOT_IN_ORDER", id="change-not-in-order"),
    pytest.param("remove", dict(menu_item_id=ITEM_B, quantity=1), "ITEM_NOT_IN_ORDER", id="remove-not-in-order"),
]


@pytest.mark.parametrize(("op", "args", "error"), REJECTIONS)
def test_a_rejected_item_request_changes_nothing_and_does_not_move_last_activity(
    service, repo, fake_clock, scene, op, args, error
):
    # The guest already has item A x3. Make the "total above 9" case real.
    service.add_item(scene.guest, scene.code, 2, ITEM_A, 3)  # now x6; adding 7 more would pass 9
    fake_clock.advance(timedelta(minutes=45))
    before = repo.get_group_order(scene.code)

    assert_rejected(error, do, service, op, scene.guest, scene.code, 2, args["menu_item_id"], args["quantity"])

    assert repo.get_group_order(scene.code) == before  # includes last_activity_at


def test_a_rejected_request_does_not_restart_the_countdown(service, repo, fake_clock, scene):
    fake_clock.advance(timedelta(hours=1))
    assert_rejected("INVALID_QUANTITY", service.add_item, scene.guest, scene.code, 2, ITEM_A, 0)
    assert_rejected("NOT_ALLOWED", service.remove_item, scene.guest, scene.code, 1, ITEM_A)

    fake_clock.advance(timedelta(hours=1))  # exactly 2:00:00 since the scene was set up

    assert_rejected("ORDER_EXPIRED", service.add_item, scene.guest, scene.code, 2, ITEM_B, 1)


# ====================================================== the order of the checks


def test_invalid_session_comes_before_invalid_code(service):
    assert_rejected("INVALID_SESSION", service.add_item, "never-issued", "nope42", 1, ITEM_A, 1)


def test_invalid_code_comes_before_not_allowed(service):
    outsider = service.create_session()

    assert_rejected("INVALID_CODE", service.add_item, outsider, "nope42", 99, UNKNOWN_ITEM, 0)


def test_checked_out_comes_before_not_allowed_quantity_and_menu_checks(service, repo, scene):
    set_status(repo, scene.code, "CHECKED_OUT")

    assert_rejected("ORDER_CHECKED_OUT", service.add_item, scene.guest, scene.code, 1, UNKNOWN_ITEM, 0)


def test_locked_comes_before_not_allowed(service, repo, scene):
    set_status(repo, scene.code, "LOCKED")

    assert_rejected("ORDER_LOCKED", service.add_item, scene.guest, scene.code, 1, ITEM_A, 1)


def test_not_allowed_comes_before_invalid_quantity(service, scene):
    assert_rejected("NOT_ALLOWED", service.add_item, scene.guest, scene.code, 1, ITEM_A, 0)


def test_invalid_quantity_comes_before_item_not_on_menu(service, scene):
    assert_rejected("INVALID_QUANTITY", service.add_item, scene.guest, scene.code, 2, OTHER_RESTAURANT_ITEM, 0)
    assert_rejected("INVALID_QUANTITY", service.change_item, scene.guest, scene.code, 2, UNKNOWN_ITEM, 10)


def test_item_not_on_menu_comes_before_item_not_in_order(service, scene):
    assert_rejected("ITEM_NOT_ON_MENU", service.change_item, scene.guest, scene.code, 2, UNKNOWN_ITEM, 2)
    assert_rejected("ITEM_NOT_ON_MENU", service.remove_item, scene.guest, scene.code, 2, UNKNOWN_ITEM)


# ============================================== simultaneous requests (no lost updates)


def run_at_the_same_time(jobs):
    """Run each callable in its own thread at the same moment. Returns (results, error codes)."""
    barrier = threading.Barrier(len(jobs))
    results, rejected = [], []

    def go(job):
        barrier.wait()
        try:
            results.append(job())
        except MiniDashError as error:
            rejected.append(error.code)

    threads = [threading.Thread(target=go, args=(job,)) for job in jobs]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results, rejected


def test_simultaneous_adds_of_one_item_by_one_participant_are_all_counted(service, repo, scene):
    jobs = [lambda: service.add_item(scene.host, scene.code, 1, ITEM_B, 1) for _ in range(9)]

    results, rejected = run_at_the_same_time(jobs)

    assert rejected == []
    assert quantity_of(repo, scene.code, 1, ITEM_B) == 9
    assert sum(1 for i in items_of(repo, scene.code, 1) if i["menu_item_id"] == ITEM_B) == 1


def test_simultaneous_adds_can_never_push_a_quantity_over_9(service, repo, scene):
    jobs = [lambda: service.add_item(scene.host, scene.code, 1, ITEM_B, 1) for _ in range(14)]

    results, rejected = run_at_the_same_time(jobs)

    assert quantity_of(repo, scene.code, 1, ITEM_B) == 9
    assert len(results) == 9
    assert rejected == ["INVALID_QUANTITY"] * 5


def test_simultaneous_adds_by_different_participants_are_all_stored(service, repo, scene):
    others = [add_user(service, scene.code, f"Guest {n}") for n in range(3, 8)]  # participants 3-7
    jobs = [
        (lambda t=t, pid=pid: service.add_item(t, scene.code, pid, ITEM_C, 2))
        for pid, t in enumerate(others, start=3)
    ]

    _, rejected = run_at_the_same_time(jobs)

    assert rejected == []
    for pid in range(3, 8):
        assert quantity_of(repo, scene.code, pid, ITEM_C) == 2
    assert quantity_of(repo, scene.code, 1, ITEM_A) == 2  # earlier items untouched
    assert quantity_of(repo, scene.code, 2, ITEM_A) == 3


def test_simultaneous_item_requests_after_the_deadline_all_get_order_expired(service, repo, fake_clock, scene):
    fake_clock.advance(TWO_HOURS)
    jobs = [lambda: service.add_item(scene.guest, scene.code, 2, ITEM_B, 1) for _ in range(6)]

    results, rejected = run_at_the_same_time(jobs)

    assert results == []
    assert rejected == ["ORDER_EXPIRED"] * 6
    assert repo.get_group_order(scene.code)["status"] == "EXPIRED"
    assert quantity_of(repo, scene.code, 2, ITEM_B) is None


# ================================================================ injected clock


def test_item_requests_use_only_the_injected_clock(service, repo, fake_clock, scene):
    service.add_item(scene.host, scene.code, 1, ITEM_B, 1)
    service.change_item(scene.host, scene.code, 1, ITEM_B, 2)
    service.remove_item(scene.host, scene.code, 1, ITEM_B)

    # The fake clock is in 2001, so a timestamp from the real clock would not match.
    assert repo.get_group_order(scene.code)["last_activity_at"] == START.isoformat()


# ============================================ R18: the host can remove anyone's item


def test_the_host_can_remove_another_participants_item(service, repo, scene):
    result = service.remove_item(scene.host, scene.code, 2, ITEM_A)  # host removes the guest's item

    assert result is None
    assert quantity_of(repo, scene.code, 2, ITEM_A) is None


def test_host_removal_removes_only_that_item(service, repo, scene):
    service.add_item(scene.guest, scene.code, 2, ITEM_B, 4)

    service.remove_item(scene.host, scene.code, 2, ITEM_A)

    assert quantity_of(repo, scene.code, 2, ITEM_A) is None
    assert quantity_of(repo, scene.code, 2, ITEM_B) == 4  # same participant, other item
    assert quantity_of(repo, scene.code, 1, ITEM_A) == 2  # same item, the host's own copy


def test_host_removal_leaves_the_participant_in_the_group(service, repo, scene):
    service.remove_item(scene.host, scene.code, 2, ITEM_A)

    participants = repo.get_group_order(scene.code)["participants"]
    assert [p["participant_id"] for p in participants] == [1, 2]
    assert items_of(repo, scene.code, 2) == []


def test_the_host_can_remove_items_of_each_participant(service, repo, scene):
    third = add_user(service, scene.code, "Third")
    service.add_item(third, scene.code, 3, ITEM_C, 2)

    service.remove_item(scene.host, scene.code, 2, ITEM_A)
    service.remove_item(scene.host, scene.code, 3, ITEM_C)

    assert items_of(repo, scene.code, 2) == []
    assert items_of(repo, scene.code, 3) == []
    assert quantity_of(repo, scene.code, 1, ITEM_A) == 2


def test_the_host_can_still_remove_their_own_items(service, repo, scene):
    service.remove_item(scene.host, scene.code, 1, ITEM_A)

    assert items_of(repo, scene.code, 1) == []
    assert quantity_of(repo, scene.code, 2, ITEM_A) == 3


def test_a_removed_item_can_be_added_again_by_its_owner(service, repo, scene):
    service.remove_item(scene.host, scene.code, 2, ITEM_A)

    service.add_item(scene.guest, scene.code, 2, ITEM_A, 1)

    assert quantity_of(repo, scene.code, 2, ITEM_A) == 1  # not 3 + 1


def test_a_participant_who_is_not_the_host_still_cannot_remove_the_hosts_item(service, repo, scene):
    assert_rejected("NOT_ALLOWED", service.remove_item, scene.guest, scene.code, 1, ITEM_A)

    assert quantity_of(repo, scene.code, 1, ITEM_A) == 2


def test_a_guest_cannot_remove_another_guests_item(service, repo, scene):
    third = add_user(service, scene.code, "Third")
    service.add_item(third, scene.code, 3, ITEM_C, 2)

    assert_rejected("NOT_ALLOWED", service.remove_item, scene.guest, scene.code, 3, ITEM_C)
    assert_rejected("NOT_ALLOWED", service.remove_item, third, scene.code, 2, ITEM_A)

    assert quantity_of(repo, scene.code, 3, ITEM_C) == 2
    assert quantity_of(repo, scene.code, 2, ITEM_A) == 3


def test_the_host_is_the_person_in_host_token_not_just_participant_1(service, repo, scene):
    repo.update_group_order(scene.code, lambda group: group.update(host_token=scene.guest))

    # The guest is now the host and can remove participant 1's item ...
    service.remove_item(scene.guest, scene.code, 1, ITEM_A)
    assert items_of(repo, scene.code, 1) == []

    # ... and the person who was host (participant 1) cannot remove the guest's item.
    assert_rejected("NOT_ALLOWED", service.remove_item, scene.host, scene.code, 2, ITEM_A)
    assert quantity_of(repo, scene.code, 2, ITEM_A) == 3


# --- the host's extra right is removal only: adding and changing stay own-items-only


def test_the_host_cannot_add_an_item_for_another_participant(service, repo, fake_clock, scene):
    fake_clock.advance(timedelta(minutes=10))
    before = repo.get_group_order(scene.code)

    assert_rejected("NOT_ALLOWED", service.add_item, scene.host, scene.code, 2, ITEM_B, 1)

    assert repo.get_group_order(scene.code) == before


@pytest.mark.parametrize("quantity", [1, 5, 9])
def test_the_host_cannot_change_another_participants_quantity(service, repo, fake_clock, scene, quantity):
    fake_clock.advance(timedelta(minutes=10))
    before = repo.get_group_order(scene.code)

    assert_rejected("NOT_ALLOWED", service.change_item, scene.host, scene.code, 2, ITEM_A, quantity)

    assert repo.get_group_order(scene.code) == before


def test_host_cannot_add_or_change_for_a_participant_who_does_not_exist(service, scene):
    assert_rejected("NOT_ALLOWED", service.add_item, scene.host, scene.code, 99, ITEM_A, 1)
    assert_rejected("NOT_ALLOWED", service.change_item, scene.host, scene.code, 99, ITEM_A, 1)


# --- the normal rules still apply to a host removal


def test_host_removal_for_a_participant_who_does_not_exist_gives_not_allowed(service, repo, scene):
    before = repo.get_group_order(scene.code)

    assert_rejected("NOT_ALLOWED", service.remove_item, scene.host, scene.code, 99, ITEM_A)

    assert repo.get_group_order(scene.code) == before


def test_host_removal_of_an_item_the_participant_does_not_have(service, repo, fake_clock, scene):
    fake_clock.advance(timedelta(minutes=10))
    before = repo.get_group_order(scene.code)

    assert_rejected("ITEM_NOT_IN_ORDER", service.remove_item, scene.host, scene.code, 2, ITEM_B)

    assert repo.get_group_order(scene.code) == before


def test_host_removal_of_an_item_not_on_the_menu(service, scene):
    assert_rejected("ITEM_NOT_ON_MENU", service.remove_item, scene.host, scene.code, 2, OTHER_RESTAURANT_ITEM)


def test_host_removal_is_rejected_while_locked(service, repo, fake_clock, scene):
    set_status(repo, scene.code, "LOCKED")
    fake_clock.advance(timedelta(minutes=10))
    before = repo.get_group_order(scene.code)

    assert_rejected("ORDER_LOCKED", service.remove_item, scene.host, scene.code, 2, ITEM_A)

    assert repo.get_group_order(scene.code) == before


def test_host_removal_is_rejected_once_checked_out(service, repo, scene):
    set_status(repo, scene.code, "CHECKED_OUT")

    assert_rejected("ORDER_CHECKED_OUT", service.remove_item, scene.host, scene.code, 2, ITEM_A)

    assert quantity_of(repo, scene.code, 2, ITEM_A) == 3


def test_host_removal_after_2_hours_gives_order_expired_and_saves_expired(service, repo, fake_clock, scene):
    before = repo.get_group_order(scene.code)
    fake_clock.advance(TWO_HOURS)

    assert_rejected("ORDER_EXPIRED", service.remove_item, scene.host, scene.code, 2, ITEM_A)

    assert repo.get_group_order(scene.code) == {**before, "status": "EXPIRED"}


def test_host_removal_at_1_59_59_still_works(service, repo, fake_clock, scene):
    fake_clock.advance(TWO_HOURS - ONE_SECOND)

    service.remove_item(scene.host, scene.code, 2, ITEM_A)

    assert quantity_of(repo, scene.code, 2, ITEM_A) is None


@pytest.mark.parametrize("token", [None, "", "never-issued"])
def test_host_removal_needs_a_valid_session(service, repo, scene, token):
    assert_rejected("INVALID_SESSION", service.remove_item, token, scene.code, 2, ITEM_A)

    assert quantity_of(repo, scene.code, 2, ITEM_A) == 3


def test_host_removal_with_a_wrong_code_gives_invalid_code(service, scene):
    assert_rejected("INVALID_CODE", service.remove_item, scene.host, "nope42", 2, ITEM_A)


# --- activity (R30)


def test_a_successful_host_removal_counts_as_activity(service, repo, fake_clock, scene):
    fake_clock.advance(timedelta(hours=1))

    service.remove_item(scene.host, scene.code, 2, ITEM_A)

    assert repo.get_group_order(scene.code)["last_activity_at"] == fake_clock.now().isoformat()


def test_a_successful_host_removal_restarts_the_2_hour_countdown(service, repo, fake_clock, scene):
    fake_clock.advance(timedelta(hours=1, minutes=30))
    service.remove_item(scene.host, scene.code, 2, ITEM_A)  # activity at 1:30

    fake_clock.advance(TWO_HOURS - ONE_SECOND)
    service.add_item(scene.host, scene.code, 1, ITEM_B, 1)  # still works

    assert repo.get_group_order(scene.code)["status"] == "OPEN"


def test_a_rejected_host_action_does_not_move_last_activity(service, repo, fake_clock, scene):
    fake_clock.advance(timedelta(minutes=45))
    before = repo.get_group_order(scene.code)

    assert_rejected("NOT_ALLOWED", service.add_item, scene.host, scene.code, 2, ITEM_B, 1)
    assert_rejected("ITEM_NOT_IN_ORDER", service.remove_item, scene.host, scene.code, 2, ITEM_B)

    assert repo.get_group_order(scene.code)["last_activity_at"] == before["last_activity_at"]


def test_simultaneous_host_removal_and_owner_change_never_lose_the_other_guests_items(service, repo, scene):
    third = add_user(service, scene.code, "Third")
    service.add_item(third, scene.code, 3, ITEM_C, 2)
    jobs = [
        lambda: service.remove_item(scene.host, scene.code, 2, ITEM_A),
        lambda: service.add_item(third, scene.code, 3, ITEM_B, 1),
        lambda: service.add_item(scene.host, scene.code, 1, ITEM_B, 1),
    ]

    _, rejected = run_at_the_same_time(jobs)

    assert rejected == []
    assert quantity_of(repo, scene.code, 2, ITEM_A) is None
    assert quantity_of(repo, scene.code, 3, ITEM_C) == 2
    assert quantity_of(repo, scene.code, 3, ITEM_B) == 1
    assert quantity_of(repo, scene.code, 1, ITEM_B) == 1
