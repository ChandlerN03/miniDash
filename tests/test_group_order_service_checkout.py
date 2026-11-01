import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

from src.repository.group_orders_repo import GroupOrderRepository
from src.repository.orders_repo import OrderRepository
from src.repository.restaurants_repo import RestaurantRepository
from src.services.errors import MiniDashError
from src.services.group_order_service import DELIVERY_FEE_CENTS, GroupOrderService
from src.services.order_service import OrderService
from src.store.file_store import FileStore
from src.store.seed import SEED_DATA

# Far from the real current time, so reading the real clock would show up.
# 12:00:00 UTC is exactly when restaurant 2 opens (12:00 to 21:30).
START = datetime(2001, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
TWO_HOURS = timedelta(hours=2)
ONE_SECOND = timedelta(seconds=1)

ADDRESS = "12 Elm Street"

# Seed data. Restaurant 2 (12:00-21:30): items 5-8. Restaurant 1 (11:00-22:00): items 1-4.
RESTAURANT = 2
ITEM_A, ITEM_B, ITEM_C = 5, 6, 7
PRICE = {m["id"]: m["price_cents"] for m in SEED_DATA["menu_items"]}  # A=899, B=1099, C=399


class FakeClock:
    def __init__(self, now: datetime = START):
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta

    def set(self, now: datetime) -> None:
        self._now = now


def at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2001, 1, 1, hour, minute, second, tzinfo=timezone.utc)


@pytest.fixture
def fake_clock():
    return FakeClock()


@pytest.fixture
def store(data_file):
    file_store = FileStore(data_file)
    file_store.initialize(SEED_DATA)
    return file_store


@pytest.fixture
def repo(store):
    return GroupOrderRepository(store)


@pytest.fixture
def orders(store, fake_clock):
    # The same store as the groups, as in the real app, so checkout is one atomic step.
    return OrderService(OrderRepository(store), RestaurantRepository(store), fake_clock)


@pytest.fixture
def service(store, repo, orders, fake_clock):
    return GroupOrderService(repo, RestaurantRepository(store), fake_clock, orders=orders)


# ---------------------------------------------------------------------- helpers


def make_locked(service, specs=None, restaurant=RESTAURANT):
    """A LOCKED group. `specs` lists each participant's items as (menu_item_id, quantity).

    Default: the host has item A x2 and a guest has item B x1.
    Returns (code, tokens); tokens[0] is the host and participant ids are 1, 2, 3, ...
    """
    specs = specs or [[(ITEM_A, 2)], [(ITEM_B, 1)]]
    host = service.create_session()
    code = service.create_group_order(host, restaurant, "Host")["code"]
    tokens = [host]
    for name in ["Bo", "Cy", "Di", "Ed"][: len(specs) - 1]:
        token = service.create_session()
        service.join(token, code, name)
        tokens.append(token)
    for participant_id, (token, items) in enumerate(zip(tokens, specs), start=1):
        for menu_item_id, quantity in items:
            service.add_item(token, code, participant_id, menu_item_id, quantity)
    service.lock(tokens[0], code)
    return code, tokens


def make_open(service, restaurant=RESTAURANT):
    host = service.create_session()
    code = service.create_group_order(host, restaurant, "Host")["code"]
    service.add_item(host, code, 1, ITEM_A, 1)
    return code, [host]


def assert_rejected(code, func, *args):
    with pytest.raises(MiniDashError) as caught:
        func(*args)
    assert caught.value.code == code
    assert isinstance(caught.value.message, str) and caught.value.message


def read_file(data_file) -> dict:
    return json.loads(data_file.read_text())


def orders_in_file(data_file) -> list[dict]:
    return read_file(data_file)["orders"]


def lines_of(order) -> set[tuple[int, int, int]]:
    return {(i["menu_item_id"], i["quantity"], i["unit_price_cents"]) for i in order["items"]}


def set_status(repo, code, status):
    repo.update_group_order(code, lambda group: group.update(status=status))


def run_at_the_same_time(jobs):
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


# ====================================================== R36: a successful checkout


