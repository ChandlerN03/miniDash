import json
from datetime import datetime, timedelta, timezone

import pytest

from src.repository.group_orders_repo import GroupOrderRepository
from src.repository.restaurants_repo import RestaurantRepository
from src.services import group_order_service
from src.services.errors import MiniDashError
from src.services.fee_split import split_evenly
from src.services.group_order_service import DELIVERY_FEE_CENTS, GroupOrderService
from src.store.file_store import FileStore
from src.store.seed import SEED_DATA

# Far from the real current time, so reading the real clock would show up.
START = datetime(2001, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
TWO_HOURS = timedelta(hours=2)
ONE_SECOND = timedelta(seconds=1)

RESTAURANT = 2
ITEM_A, ITEM_B, ITEM_C = 5, 6, 7  # on the menu of restaurant 2
PRICE = {m["id"]: m["price_cents"] for m in SEED_DATA["menu_items"]}

ENTRY_FIELDS = {"participant_id", "display_name", "subtotal_cents", "fee_share_cents", "total_cents"}


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


# ---------------------------------------------------------------------- helpers


def make_group(service, names=("Host",)):
    """A group at restaurant 2 whose participants joined in the order of `names`.

    Returns (code, tokens) with tokens in join order; tokens[0] is the host.
    Participant ids are 1, 2, 3, ...
    """
    host = service.create_session()
    code = service.create_group_order(host, RESTAURANT, names[0])["code"]
    tokens = [host]
    for name in names[1:]:
        token = service.create_session()
        service.join(token, code, name)
        tokens.append(token)
    return code, tokens


def assert_rejected(code, func, *args):
    with pytest.raises(MiniDashError) as caught:
        func(*args)
    assert caught.value.code == code
    assert isinstance(caught.value.message, str) and caught.value.message


def set_status(repo, code, status):
    repo.update_group_order(code, lambda group: group.update(status=status))


def shares_of(summary):
    return [entry["fee_share_cents"] for entry in summary["participants"]]


# ======================================================== R21: the delivery fee


def test_the_delivery_fee_constant_is_499_cents():
    assert DELIVERY_FEE_CENTS == 499
    assert type(DELIVERY_FEE_CENTS) is int


def test_the_summary_states_the_delivery_fee(service):
    code, tokens = make_group(service)

    assert service.get_summary(tokens[0], code)["delivery_fee_cents"] == 499


# ================================================ R22-R24: fee shares (split_evenly)


def test_three_participants_split_499_as_166_166_167(service):
    code, tokens = make_group(service, ["A", "B", "C"])

    summary = service.get_summary(tokens[0], code)

    assert shares_of(summary) == [166, 166, 167]
    assert sum(shares_of(summary)) == 499


def test_a_single_participant_pays_the_whole_fee(service):
    code, tokens = make_group(service, ["Solo"])

    summary = service.get_summary(tokens[0], code)

    assert shares_of(summary) == [499]
    assert summary["participants"][0]["total_cents"] == 499  # no items, so subtotal 0


def test_two_participants_split_499_as_249_250(service):
    code, tokens = make_group(service, ["A", "B"])

    assert shares_of(service.get_summary(tokens[0], code)) == [249, 250]


def test_four_participants_split_499_with_the_extra_cents_at_the_end(service):
    code, tokens = make_group(service, ["A", "B", "C", "D"])

    assert shares_of(service.get_summary(tokens[0], code)) == [124, 125, 125, 125]


@pytest.mark.parametrize("size", range(1, 11))
def test_shares_always_add_up_to_499_and_differ_by_at_most_1_cent(service, size):
    code, tokens = make_group(service, [f"P{n}" for n in range(1, size + 1)])

    shares = shares_of(service.get_summary(tokens[0], code))

    assert len(shares) == size
    assert sum(shares) == 499
    assert max(shares) - min(shares) <= 1
    assert shares == sorted(shares)  # the extra cents go to the last participants
    assert shares == split_evenly(499, size)


def test_the_summary_calls_the_existing_split_evenly_function(service, monkeypatch):
    calls = []

    def fake_split(total_cents, parts):
        calls.append((total_cents, parts))
        return [7, 8, 9]

    monkeypatch.setattr(group_order_service, "split_evenly", fake_split)
    code, tokens = make_group(service, ["A", "B", "C"])

    summary = service.get_summary(tokens[0], code)

    assert calls == [(499, 3)]
    assert shares_of(summary) == [7, 8, 9]


def test_the_fee_share_changes_when_more_people_join(service):
    code, tokens = make_group(service, ["A", "B"])
    assert shares_of(service.get_summary(tokens[0], code)) == [249, 250]

    third = service.create_session()
    service.join(third, code, "C")

    assert shares_of(service.get_summary(tokens[0], code)) == [166, 166, 167]


# ========================================================= R20: the summary


def test_each_entry_has_name_subtotal_fee_share_and_total(service):
    code, tokens = make_group(service, ["Hana", "Bo"])

    summary = service.get_summary(tokens[0], code)

    assert len(summary["participants"]) == 2
    for entry in summary["participants"]:
        assert set(entry) == ENTRY_FIELDS
    assert [e["display_name"] for e in summary["participants"]] == ["Hana", "Bo"]
    assert [e["participant_id"] for e in summary["participants"]] == [1, 2]


def test_the_summary_is_in_join_order(service):
    names = ["Zed", "Amy", "Mia", "Bob", "Yan"]  # not alphabetical on purpose
    code, tokens = make_group(service, names)

    summary = service.get_summary(tokens[0], code)

    assert [e["display_name"] for e in summary["participants"]] == names
    assert [e["participant_id"] for e in summary["participants"]] == [1, 2, 3, 4, 5]


def test_subtotal_is_price_times_quantity_summed_over_the_participants_items(service):
    code, tokens = make_group(service, ["Host", "Guest"])
    service.add_item(tokens[0], code, 1, ITEM_A, 2)
    service.add_item(tokens[0], code, 1, ITEM_B, 1)
    service.add_item(tokens[1], code, 2, ITEM_C, 3)

    host, guest = service.get_summary(tokens[0], code)["participants"]

    assert host["subtotal_cents"] == 2 * PRICE[ITEM_A] + PRICE[ITEM_B]
    assert guest["subtotal_cents"] == 3 * PRICE[ITEM_C]


def test_subtotal_example_with_literal_prices(service):
    # Seed prices: item 5 = 899 cents, item 6 = 1099 cents.
    code, tokens = make_group(service)
    service.add_item(tokens[0], code, 1, ITEM_A, 2)
    service.add_item(tokens[0], code, 1, ITEM_B, 1)

    entry = service.get_summary(tokens[0], code)["participants"][0]

    assert entry["subtotal_cents"] == 2 * 899 + 1099 == 2897
    assert entry["fee_share_cents"] == 499
    assert entry["total_cents"] == 2897 + 499


def test_total_is_subtotal_plus_fee_share_for_everyone(service):
    code, tokens = make_group(service, ["A", "B", "C"])
    service.add_item(tokens[0], code, 1, ITEM_A, 1)
    service.add_item(tokens[1], code, 2, ITEM_B, 2)
    service.add_item(tokens[2], code, 3, ITEM_C, 9)

    summary = service.get_summary(tokens[1], code)

    for entry in summary["participants"]:
        assert entry["total_cents"] == entry["subtotal_cents"] + entry["fee_share_cents"]
    assert [e["total_cents"] for e in summary["participants"]] == [
        PRICE[ITEM_A] + 166,
        2 * PRICE[ITEM_B] + 166,
        9 * PRICE[ITEM_C] + 167,
    ]


def test_a_participant_with_no_items_has_subtotal_0_and_pays_only_their_fee_share(service):
    code, tokens = make_group(service, ["A", "B", "C"])
    service.add_item(tokens[0], code, 1, ITEM_A, 1)

    _, empty, _ = service.get_summary(tokens[0], code)["participants"]

    assert empty["subtotal_cents"] == 0
    assert empty["total_cents"] == empty["fee_share_cents"] == 166


def test_all_amounts_are_integers(service):
    code, tokens = make_group(service, ["A", "B", "C"])
    service.add_item(tokens[0], code, 1, ITEM_A, 2)

    summary = service.get_summary(tokens[0], code)

    assert type(summary["delivery_fee_cents"]) is int
    for entry in summary["participants"]:
        for field in ("subtotal_cents", "fee_share_cents", "total_cents"):
            assert type(entry[field]) is int, field


def test_the_sum_of_all_totals_is_all_subtotals_plus_the_delivery_fee(service):
    code, tokens = make_group(service, ["A", "B", "C", "D", "E", "F", "G"])
    for pid, token in enumerate(tokens, start=1):
        service.add_item(token, code, pid, ITEM_A + pid % 3, pid % 9 + 1)

    entries = service.get_summary(tokens[0], code)["participants"]

    assert sum(e["total_cents"] for e in entries) == sum(e["subtotal_cents"] for e in entries) + 499


def test_the_summary_changes_when_items_change(service):
    code, tokens = make_group(service, ["Host", "Guest"])
    service.add_item(tokens[1], code, 2, ITEM_A, 1)
    assert service.get_summary(tokens[0], code)["participants"][1]["subtotal_cents"] == PRICE[ITEM_A]

    service.change_item(tokens[1], code, 2, ITEM_A, 4)
    assert service.get_summary(tokens[0], code)["participants"][1]["subtotal_cents"] == 4 * PRICE[ITEM_A]

    service.remove_item(tokens[0], code, 2, ITEM_A)  # the host removes it
    assert service.get_summary(tokens[0], code)["participants"][1]["subtotal_cents"] == 0


def test_the_summary_includes_the_groups_status(service, repo):
    code, tokens = make_group(service)
    assert service.get_summary(tokens[0], code)["status"] == "OPEN"

    set_status(repo, code, "LOCKED")
    assert service.get_summary(tokens[0], code)["status"] == "LOCKED"

    set_status(repo, code, "CHECKED_OUT")
    assert service.get_summary(tokens[0], code)["status"] == "CHECKED_OUT"


# ---------------------------------------------------- prices are not stored (R20)


def test_prices_are_read_from_the_menu_when_the_summary_is_computed(service, data_file):
    code, tokens = make_group(service)
    service.add_item(tokens[0], code, 1, ITEM_A, 2)
    assert service.get_summary(tokens[0], code)["participants"][0]["subtotal_cents"] == 2 * 899

    data = json.loads(data_file.read_text())
    for item in data["menu_items"]:
        if item["id"] == ITEM_A:
            item["price_cents"] = 1000  # the menu price changes
    data_file.write_text(json.dumps(data))

    assert service.get_summary(tokens[0], code)["participants"][0]["subtotal_cents"] == 2 * 1000


def test_no_prices_are_stored_on_the_group_order(service, data_file):
    code, tokens = make_group(service, ["Host", "Guest"])
    service.add_item(tokens[0], code, 1, ITEM_A, 2)
    service.get_summary(tokens[0], code)

    group = json.loads(data_file.read_text())["group_orders"][code]

    assert group["items"] == [{"participant_id": 1, "menu_item_id": ITEM_A, "quantity": 2}]
    assert "price" not in json.dumps(group).lower()
    assert "cents" not in json.dumps(group).lower()


# ===================================================== who may read the summary


def test_every_participant_gets_the_same_summary(service):
    code, tokens = make_group(service, ["Host", "Bo", "Cy"])
    service.add_item(tokens[2], code, 3, ITEM_B, 2)

    summaries = [service.get_summary(token, code) for token in tokens]

    assert summaries[0] == summaries[1] == summaries[2]


def test_a_user_who_is_not_in_the_group_gets_not_allowed(service, repo):
    code, tokens = make_group(service)
    outsider = service.create_session()
    before = repo.get_group_order(code)

    assert_rejected("NOT_ALLOWED", service.get_summary, outsider, code)

    assert repo.get_group_order(code) == before


@pytest.mark.parametrize("token", [None, "", "never-issued"])
def test_a_missing_or_unknown_session_gives_invalid_session(service, token):
    code, _ = make_group(service)

    assert_rejected("INVALID_SESSION", service.get_summary, token, code)


def test_a_wrong_code_gives_invalid_code(service):
    _, tokens = make_group(service)

    assert_rejected("INVALID_CODE", service.get_summary, tokens[0], "nope42")


def test_invalid_session_is_checked_before_invalid_code(service):
    assert_rejected("INVALID_SESSION", service.get_summary, "never-issued", "nope42")


# ====================================================== viewing is not activity (R30)


def test_viewing_the_summary_does_not_move_last_activity(service, repo, fake_clock):
    code, tokens = make_group(service, ["Host", "Guest"])
    service.add_item(tokens[1], code, 2, ITEM_A, 1)
    before = repo.get_group_order(code)
    fake_clock.advance(timedelta(hours=1))

    service.get_summary(tokens[0], code)
    service.get_summary(tokens[1], code)

    assert repo.get_group_order(code) == before  # nothing at all changed
    assert repo.get_group_order(code)["last_activity_at"] == START.isoformat()


def test_viewing_the_summary_does_not_write_to_the_data_file(service, data_file, fake_clock):
    code, tokens = make_group(service)
    before = data_file.read_text()
    fake_clock.advance(timedelta(minutes=30))

    service.get_summary(tokens[0], code)

    assert data_file.read_text() == before


def test_viewing_the_summary_does_not_restart_the_countdown(service, repo, fake_clock):
    code, tokens = make_group(service)
    fake_clock.advance(timedelta(hours=1))
    service.get_summary(tokens[0], code)

    fake_clock.advance(timedelta(hours=1))  # exactly 2:00:00 since the last real activity

    assert_rejected("ORDER_EXPIRED", service.add_item, tokens[0], code, 1, ITEM_A, 1)


def test_a_rejected_summary_request_does_not_move_last_activity(service, repo, fake_clock):
    code, tokens = make_group(service)
    outsider = service.create_session()
    before = repo.get_group_order(code)
    fake_clock.advance(timedelta(hours=1))

    assert_rejected("NOT_ALLOWED", service.get_summary, outsider, code)

    assert repo.get_group_order(code) == before


# ===================================== R31, R32: expiry is applied but not rejected


def test_the_summary_at_1_59_59_is_open_and_nothing_is_saved(service, repo, fake_clock):
    code, tokens = make_group(service)
    fake_clock.advance(TWO_HOURS - ONE_SECOND)

    summary = service.get_summary(tokens[0], code)

    assert summary["status"] == "OPEN"
    assert repo.get_group_order(code)["status"] == "OPEN"


def test_the_summary_at_exactly_2_hours_still_returns_and_saves_expired(service, repo, fake_clock):
    code, tokens = make_group(service, ["Host", "Guest"])
    service.add_item(tokens[1], code, 2, ITEM_A, 2)
    before = repo.get_group_order(code)
    fake_clock.advance(TWO_HOURS)

    summary = service.get_summary(tokens[0], code)  # not rejected

    assert summary["status"] == "EXPIRED"
    assert summary["participants"][1]["subtotal_cents"] == 2 * PRICE[ITEM_A]
    assert repo.get_group_order(code) == {**before, "status": "EXPIRED"}  # only the status changed


def test_a_locked_group_expires_when_the_summary_is_read(service, repo, fake_clock):
    code, tokens = make_group(service)
    set_status(repo, code, "LOCKED")
    fake_clock.advance(TWO_HOURS)

    summary = service.get_summary(tokens[0], code)

    assert summary["status"] == "EXPIRED"
    assert repo.get_group_order(code)["status"] == "EXPIRED"


def test_an_already_expired_group_still_returns_a_summary(service, repo):
    code, tokens = make_group(service)
    set_status(repo, code, "EXPIRED")

    assert service.get_summary(tokens[0], code)["status"] == "EXPIRED"


def test_a_checked_out_group_never_expires_when_the_summary_is_read(service, repo, fake_clock):
    code, tokens = make_group(service)
    set_status(repo, code, "CHECKED_OUT")
    fake_clock.advance(timedelta(days=30))

    assert service.get_summary(tokens[0], code)["status"] == "CHECKED_OUT"
    assert repo.get_group_order(code)["status"] == "CHECKED_OUT"


def test_expiry_is_applied_even_when_a_non_participant_is_rejected(service, repo, fake_clock):
    code, tokens = make_group(service)
    outsider = service.create_session()
    fake_clock.advance(TWO_HOURS)

    assert_rejected("NOT_ALLOWED", service.get_summary, outsider, code)

    assert repo.get_group_order(code)["status"] == "EXPIRED"  # R31 applies before the request is handled


def test_after_the_summary_expired_the_group_other_requests_get_order_expired(service, fake_clock):
    code, tokens = make_group(service)
    fake_clock.advance(TWO_HOURS)
    service.get_summary(tokens[0], code)

    assert_rejected("ORDER_EXPIRED", service.add_item, tokens[0], code, 1, ITEM_A, 1)
    assert_rejected("ORDER_EXPIRED", service.join, service.create_session(), code, "Late")


# ================================================================ injected clock


def test_the_summary_uses_only_the_injected_clock(service, repo, fake_clock):
    code, tokens = make_group(service)
    fake_clock.advance(TWO_HOURS - ONE_SECOND)  # clock is in 2001; a real clock would say "expired"

    assert service.get_summary(tokens[0], code)["status"] == "OPEN"
