import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

from src.repository.group_orders_repo import GroupOrderRepository
from src.repository.restaurants_repo import RestaurantRepository
from src.services import group_order_service
from src.services.errors import MiniDashError
from src.services.group_order_service import GroupOrderService
from src.services.share_code import ALPHABET
from src.store.file_store import FileStore
from src.store.seed import SEED_DATA

# Far from the real current time, so reading the real clock would show up.
START = datetime(2001, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
TWO_HOURS = timedelta(hours=2)
ONE_SECOND = timedelta(seconds=1)


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


def new_group(service, restaurant_id=2, name="Host"):
    """Create a session and a group. Returns (host_token, code)."""
    token = service.create_session()
    result = service.create_group_order(token, restaurant_id, name)
    return token, result["code"]


def new_user(service) -> str:
    return service.create_session()


def join_new_user(service, code, name="Guest") -> str:
    token = new_user(service)
    service.join(token, code, name)
    return token


def fill_group(service, code, total_participants):
    """Join users to a brand-new group until it has `total_participants` (the host counts as 1)."""
    for number in range(2, total_participants + 1):  # a new group has only the host
        join_new_user(service, code, f"Guest {number}")


def set_status(repo, code, status):
    group = repo.get_group_order(code)
    group["status"] = status
    repo.save_group_order(group)


def assert_rejected(code, func, *args):
    with pytest.raises(MiniDashError) as caught:
        func(*args)
    assert caught.value.code == code
    assert isinstance(caught.value.message, str) and caught.value.message


def read_file(data_file) -> dict:
    return json.loads(data_file.read_text())


# ============================================================ R1: sessions


def test_create_session_returns_a_token_that_is_stored(service, repo):
    token = service.create_session()

    assert isinstance(token, str) and token
    assert repo.session_exists(token) is True


def test_every_session_token_is_unique(service):
    tokens = {service.create_session() for _ in range(200)}

    assert len(tokens) == 200


def test_session_is_stored_with_the_time_from_the_injected_clock(service, data_file, fake_clock):
    token = service.create_session()

    stored = read_file(data_file)["sessions"][token]
    assert stored["created_at"] == fake_clock.now().isoformat()


# ================================================== R3, R4, R2: create a group


def test_create_group_returns_the_share_code_and_status_open(service):
    token = new_user(service)

    result = service.create_group_order(token, 2, "Hana")

    assert result["status"] == "OPEN"
    assert len(result["code"]) == 6
    assert set(result["code"]) <= set(ALPHABET)


def test_creator_becomes_host_and_first_participant(service, repo, fake_clock):
    token = new_user(service)

    code = service.create_group_order(token, 2, "Hana")["code"]

    group = repo.get_group_order(code)
    assert group["host_token"] == token
    assert group["status"] == "OPEN"
    assert group["restaurant_id"] == 2
    assert group["order_id"] is None
    assert group["items"] == []
    assert group["participants"] == [
        {
            "participant_id": 1,
            "token": token,
            "display_name": "Hana",
            "joined_at": fake_clock.now().isoformat(),
        }
    ]


def test_group_records_when_it_was_created_using_the_injected_clock(service, repo, fake_clock):
    fake_clock.advance(timedelta(days=3, hours=4))
    token = new_user(service)

    code = service.create_group_order(token, 2, "Hana")["code"]

    group = repo.get_group_order(code)
    assert group["created_at"] == fake_clock.now().isoformat()
    assert group["last_activity_at"] == fake_clock.now().isoformat()


def test_each_group_gets_its_own_code_and_id(service, repo):
    _, first = new_group(service)
    _, second = new_group(service)

    assert first != second
    assert repo.get_group_order(first)["id"] != repo.get_group_order(second)["id"]


def test_new_share_code_is_checked_against_every_code_already_issued(service, monkeypatch):
    _, old_code = new_group(service)
    seen = {}

    def fake_generate(existing_codes, rng=None):
        seen["knows_old_code"] = old_code in existing_codes
        seen["knows_unissued_code"] = "zzzzzz" in existing_codes
        return "Qw7rTy"

    monkeypatch.setattr(group_order_service, "generate_share_code", fake_generate)

    new_code = service.create_group_order(new_user(service), 2, "Hana")["code"]

    assert new_code == "Qw7rTy"
    assert seen == {"knows_old_code": True, "knows_unissued_code": False}


def test_codes_of_expired_and_checked_out_groups_are_also_checked(service, repo, monkeypatch):
    _, expired_code = new_group(service)
    _, checked_out_code = new_group(service)
    set_status(repo, expired_code, "EXPIRED")
    set_status(repo, checked_out_code, "CHECKED_OUT")
    seen = {}

    def fake_generate(existing_codes, rng=None):
        seen["both"] = expired_code in existing_codes and checked_out_code in existing_codes
        return "Qw7rTy"

    monkeypatch.setattr(group_order_service, "generate_share_code", fake_generate)
    service.create_group_order(new_user(service), 2, "Hana")

    assert seen["both"] is True


def test_a_share_code_taken_at_the_last_moment_is_retried(service, repo, monkeypatch):
    _, taken_code = new_group(service)
    codes = iter([taken_code, "Qw7rTy"])  # the first one is already stored

    # Ignores existing_codes on purpose, as if another request took the code a moment ago.
    monkeypatch.setattr(group_order_service, "generate_share_code", lambda existing_codes, rng=None: next(codes))

    new_code = service.create_group_order(new_user(service), 2, "Hana")["code"]

    assert new_code == "Qw7rTy"
    assert repo.get_group_order(taken_code)["host_token"] != repo.get_group_order(new_code)["host_token"]


def test_unknown_restaurant_gives_restaurant_not_found(service):
    token = new_user(service)

    assert_rejected("RESTAURANT_NOT_FOUND", service.create_group_order, token, 999, "Hana")


def test_rejected_create_stores_no_group(service, data_file):
    token = new_user(service)

    assert_rejected("RESTAURANT_NOT_FOUND", service.create_group_order, token, 999, "Hana")

    assert read_file(data_file)["group_orders"] == {}


@pytest.mark.parametrize("token", [None, "", "never-issued"])
def test_create_with_a_missing_or_unknown_session_gives_invalid_session(service, data_file, token):
    assert_rejected("INVALID_SESSION", service.create_group_order, token, 2, "Hana")

    assert read_file(data_file)["group_orders"] == {}


def test_invalid_session_is_checked_before_the_restaurant(service):
    assert_rejected("INVALID_SESSION", service.create_group_order, "never-issued", 999, "Hana")


# ===================================================== R7: a successful join


def test_join_adds_the_user_as_the_next_participant(service, repo, fake_clock):
    _, code = new_group(service, name="Hana")
    fake_clock.advance(timedelta(minutes=5))
    guest = new_user(service)

    service.join(guest, code, "Bo")

    participants = repo.get_group_order(code)["participants"]
    assert len(participants) == 2
    assert participants[1] == {
        "participant_id": 2,
        "token": guest,
        "display_name": "Bo",
        "joined_at": fake_clock.now().isoformat(),
    }


def test_join_returns_the_new_participant(service):
    _, code = new_group(service)
    guest = new_user(service)

    participant = service.join(guest, code, "Bo")

    assert participant["participant_id"] == 2
    assert participant["display_name"] == "Bo"
    assert participant["token"] == guest


def test_participants_are_kept_in_join_order_with_ids_1_2_3(service, repo):
    _, code = new_group(service, name="Zed")
    for name in ["Amy", "Mia", "Bob"]:
        join_new_user(service, code, name)

    participants = repo.get_group_order(code)["participants"]

    assert [p["display_name"] for p in participants] == ["Zed", "Amy", "Mia", "Bob"]
    assert [p["participant_id"] for p in participants] == [1, 2, 3, 4]


def test_join_does_not_change_status_host_or_items(service, repo):
    host, code = new_group(service)
    before = repo.get_group_order(code)

    join_new_user(service, code)

    after = repo.get_group_order(code)
    assert after["status"] == "OPEN"
    assert after["host_token"] == host
    assert after["items"] == before["items"]
    assert after["created_at"] == before["created_at"]


def test_code_is_case_sensitive(service):
    _, code = new_group(service)
    wrong_case = code.swapcase()
    assert wrong_case != code

    assert_rejected("INVALID_CODE", service.join, new_user(service), wrong_case, "Bo")


# ======================================================= R8: 10 participants


def test_the_10th_participant_can_join(service, repo):
    _, code = new_group(service)

    fill_group(service, code, 10)

    assert len(repo.get_group_order(code)["participants"]) == 10


def test_the_11th_participant_gets_group_full(service, repo):
    _, code = new_group(service)
    fill_group(service, code, 10)

    assert_rejected("GROUP_FULL", service.join, new_user(service), code, "Eleven")

    assert len(repo.get_group_order(code)["participants"]) == 10


def test_the_host_counts_toward_the_limit(service):
    _, code = new_group(service)
    fill_group(service, code, 9)  # host plus 8 guests

    service.join(new_user(service), code, "Tenth")  # still fits

    assert_rejected("GROUP_FULL", service.join, new_user(service), code, "Eleven")


# =========================================================== R9: wrong code


def test_wrong_code_gives_invalid_code(service):
    new_group(service)

    assert_rejected("INVALID_CODE", service.join, new_user(service), "nope42", "Bo")


def test_wrong_code_changes_nothing(service, data_file):
    _, code = new_group(service)
    guest = new_user(service)
    before = read_file(data_file)

    assert_rejected("INVALID_CODE", service.join, guest, "nope42", "Bo")

    assert read_file(data_file) == before


# ============================================== R10, R11: locked, checked out


def test_locked_group_gives_order_locked(service, repo):
    _, code = new_group(service)
    set_status(repo, code, "LOCKED")

    assert_rejected("ORDER_LOCKED", service.join, new_user(service), code, "Bo")


def test_checked_out_group_gives_order_checked_out(service, repo):
    _, code = new_group(service)
    set_status(repo, code, "CHECKED_OUT")

    assert_rejected("ORDER_CHECKED_OUT", service.join, new_user(service), code, "Bo")


# ================================================================ R12: twice


def test_joining_twice_gives_already_joined_and_keeps_one_record(service, repo):
    _, code = new_group(service)
    guest = new_user(service)
    service.join(guest, code, "Bo")

    assert_rejected("ALREADY_JOINED", service.join, guest, code, "Bo again")

    participants = repo.get_group_order(code)["participants"]
    assert [p["token"] for p in participants].count(guest) == 1
    assert len(participants) == 2
    assert participants[1]["display_name"] == "Bo"


def test_the_host_joining_their_own_group_gives_already_joined(service, repo):
    host, code = new_group(service)

    assert_rejected("ALREADY_JOINED", service.join, host, code, "Hana again")

    assert len(repo.get_group_order(code)["participants"]) == 1


# ======================================================= R2: session on join


@pytest.mark.parametrize("token", [None, "", "never-issued"])
def test_join_with_a_missing_or_unknown_session_gives_invalid_session(service, repo, token):
    _, code = new_group(service)

    assert_rejected("INVALID_SESSION", service.join, token, code, "Bo")

    assert len(repo.get_group_order(code)["participants"]) == 1


# ====================================================== order of the checks


def test_invalid_session_is_checked_before_the_code(service):
    assert_rejected("INVALID_SESSION", service.join, "never-issued", "nope42", "Bo")


def test_invalid_code_is_checked_before_everything_about_the_group(service):
    # No group exists, so there is nothing else to check.
    assert_rejected("INVALID_CODE", service.join, new_user(service), "nope42", "Bo")


def test_expired_is_checked_before_locked(service, repo, fake_clock):
    _, code = new_group(service)
    set_status(repo, code, "LOCKED")
    fake_clock.advance(TWO_HOURS)

    assert_rejected("ORDER_EXPIRED", service.join, new_user(service), code, "Bo")


def test_checked_out_is_checked_before_already_joined(service, repo):
    host, code = new_group(service)
    set_status(repo, code, "CHECKED_OUT")

    assert_rejected("ORDER_CHECKED_OUT", service.join, host, code, "Hana")


def test_locked_is_checked_before_already_joined(service, repo):
    host, code = new_group(service)
    set_status(repo, code, "LOCKED")

    assert_rejected("ORDER_LOCKED", service.join, host, code, "Hana")


def test_locked_is_checked_before_group_full(service, repo):
    _, code = new_group(service)
    fill_group(service, code, 10)
    set_status(repo, code, "LOCKED")

    assert_rejected("ORDER_LOCKED", service.join, new_user(service), code, "Eleven")


def test_already_joined_is_checked_before_group_full(service):
    host, code = new_group(service)
    fill_group(service, code, 10)

    assert_rejected("ALREADY_JOINED", service.join, host, code, "Hana")


# ==================================================== R31, R32: expiry on join


def test_join_at_1_59_59_still_works(service, repo, fake_clock):
    _, code = new_group(service)
    fake_clock.advance(TWO_HOURS - ONE_SECOND)

    service.join(new_user(service), code, "Bo")

    group = repo.get_group_order(code)
    assert group["status"] == "OPEN"
    assert len(group["participants"]) == 2


def test_join_at_exactly_2_hours_gives_order_expired_and_saves_status_expired(service, repo, fake_clock):
    _, code = new_group(service)
    guest = new_user(service)
    fake_clock.advance(TWO_HOURS)

    assert_rejected("ORDER_EXPIRED", service.join, guest, code, "Bo")

    group = repo.get_group_order(code)
    assert group["status"] == "EXPIRED"  # saved even though the request was rejected
    assert len(group["participants"]) == 1


def test_join_after_2_hours_and_1_second_gives_order_expired(service, repo, fake_clock):
    _, code = new_group(service)
    fake_clock.advance(TWO_HOURS + ONE_SECOND)

    assert_rejected("ORDER_EXPIRED", service.join, new_user(service), code, "Bo")

    assert repo.get_group_order(code)["status"] == "EXPIRED"


def test_a_locked_group_can_expire(service, repo, fake_clock):
    _, code = new_group(service)
    set_status(repo, code, "LOCKED")
    fake_clock.advance(TWO_HOURS)

    assert_rejected("ORDER_EXPIRED", service.join, new_user(service), code, "Bo")

    assert repo.get_group_order(code)["status"] == "EXPIRED"


def test_an_expired_group_keeps_rejecting_joins(service, repo, fake_clock):
    _, code = new_group(service)
    fake_clock.advance(TWO_HOURS)
    assert_rejected("ORDER_EXPIRED", service.join, new_user(service), code, "Bo")

    assert_rejected("ORDER_EXPIRED", service.join, new_user(service), code, "Cy")
    fake_clock.advance(timedelta(days=1))
    assert_rejected("ORDER_EXPIRED", service.join, new_user(service), code, "Di")

    assert repo.get_group_order(code)["status"] == "EXPIRED"


def test_a_group_already_marked_expired_gives_order_expired(service, repo):
    _, code = new_group(service)
    set_status(repo, code, "EXPIRED")

    assert_rejected("ORDER_EXPIRED", service.join, new_user(service), code, "Bo")


def test_expiry_changes_only_the_status(service, repo, fake_clock):
    _, code = new_group(service)
    before = repo.get_group_order(code)
    fake_clock.advance(TWO_HOURS)

    assert_rejected("ORDER_EXPIRED", service.join, new_user(service), code, "Bo")

    assert repo.get_group_order(code) == {**before, "status": "EXPIRED"}


def test_a_checked_out_group_never_expires(service, repo, fake_clock):
    _, code = new_group(service)
    set_status(repo, code, "CHECKED_OUT")
    fake_clock.advance(timedelta(days=30))

    assert_rejected("ORDER_CHECKED_OUT", service.join, new_user(service), code, "Bo")

    assert repo.get_group_order(code)["status"] == "CHECKED_OUT"


def test_expiry_is_measured_from_the_last_activity_not_from_creation(service, repo, fake_clock):
    _, code = new_group(service)
    fake_clock.advance(timedelta(hours=1, minutes=30))
    service.join(new_user(service), code, "Bo")  # activity at 1:30

    fake_clock.advance(TWO_HOURS - ONE_SECOND)  # 3:29:59 since creation, 1:59:59 since the join
    service.join(new_user(service), code, "Cy")

    assert len(repo.get_group_order(code)["participants"]) == 3


def test_a_group_expires_2_hours_after_the_last_successful_join(service, repo, fake_clock):
    _, code = new_group(service)
    fake_clock.advance(timedelta(hours=1))
    service.join(new_user(service), code, "Bo")

    fake_clock.advance(TWO_HOURS)

    assert_rejected("ORDER_EXPIRED", service.join, new_user(service), code, "Cy")
    assert repo.get_group_order(code)["status"] == "EXPIRED"


def test_expiry_is_applied_for_users_who_are_already_participants(service, repo, fake_clock):
    host, code = new_group(service)
    fake_clock.advance(TWO_HOURS)

    # R31 applies before the request is handled, so this is ORDER_EXPIRED, not ALREADY_JOINED.
    assert_rejected("ORDER_EXPIRED", service.join, host, code, "Hana")

    assert repo.get_group_order(code)["status"] == "EXPIRED"


def test_the_inactivity_limit_can_be_set_when_the_service_is_built(data_file, repo, fake_clock):
    restaurants = RestaurantRepository(FileStore(data_file))
    short = GroupOrderService(repo, restaurants, fake_clock, ttl=timedelta(minutes=30))
    _, code = new_group(short)

    fake_clock.advance(timedelta(minutes=29, seconds=59))
    short.join(new_user(short), code, "Bo")  # still inside the 30 minutes

    fake_clock.advance(timedelta(minutes=30))
    assert_rejected("ORDER_EXPIRED", short.join, new_user(short), code, "Cy")
    assert repo.get_group_order(code)["status"] == "EXPIRED"


# ============================================ simultaneous joins (no lost updates)


def run_joins_at_the_same_time(service, code, tokens):
    """Join all `tokens` at once. Returns (joined tokens, error codes of rejected joins)."""
    barrier = threading.Barrier(len(tokens))
    joined, rejected = [], []

    def go(token):
        barrier.wait()
        try:
            service.join(token, code, "Guest")
            joined.append(token)
        except MiniDashError as error:
            rejected.append(error.code)

    threads = [threading.Thread(target=go, args=(token,)) for token in tokens]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return joined, rejected


def test_simultaneous_joins_are_all_stored(service, repo):
    _, code = new_group(service)
    tokens = [new_user(service) for _ in range(9)]  # host + 9 = exactly 10

    joined, rejected = run_joins_at_the_same_time(service, code, tokens)

    participants = repo.get_group_order(code)["participants"]
    assert len(joined) == 9 and rejected == []
    assert len(participants) == 10
    assert {p["token"] for p in participants} >= set(tokens)


def test_simultaneous_joins_never_go_over_10_and_get_unique_ids(service, repo):
    _, code = new_group(service)
    tokens = [new_user(service) for _ in range(15)]

    joined, rejected = run_joins_at_the_same_time(service, code, tokens)

    participants = repo.get_group_order(code)["participants"]
    assert len(participants) == 10
    assert len(joined) == 9
    assert rejected == ["GROUP_FULL"] * 6
    assert sorted(p["participant_id"] for p in participants) == list(range(1, 11))
    assert {p["token"] for p in participants if p["participant_id"] != 1} == set(joined)


def test_simultaneous_joins_by_the_same_user_store_one_record(service, repo):
    _, code = new_group(service)
    guest = new_user(service)

    joined, rejected = run_joins_at_the_same_time(service, code, [guest] * 8)

    participants = repo.get_group_order(code)["participants"]
    assert len(joined) == 1
    assert rejected == ["ALREADY_JOINED"] * 7
    assert [p["token"] for p in participants].count(guest) == 1


def test_simultaneous_joins_after_the_deadline_all_get_order_expired(service, repo, fake_clock):
    _, code = new_group(service)
    tokens = [new_user(service) for _ in range(8)]
    fake_clock.advance(TWO_HOURS)

    joined, rejected = run_joins_at_the_same_time(service, code, tokens)

    assert joined == []
    assert rejected == ["ORDER_EXPIRED"] * 8
    group = repo.get_group_order(code)
    assert group["status"] == "EXPIRED"
    assert len(group["participants"]) == 1


# ================================================ R30: what counts as activity


def test_a_successful_join_records_activity(service, repo, fake_clock):
    _, code = new_group(service)
    fake_clock.advance(timedelta(hours=1))

    service.join(new_user(service), code, "Bo")

    assert repo.get_group_order(code)["last_activity_at"] == fake_clock.now().isoformat()


def test_creating_a_group_starts_the_countdown(service, repo, fake_clock):
    fake_clock.advance(timedelta(minutes=7))

    _, code = new_group(service)

    assert repo.get_group_order(code)["last_activity_at"] == fake_clock.now().isoformat()


def test_a_rejected_join_does_not_restart_the_countdown(service, repo, fake_clock):
    host, code = new_group(service)
    created_at = repo.get_group_order(code)["last_activity_at"]
    fake_clock.advance(timedelta(hours=1))

    assert_rejected("ALREADY_JOINED", service.join, host, code, "Hana")
    assert repo.get_group_order(code)["last_activity_at"] == created_at

    fake_clock.advance(timedelta(hours=1))  # exactly 2:00:00 since creation
    assert_rejected("ORDER_EXPIRED", service.join, new_user(service), code, "Bo")


# =================================================== R38: rejected = unchanged


def stored_group(repo, code):
    return repo.get_group_order(code)


def test_rejected_join_already_joined_changes_nothing(service, repo, fake_clock):
    host, code = new_group(service)
    fake_clock.advance(timedelta(minutes=10))
    before = stored_group(repo, code)

    assert_rejected("ALREADY_JOINED", service.join, host, code, "Hana")

    assert stored_group(repo, code) == before


def test_rejected_join_group_full_changes_nothing(service, repo, fake_clock):
    _, code = new_group(service)
    fill_group(service, code, 10)
    fake_clock.advance(timedelta(minutes=10))
    before = stored_group(repo, code)

    assert_rejected("GROUP_FULL", service.join, new_user(service), code, "Eleven")

    assert stored_group(repo, code) == before


@pytest.mark.parametrize(
    ("status", "error_code"),
    [("LOCKED", "ORDER_LOCKED"), ("CHECKED_OUT", "ORDER_CHECKED_OUT")],
)
def test_rejected_join_on_locked_or_checked_out_group_changes_nothing(service, repo, fake_clock, status, error_code):
    _, code = new_group(service)
    set_status(repo, code, status)
    fake_clock.advance(timedelta(minutes=10))
    before = stored_group(repo, code)

    assert_rejected(error_code, service.join, new_user(service), code, "Bo")

    assert stored_group(repo, code) == before


def test_rejected_join_with_invalid_session_changes_nothing(service, repo, fake_clock):
    _, code = new_group(service)
    fake_clock.advance(timedelta(minutes=10))
    before = stored_group(repo, code)

    assert_rejected("INVALID_SESSION", service.join, "never-issued", code, "Bo")

    assert stored_group(repo, code) == before


def test_rejected_join_leaves_participants_and_last_activity_unchanged(service, repo, fake_clock):
    host, code = new_group(service)
    join_new_user(service, code, "Bo")
    participants = stored_group(repo, code)["participants"]
    last_activity = stored_group(repo, code)["last_activity_at"]
    fake_clock.advance(timedelta(minutes=30))

    assert_rejected("ALREADY_JOINED", service.join, host, code, "Hana")

    assert stored_group(repo, code)["participants"] == participants
    assert stored_group(repo, code)["last_activity_at"] == last_activity


# ============================================================ injected clock


def test_all_times_come_from_the_injected_clock(service, repo, data_file):
    # The fake clock is in 2001. Any timestamp from the real clock would be
    # in this decade and fail the checks below.
    host, code = new_group(service)
    join_new_user(service, code)

    data = read_file(data_file)
    group = data["group_orders"][code]
    stamps = [group["created_at"], group["last_activity_at"]]
    stamps += [p["joined_at"] for p in group["participants"]]
    stamps += [s["created_at"] for s in data["sessions"].values()]

    assert all(stamp.startswith("2001-01-01") for stamp in stamps), stamps


# ===================================== the join result tells the joiner which restaurant


def test_join_returns_the_restaurant_of_the_group(service):
    host = service.create_session()
    code = service.create_group_order(host, 1, "Host")["code"]  # restaurant 1

    result = service.join(new_user(service), code, "Bo")

    assert result["restaurant_id"] == 1


def test_join_returns_the_restaurant_for_another_group_too(service):
    _, code = new_group(service, restaurant_id=2)

    assert service.join(new_user(service), code, "Bo")["restaurant_id"] == 2


def test_the_restaurant_is_not_added_to_the_stored_participant(service, repo):
    _, code = new_group(service)
    guest = new_user(service)

    service.join(guest, code, "Bo")

    stored = repo.get_group_order(code)["participants"][1]
    assert set(stored) == {"participant_id", "token", "display_name", "joined_at"}


def test_a_rejected_join_returns_no_restaurant_and_changes_nothing(service, repo):
    host, code = new_group(service)
    before = repo.get_group_order(code)

    assert_rejected("ALREADY_JOINED", service.join, host, code, "Hana")

    assert repo.get_group_order(code) == before