def test_checkout_creates_exactly_one_order(service, data_file):
    code, tokens = make_locked(service)

    result = service.checkout(tokens[0], code, ADDRESS)

    created = orders_in_file(data_file)
    assert len(created) == 1
    assert result["order_id"] == created[0]["id"]


def test_checkout_returns_the_order_id_status_and_total(service):
    code, tokens = make_locked(service)

    result = service.checkout(tokens[0], code, ADDRESS)

    assert result == {"order_id": 1, "status": "CHECKED_OUT", "total_cents": 2 * 899 + 1099 + 499}


def test_the_order_is_a_normal_order_for_the_groups_restaurant(service, orders, fake_clock):
    code, tokens = make_locked(service)
    fake_clock.advance(timedelta(minutes=5))

    order_id = service.checkout(tokens[0], code, ADDRESS)["order_id"]

    order = orders.get_order(order_id)  # readable through the normal order service
    assert order["restaurant_id"] == RESTAURANT
    assert order["address"] == ADDRESS
    assert order["status"] == "PLACED"
    assert order["created_at"] == fake_clock.now().isoformat()


def test_the_order_address_is_trimmed(service, orders):
    code, tokens = make_locked(service)

    order_id = service.checkout(tokens[0], code, "  12 Elm Street \n")["order_id"]

    assert orders.get_order(order_id)["address"] == "12 Elm Street"


def test_the_order_contains_every_participants_items(service, orders):
    code, tokens = make_locked(service, [[(ITEM_A, 2)], [(ITEM_B, 1)], [(ITEM_C, 4)]])

    order = orders.get_order(service.checkout(tokens[0], code, ADDRESS)["order_id"])

    assert lines_of(order) == {(ITEM_A, 2, 899), (ITEM_B, 1, 1099), (ITEM_C, 4, 399)}


def test_identical_items_from_different_participants_are_merged_by_adding_quantities(service, orders):
    code, tokens = make_locked(
        service,
        [
            [(ITEM_A, 2), (ITEM_B, 1)],  # Host
            [(ITEM_A, 3), (ITEM_C, 4)],  # Bo
            [(ITEM_B, 2)],  # Cy
        ],
    )

    order = orders.get_order(service.checkout(tokens[0], code, ADDRESS)["order_id"])

    assert len(order["items"]) == 3  # one line per menu item
    assert lines_of(order) == {(ITEM_A, 5, 899), (ITEM_B, 3, 1099), (ITEM_C, 4, 399)}


def test_a_merged_quantity_can_be_above_9(service, orders):
    code, tokens = make_locked(service, [[(ITEM_A, 9)], [(ITEM_A, 9)]])

    order = orders.get_order(service.checkout(tokens[0], code, ADDRESS)["order_id"])

    assert lines_of(order) == {(ITEM_A, 18, 899)}
    assert order["total_cents"] == 18 * 899 + 499


def test_the_total_is_all_subtotals_plus_the_delivery_fee(service, orders):
    code, tokens = make_locked(service)  # host A x2 = 1798, guest B x1 = 1099

    order = orders.get_order(service.checkout(tokens[0], code, ADDRESS)["order_id"])

    assert order["total_cents"] == 1798 + 1099 + 499 == 3396
    assert type(order["total_cents"]) is int


def test_the_total_with_merged_items_example(service, orders):
    code, tokens = make_locked(
        service, [[(ITEM_A, 2), (ITEM_B, 1)], [(ITEM_A, 3), (ITEM_C, 4)], [(ITEM_B, 2)]]
    )

    order = orders.get_order(service.checkout(tokens[0], code, ADDRESS)["order_id"])

    # A x5 = 4495, B x3 = 3297, C x4 = 1596, plus the 499 fee
    assert order["total_cents"] == 4495 + 3297 + 1596 + 499 == 9887


def test_the_order_total_equals_the_sum_of_the_summary_totals(service, orders):
    code, tokens = make_locked(service, [[(ITEM_A, 2)], [(ITEM_B, 3)], [(ITEM_C, 1)], [(ITEM_A, 9)]])
    summary = service.get_summary(tokens[0], code)

    order = orders.get_order(service.checkout(tokens[0], code, ADDRESS)["order_id"])

    assert order["total_cents"] == sum(entry["total_cents"] for entry in summary["participants"])


def test_a_group_of_one_pays_their_subtotal_plus_the_whole_fee(service, orders):
    code, tokens = make_locked(service, [[(ITEM_A, 1)]])

    order = orders.get_order(service.checkout(tokens[0], code, ADDRESS)["order_id"])

    assert order["total_cents"] == 899 + 499


def test_the_delivery_fee_is_the_service_constant(service, orders):
    code, tokens = make_locked(service, [[(ITEM_C, 1)]])

    order = orders.get_order(service.checkout(tokens[0], code, ADDRESS)["order_id"])

    assert order["total_cents"] - 399 == DELIVERY_FEE_CENTS == 499


def test_the_group_becomes_checked_out_and_records_the_order_id(service, repo):
    code, tokens = make_locked(service)

    order_id = service.checkout(tokens[0], code, ADDRESS)["order_id"]

    group = repo.get_group_order(code)
    assert group["status"] == "CHECKED_OUT"
    assert group["order_id"] == order_id


def test_checkout_changes_nothing_else_on_the_group(service, repo, fake_clock):
    code, tokens = make_locked(service)
    before = repo.get_group_order(code)
    fake_clock.advance(timedelta(minutes=30))

    order_id = service.checkout(tokens[0], code, ADDRESS)["order_id"]

    # Checkout is not "activity" in R30, so last_activity_at stays as it was.
    assert repo.get_group_order(code) == {**before, "status": "CHECKED_OUT", "order_id": order_id}


def test_group_order_ids_follow_the_normal_orders(service, orders):
    first = orders.create_order(RESTAURANT, "1 Main St", [{"menu_item_id": ITEM_A, "quantity": 1}])
    code, tokens = make_locked(service)

    result = service.checkout(tokens[0], code, ADDRESS)

    assert result["order_id"] == first["id"] + 1


def test_the_normal_order_status_flow_works_on_a_group_order(service, orders):
    code, tokens = make_locked(service)
    order_id = service.checkout(tokens[0], code, ADDRESS)["order_id"]

    assert orders.update_status(order_id, "PREPARING")["status"] == "PREPARING"


def test_the_summary_still_works_after_checkout(service):
    code, tokens = make_locked(service)
    service.checkout(tokens[0], code, ADDRESS)

    summary = service.get_summary(tokens[1], code)

    assert summary["status"] == "CHECKED_OUT"


def test_two_groups_make_two_separate_orders(service, data_file):
    code_1, tokens_1 = make_locked(service)
    code_2, tokens_2 = make_locked(service, [[(ITEM_C, 1)]])

    first = service.checkout(tokens_1[0], code_1, ADDRESS)
    second = service.checkout(tokens_2[0], code_2, "9 Pine Road")

    assert first["order_id"] != second["order_id"]
    assert len(orders_in_file(data_file)) == 2


# ============================================================ R33: not locked


def test_an_open_group_gives_not_locked(service, repo, data_file):
    code, tokens = make_open(service)
    before = repo.get_group_order(code)

    assert_rejected("NOT_LOCKED", service.checkout, tokens[0], code, ADDRESS)

    assert repo.get_group_order(code) == before
    assert orders_in_file(data_file) == []


# ======================================================= R34: restaurant hours


@pytest.mark.parametrize(
    ("locked_at", "checkout_at", "is_open"),
    [
        (at(11, 0, 0), at(11, 59, 59), False),  # one second before 12:00
        (at(11, 0, 0), at(12, 0, 0), True),  # exactly when it opens
        (at(20, 0, 0), at(21, 29, 59), True),  # one second before 21:30
        (at(20, 0, 0), at(21, 30, 0), False),  # exactly at closing time
        (at(20, 0, 0), at(21, 59, 0), False),
        (at(0, 30, 0), at(1, 0, 0), False),  # the middle of the night
    ],
)
def test_checkout_is_allowed_only_while_the_restaurant_is_open(
    service, repo, fake_clock, data_file, locked_at, checkout_at, is_open
):
    fake_clock.set(locked_at)
    code, tokens = make_locked(service)
    before = repo.get_group_order(code)
    fake_clock.set(checkout_at)

    if is_open:
        service.checkout(tokens[0], code, ADDRESS)
        assert repo.get_group_order(code)["status"] == "CHECKED_OUT"
        assert len(orders_in_file(data_file)) == 1
    else:
        assert_rejected("RESTAURANT_CLOSED", service.checkout, tokens[0], code, ADDRESS)
        assert repo.get_group_order(code) == before  # still LOCKED, nothing changed
        assert orders_in_file(data_file) == []


def test_the_hours_are_those_of_the_groups_restaurant(service, fake_clock):
    # At 21:45 restaurant 1 (11:00-22:00) is open but restaurant 2 (12:00-21:30) is closed.
    fake_clock.set(at(21, 0, 0))
    code_1, tokens_1 = make_locked(service, [[(1, 1)]], restaurant=1)
    code_2, tokens_2 = make_locked(service, [[(ITEM_A, 1)]], restaurant=2)
    fake_clock.set(at(21, 45, 0))

    service.checkout(tokens_1[0], code_1, ADDRESS)
    assert_rejected("RESTAURANT_CLOSED", service.checkout, tokens_2[0], code_2, ADDRESS)


def test_the_hours_are_compared_in_utc(service, fake_clock):
    plus_5 = timezone(timedelta(hours=5))
    # 16:30 at UTC+5 is 11:30 UTC: restaurant 2 (opens 12:00 UTC) is closed. The wall-clock
    # time 16:30 would look "open", so this fails if the offset is ignored.
    fake_clock.set(datetime(2001, 1, 1, 16, 30, tzinfo=plus_5))
    code, tokens = make_locked(service)
    assert_rejected("RESTAURANT_CLOSED", service.checkout, tokens[0], code, ADDRESS)

    # One hour later, 17:30 at UTC+5 is 12:30 UTC: open.
    fake_clock.set(datetime(2001, 1, 1, 17, 30, tzinfo=plus_5))
    service.checkout(tokens[0], code, ADDRESS)


def test_a_closed_restaurant_can_be_retried_once_it_opens(service, repo, fake_clock):
    fake_clock.set(at(11, 30, 0))
    code, tokens = make_locked(service)
    assert_rejected("RESTAURANT_CLOSED", service.checkout, tokens[0], code, ADDRESS)

    fake_clock.set(at(12, 0, 0))
    service.checkout(tokens[0], code, ADDRESS)

    assert repo.get_group_order(code)["status"] == "CHECKED_OUT"


# ============================================================== R35: the address


@pytest.mark.parametrize(
    "address",
    ["", " ", "     ", "\n\t ", None, 123, 1.5, True, b"12 Elm Street", ["12 Elm Street"], {"street": "12 Elm"}],
)
def test_a_missing_or_blank_address_gives_invalid_address(service, repo, data_file, address):
    code, tokens = make_locked(service)
    before = repo.get_group_order(code)

    assert_rejected("INVALID_ADDRESS", service.checkout, tokens[0], code, address)

    assert repo.get_group_order(code) == before  # still LOCKED
    assert orders_in_file(data_file) == []


def test_the_group_can_be_checked_out_after_a_blank_address_is_corrected(service, repo):
    code, tokens = make_locked(service)
    assert_rejected("INVALID_ADDRESS", service.checkout, tokens[0], code, "   ")

    service.checkout(tokens[0], code, ADDRESS)

    assert repo.get_group_order(code)["status"] == "CHECKED_OUT"


# ================================================================== R27: not host


def test_a_guest_cannot_check_out(service, repo, data_file):
    code, tokens = make_locked(service)
    before = repo.get_group_order(code)

    assert_rejected("NOT_HOST", service.checkout, tokens[1], code, ADDRESS)

    assert repo.get_group_order(code) == before
    assert orders_in_file(data_file) == []


def test_a_user_who_is_not_in_the_group_cannot_check_out(service, repo, data_file):
    code, _ = make_locked(service)
    outsider = service.create_session()

    assert_rejected("NOT_HOST", service.checkout, outsider, code, ADDRESS)

    assert repo.get_group_order(code)["status"] == "LOCKED"
    assert orders_in_file(data_file) == []


def test_the_host_is_the_person_in_host_token_not_just_participant_1(service, repo):
    code, tokens = make_locked(service)
    repo.update_group_order(code, lambda group: group.update(host_token=tokens[1]))

    assert_rejected("NOT_HOST", service.checkout, tokens[0], code, ADDRESS)  # the former host
    service.checkout(tokens[1], code, ADDRESS)  # the new host

    assert repo.get_group_order(code)["status"] == "CHECKED_OUT"


# ======================================================= R37: a second checkout


def test_a_second_checkout_gives_order_checked_out_and_creates_no_second_order(service, repo, data_file):
    code, tokens = make_locked(service)
    first = service.checkout(tokens[0], code, ADDRESS)
    after_first = repo.get_group_order(code)

    assert_rejected("ORDER_CHECKED_OUT", service.checkout, tokens[0], code, ADDRESS)
    assert_rejected("ORDER_CHECKED_OUT", service.checkout, tokens[0], code, "A different address")

    assert len(orders_in_file(data_file)) == 1
    assert repo.get_group_order(code) == after_first
    assert repo.get_group_order(code)["order_id"] == first["order_id"]


def test_a_guest_checking_out_a_checked_out_group_gets_order_checked_out(service):
    code, tokens = make_locked(service)
    service.checkout(tokens[0], code, ADDRESS)

    assert_rejected("ORDER_CHECKED_OUT", service.checkout, tokens[1], code, ADDRESS)


def test_a_checked_out_group_never_expires(service, repo, fake_clock):
    code, tokens = make_locked(service)
    service.checkout(tokens[0], code, ADDRESS)
    fake_clock.advance(timedelta(days=30))

    assert_rejected("ORDER_CHECKED_OUT", service.checkout, tokens[0], code, ADDRESS)

    assert repo.get_group_order(code)["status"] == "CHECKED_OUT"


def test_nothing_else_works_on_a_checked_out_group(service):
    code, tokens = make_locked(service)
    service.checkout(tokens[0], code, ADDRESS)

    assert_rejected("ORDER_CHECKED_OUT", service.lock, tokens[0], code)
    assert_rejected("ORDER_CHECKED_OUT", service.join, service.create_session(), code, "Late")
    assert_rejected("ORDER_CHECKED_OUT", service.add_item, tokens[0], code, 1, ITEM_B, 1)


# ======================================================== R31, R32: expiry on checkout


def test_checkout_at_1_59_59_after_the_lock_still_works(service, repo, fake_clock):
    code, tokens = make_locked(service)
    fake_clock.advance(TWO_HOURS - ONE_SECOND)

    service.checkout(tokens[0], code, ADDRESS)

    assert repo.get_group_order(code)["status"] == "CHECKED_OUT"


def test_checkout_at_exactly_2_hours_gives_order_expired_and_saves_expired(service, repo, fake_clock, data_file):
    code, tokens = make_locked(service)
    before = repo.get_group_order(code)
    fake_clock.advance(TWO_HOURS)

    assert_rejected("ORDER_EXPIRED", service.checkout, tokens[0], code, ADDRESS)

    assert repo.get_group_order(code) == {**before, "status": "EXPIRED"}  # saved; nothing else changed
    assert orders_in_file(data_file) == []


def test_an_already_expired_group_gives_order_expired(service, repo, data_file):
    code, tokens = make_locked(service)
    set_status(repo, code, "EXPIRED")

    assert_rejected("ORDER_EXPIRED", service.checkout, tokens[0], code, ADDRESS)

    assert orders_in_file(data_file) == []


def test_an_open_group_that_expired_gives_order_expired_not_not_locked(service, repo, fake_clock):
    code, tokens = make_open(service)
    fake_clock.advance(TWO_HOURS)

    assert_rejected("ORDER_EXPIRED", service.checkout, tokens[0], code, ADDRESS)

    assert repo.get_group_order(code)["status"] == "EXPIRED"


def test_a_guest_on_an_expired_group_gets_order_expired_not_not_host(service, fake_clock):
    code, tokens = make_locked(service)
    fake_clock.advance(TWO_HOURS)

    assert_rejected("ORDER_EXPIRED", service.checkout, tokens[1], code, ADDRESS)


def test_expired_comes_before_restaurant_closed_and_invalid_address(service, fake_clock):
    fake_clock.set(at(19, 0, 0))
    code, tokens = make_locked(service)
    fake_clock.set(at(21, 45, 0))  # restaurant 2 is closed, and more than 2 hours have passed

    assert_rejected("ORDER_EXPIRED", service.checkout, tokens[0], code, "   ")


# ============================================================ sessions and codes


@pytest.mark.parametrize("token", [None, "", "never-issued"])
def test_a_missing_or_unknown_session_gives_invalid_session(service, repo, data_file, token):
    code, _ = make_locked(service)

    assert_rejected("INVALID_SESSION", service.checkout, token, code, ADDRESS)

    assert repo.get_group_order(code)["status"] == "LOCKED"
    assert orders_in_file(data_file) == []


def test_a_wrong_code_gives_invalid_code(service):
    _, tokens = make_locked(service)

    assert_rejected("INVALID_CODE", service.checkout, tokens[0], "nope42", ADDRESS)


def test_invalid_session_is_checked_before_invalid_code(service):
    assert_rejected("INVALID_SESSION", service.checkout, "never-issued", "nope42", ADDRESS)


# ============================================================ the order of the checks


def test_checked_out_comes_before_not_host(service):
    code, tokens = make_locked(service)
    service.checkout(tokens[0], code, ADDRESS)

    assert_rejected("ORDER_CHECKED_OUT", service.checkout, tokens[1], code, "   ")


def test_not_host_comes_before_not_locked(service):
    code, tokens = make_open(service)
    outsider = service.create_session()

    assert_rejected("NOT_HOST", service.checkout, outsider, code, ADDRESS)


def test_not_locked_comes_before_restaurant_closed(service, fake_clock):
    fake_clock.set(at(11, 0, 0))  # restaurant 2 is closed
    code, tokens = make_open(service)

    assert_rejected("NOT_LOCKED", service.checkout, tokens[0], code, ADDRESS)


def test_restaurant_closed_comes_before_invalid_address(service, fake_clock):
    fake_clock.set(at(11, 0, 0))  # restaurant 2 is closed
    code, tokens = make_locked(service)

    assert_rejected("RESTAURANT_CLOSED", service.checkout, tokens[0], code, "   ")


def test_not_locked_comes_before_invalid_address(service):
    code, tokens = make_open(service)

    assert_rejected("NOT_LOCKED", service.checkout, tokens[0], code, "")


# ================================================= R38: a failed checkout changes nothing


def test_every_kind_of_failed_checkout_leaves_the_group_locked_with_no_order(service, repo, fake_clock, data_file):
    fake_clock.set(at(11, 0, 0))
    code, tokens = make_locked(service)  # locked while closed; opens in an hour
    before = repo.get_group_order(code)

    assert_rejected("RESTAURANT_CLOSED", service.checkout, tokens[0], code, ADDRESS)  # closed
    fake_clock.set(at(12, 0, 0))
    assert_rejected("INVALID_ADDRESS", service.checkout, tokens[0], code, " ")  # blank address
    assert_rejected("NOT_HOST", service.checkout, tokens[1], code, ADDRESS)  # not the host
    assert_rejected("INVALID_SESSION", service.checkout, "never-issued", code, ADDRESS)

    assert repo.get_group_order(code) == before
    assert before["status"] == "LOCKED" and before["order_id"] is None
    assert orders_in_file(data_file) == []


def test_a_failed_checkout_does_not_restart_the_countdown(service, repo, fake_clock):
    code, tokens = make_locked(service)
    fake_clock.advance(timedelta(hours=1))
    assert_rejected("INVALID_ADDRESS", service.checkout, tokens[0], code, "")

    fake_clock.advance(timedelta(hours=1))  # exactly 2:00:00 since the lock

    assert_rejected("ORDER_EXPIRED", service.checkout, tokens[0], code, ADDRESS)


def test_if_creating_the_order_fails_the_group_stays_locked_and_no_order_remains(
    store, repo, orders, fake_clock, data_file
):
    class FailsAfterCreating:
        """Creates the order for real, then fails, as if something broke right afterwards."""

        def create_order(self, *args, **kwargs):
            orders.create_order(*args, **kwargs)
            raise RuntimeError("boom")

    service = GroupOrderService(repo, RestaurantRepository(store), fake_clock, orders=FailsAfterCreating())
    code, tokens = make_locked(service)
    before = repo.get_group_order(code)

    with pytest.raises(RuntimeError, match="boom"):
        service.checkout(tokens[0], code, ADDRESS)

    assert repo.get_group_order(code) == before  # still LOCKED, order_id still None
    assert orders_in_file(data_file) == []  # the half-made order was rolled back


def test_an_order_service_error_is_passed_on_and_nothing_is_saved(store, repo, fake_clock, data_file):
    class Rejects:
        def create_order(self, *args, **kwargs):
            raise MiniDashError("ITEM_NOT_ON_MENU", "gone")

    service = GroupOrderService(repo, RestaurantRepository(store), fake_clock, orders=Rejects())
    code, tokens = make_locked(service)
    before = repo.get_group_order(code)

    assert_rejected("ITEM_NOT_ON_MENU", service.checkout, tokens[0], code, ADDRESS)

    assert repo.get_group_order(code) == before


def test_checkout_without_an_order_service_fails_clearly(store, repo, fake_clock):
    service = GroupOrderService(repo, RestaurantRepository(store), fake_clock)  # no orders=
    code, tokens = make_locked(service)

    with pytest.raises(RuntimeError, match="order service"):
        service.checkout(tokens[0], code, ADDRESS)

    assert repo.get_group_order(code)["status"] == "LOCKED"


def test_the_order_is_created_through_the_order_service(service, orders, monkeypatch):
    calls = []
    real = orders.create_order

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(orders, "create_order", spy)
    code, tokens = make_locked(service)

    service.checkout(tokens[0], code, ADDRESS)

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert RESTAURANT in args or kwargs.get("restaurant_id") == RESTAURANT
    assert kwargs.get("delivery_fee_cents") == 499


# ============================================ simultaneous requests (one atomic step)


def test_simultaneous_checkouts_create_exactly_one_order(service, repo, data_file):
    code, tokens = make_locked(service)

    results, rejected = run_at_the_same_time([lambda: service.checkout(tokens[0], code, ADDRESS) for _ in range(8)])

    assert len(results) == 1
    assert rejected == ["ORDER_CHECKED_OUT"] * 7
    created = orders_in_file(data_file)
    assert len(created) == 1
    group = repo.get_group_order(code)
    assert group["status"] == "CHECKED_OUT"
    assert group["order_id"] == created[0]["id"] == results[0]["order_id"]


def test_a_checkout_and_ordinary_orders_at_the_same_time_all_survive(service, orders, repo, data_file):
    code, tokens = make_locked(service)
    jobs = [lambda: service.checkout(tokens[0], code, ADDRESS)]
    jobs += [
        (lambda n=n: orders.create_order(1, f"{n} Main St", [{"menu_item_id": 1, "quantity": 1}])) for n in range(5)
    ]

    results, rejected = run_at_the_same_time(jobs)

    created = orders_in_file(data_file)
    assert rejected == []
    assert len(created) == 6  # 5 ordinary orders plus the group order, none lost
    assert sorted(o["id"] for o in created) == [1, 2, 3, 4, 5, 6]
    group = repo.get_group_order(code)
    group_order = next(o for o in created if o["id"] == group["order_id"])
    assert group_order["restaurant_id"] == RESTAURANT
    assert group["status"] == "CHECKED_OUT"


# ================================================================ injected clock


def test_checkout_uses_only_the_injected_clock(service, orders, fake_clock):
    fake_clock.set(at(20, 0, 0))
    code, tokens = make_locked(service)
    fake_clock.set(at(21, 29, 59))  # the real clock cannot be 2001, so this proves it is not used

    order = orders.get_order(service.checkout(tokens[0], code, ADDRESS)["order_id"])

    assert order["created_at"] == at(21, 29, 59).isoformat()


# ======================================== the order service: optional delivery fee


def one_line(quantity=2):
    return [{"menu_item_id": ITEM_A, "quantity": quantity}]


def test_the_order_service_adds_no_fee_by_default(orders):
    order = orders.create_order(RESTAURANT, "1 Main St", one_line(2))

    assert order["total_cents"] == 2 * 899


def test_the_order_service_adds_the_delivery_fee_it_is_given(orders):
    order = orders.create_order(RESTAURANT, "1 Main St", one_line(2), delivery_fee_cents=499)

    assert order["total_cents"] == 2 * 899 + 499
    assert type(order["total_cents"]) is int
    assert lines_of(order) == {(ITEM_A, 2, 899)}  # the lines themselves are unchanged


def test_a_fee_of_zero_is_the_same_as_no_fee(orders):
    order = orders.create_order(RESTAURANT, "1 Main St", one_line(2), delivery_fee_cents=0)

    assert order["total_cents"] == 2 * 899


def test_the_fee_is_part_of_the_stored_order_total(orders):
    created = orders.create_order(RESTAURANT, "1 Main St", one_line(1), delivery_fee_cents=499)

    assert orders.get_order(created["id"])["total_cents"] == 899 + 499


def test_the_fee_is_added_once_however_many_lines_there_are(orders):
    items = [{"menu_item_id": ITEM_A, "quantity": 1}, {"menu_item_id": ITEM_B, "quantity": 1}]

    order = orders.create_order(RESTAURANT, "1 Main St", items, delivery_fee_cents=499)

    assert order["total_cents"] == 899 + 1099 + 499


@pytest.mark.parametrize("fee", [-1, -499, 1.5, 499.0, "499", True, None])
def test_an_invalid_fee_is_rejected_and_no_order_is_stored(orders, data_file, fee):
    with pytest.raises(ValueError):
        orders.create_order(RESTAURANT, "1 Main St", one_line(1), delivery_fee_cents=fee)

    assert orders_in_file(data_file) == []


def test_the_other_order_checks_still_apply_when_a_fee_is_given(orders, data_file):
    assert_rejected("INVALID_ADDRESS", orders.create_order, RESTAURANT, "  ", one_line(1), 499)
    assert_rejected("RESTAURANT_NOT_FOUND", orders.create_order, 999, "1 Main St", one_line(1), 499)
    assert_rejected("EMPTY_ORDER", orders.create_order, RESTAURANT, "1 Main St", [], 499)

    assert orders_in_file(data_file) == []


# ================= every participant can learn the order id from the summary (for the receipt)


def test_the_summary_shows_the_order_id_to_the_host_and_to_every_guest_after_checkout(service):
    code, tokens = make_locked(service, [[(ITEM_A, 2)], [(ITEM_B, 1)], [(ITEM_C, 4)]])

    order_id = service.checkout(tokens[0], code, ADDRESS)["order_id"]

    for token in tokens:
        summary = service.get_summary(token, code)
        assert summary["status"] == "CHECKED_OUT"
        assert summary["order_id"] == order_id


def test_the_order_id_in_the_summary_is_the_id_of_the_one_normal_order(service, orders, data_file):
    code, tokens = make_locked(service)
    service.checkout(tokens[0], code, ADDRESS)

    order_id = service.get_summary(tokens[1], code)["order_id"]

    assert [o["id"] for o in orders_in_file(data_file)] == [order_id]
    assert orders.get_order(order_id)["restaurant_id"] == RESTAURANT


def test_the_summary_order_id_is_none_after_a_failed_checkout(service):
    code, tokens = make_locked(service)
    assert_rejected("INVALID_ADDRESS", service.checkout, tokens[0], code, "  ")

    assert service.get_summary(tokens[0], code)["order_id"] is None


def test_the_group_total_in_the_summary_matches_the_order_total(service, orders):
    code, tokens = make_locked(service, [[(ITEM_A, 2)], [(ITEM_B, 1)], [(ITEM_C, 4)]])
    service.checkout(tokens[0], code, ADDRESS)

    summary = service.get_summary(tokens[2], code)

    group_total = sum(entry["total_cents"] for entry in summary["participants"])
    assert group_total == orders.get_order(summary["order_id"])["total_cents"]
