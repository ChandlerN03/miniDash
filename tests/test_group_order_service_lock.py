import threading
from datetime import datetime, timedelta, timezone

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

RESTAURANT = 2
ITEM_A, ITEM_B = 5, 6  # on the menu of restaurant 2


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


def make_group(service, names=("Host", "Guest"), with_items=True):
    """A group at restaurant 2 whose participants joined in the order of `names`.

    Returns (code, tokens); tokens[0] is the host and participant ids are 1, 2, 3, ...
    If `with_items`, every participant has one item, so the group is ready to lock.
    """
    host = service.create_session()
    code = service.create_group_order(host, RESTAURANT, names[0])["code"]
    tokens = [host]
    for name in names[1:]:
        token = service.create_session()
        service.join(token, code, name)
        tokens.append(token)
    if with_items:
        for pid, token in enumerate(tokens, start=1):
            service.add_item(token, code, pid, ITEM_A, 1)
    return code, tokens


def assert_rejected(code, func, *args):
    with pytest.raises(MiniDashError) as caught:
        func(*args)
    assert caught.value.code == code
    assert isinstance(caught.value.message, str) and caught.value.message
    return caught.value


def set_status(repo, code, status):
    repo.update_group_order(code, lambda group: group.update(status=status))


# ============================================================ R25: a successful lock


def test_the_host_locks_an_open_group_where_everyone_has_an_item(service, repo):
    code, tokens = make_group(service, ["Host", "Bo", "Cy"])

    result = service.lock(tokens[0], code)

    assert result == {"code": code, "status": "LOCKED"}
    assert repo.get_group_order(code)["status"] == "LOCKED"


def test_a_single_host_with_an_item_can_lock(service, repo):
    code, tokens = make_group(service, ["Solo"])

    service.lock(tokens[0], code)

    assert repo.get_group_order(code)["status"] == "LOCKED"


def test_locking_changes_only_the_status_and_last_activity(service, repo, fake_clock):
    code, tokens = make_group(service, ["Host", "Bo"])
    before = repo.get_group_order(code)
    fake_clock.advance(timedelta(minutes=20))

    service.lock(tokens[0], code)

    after = repo.get_group_order(code)
    assert after == {**before, "status": "LOCKED", "last_activity_at": fake_clock.now().isoformat()}


def test_a_participant_who_has_several_items_counts_as_having_items(service, repo):
    code, tokens = make_group(service, ["Host", "Bo"], with_items=False)
    service.add_item(tokens[0], code, 1, ITEM_A, 2)
    service.add_item(tokens[0], code, 1, ITEM_B, 1)
    service.add_item(tokens[1], code, 2, ITEM_B, 9)

    service.lock(tokens[0], code)

    assert repo.get_group_order(code)["status"] == "LOCKED"


def test_the_host_is_the_person_in_host_token_not_just_participant_1(service, repo):
    code, tokens = make_group(service, ["Host", "Bo"])
    repo.update_group_order(code, lambda group: group.update(host_token=tokens[1]))

    assert_rejected("NOT_HOST", service.lock, tokens[0], code)  # former host
    service.lock(tokens[1], code)  # new host

    assert repo.get_group_order(code)["status"] == "LOCKED"


# ============================================ R26: every participant needs an item


def test_a_guest_with_no_items_gives_empty_participant_and_the_status_stays_open(service, repo):
    code, tokens = make_group(service, ["Host", "Bo", "Cy"])
    service.remove_item(tokens[2], code, 3, ITEM_A)  # Cy removes their only item

    error = assert_rejected("EMPTY_PARTICIPANT", service.lock, tokens[0], code)

    assert repo.get_group_order(code)["status"] == "OPEN"
    assert [p["participant_id"] for p in error.participants] == [3]
    assert [p["display_name"] for p in error.participants] == ["Cy"]
    assert "Cy" in error.message


def test_every_empty_participant_is_named_in_join_order(service, repo):
    code, tokens = make_group(service, ["Host", "Amy", "Bob", "Cy", "Di"], with_items=False)
    service.add_item(tokens[0], code, 1, ITEM_A, 1)  # Host has an item
    service.add_item(tokens[3], code, 4, ITEM_A, 1)  # Cy has an item; Amy, Bob and Di do not

    error = assert_rejected("EMPTY_PARTICIPANT", service.lock, tokens[0], code)

    assert [p["display_name"] for p in error.participants] == ["Amy", "Bob", "Di"]
    assert [p["participant_id"] for p in error.participants] == [2, 3, 5]
    for name in ["Amy", "Bob", "Di"]:
        assert name in error.message
    assert "Cy" not in error.message
    assert repo.get_group_order(code)["status"] == "OPEN"


def test_the_host_with_no_items_also_blocks_the_lock(service, repo):
    code, tokens = make_group(service, ["Host", "Bo"], with_items=False)
    service.add_item(tokens[1], code, 2, ITEM_A, 1)

    error = assert_rejected("EMPTY_PARTICIPANT", service.lock, tokens[0], code)

    assert [p["display_name"] for p in error.participants] == ["Host"]
    assert repo.get_group_order(code)["status"] == "OPEN"


def test_a_group_with_nobody_having_items_names_everyone(service):
    code, tokens = make_group(service, ["Host", "Bo"], with_items=False)

    error = assert_rejected("EMPTY_PARTICIPANT", service.lock, tokens[0], code)

    assert [p["display_name"] for p in error.participants] == ["Host", "Bo"]


def test_a_lone_host_without_items_cannot_lock(service, repo):
    code, tokens = make_group(service, ["Solo"], with_items=False)

    error = assert_rejected("EMPTY_PARTICIPANT", service.lock, tokens[0], code)

    assert [p["display_name"] for p in error.participants] == ["Solo"]
    assert repo.get_group_order(code)["status"] == "OPEN"


def test_participants_with_the_same_name_are_told_apart_by_id(service):
    code, tokens = make_group(service, ["Host", "Sam", "Sam"])
    service.remove_item(tokens[2], code, 3, ITEM_A)

    error = assert_rejected("EMPTY_PARTICIPANT", service.lock, tokens[0], code)

    assert [p["participant_id"] for p in error.participants] == [3]


def test_the_host_removing_a_guests_only_item_makes_the_guest_empty(service, repo):
    code, tokens = make_group(service, ["Host", "Bo"])
    service.remove_item(tokens[0], code, 2, ITEM_A)  # R18: host removes Bo's item

    error = assert_rejected("EMPTY_PARTICIPANT", service.lock, tokens[0], code)

    assert [p["display_name"] for p in error.participants] == ["Bo"]


def test_the_group_can_be_locked_once_the_empty_participant_adds_an_item(service, repo):
    code, tokens = make_group(service, ["Host", "Bo"])
    service.remove_item(tokens[1], code, 2, ITEM_A)
    assert_rejected("EMPTY_PARTICIPANT", service.lock, tokens[0], code)

    service.add_item(tokens[1], code, 2, ITEM_B, 1)
    service.lock(tokens[0], code)

    assert repo.get_group_order(code)["status"] == "LOCKED"


def test_a_rejected_empty_participant_lock_changes_nothing(service, repo, fake_clock):
    code, tokens = make_group(service, ["Host", "Bo"])
    service.remove_item(tokens[1], code, 2, ITEM_A)
    fake_clock.advance(timedelta(minutes=45))
    before = repo.get_group_order(code)

    assert_rejected("EMPTY_PARTICIPANT", service.lock, tokens[0], code)

    assert repo.get_group_order(code) == before  # status, items and last_activity_at


# ================================================================ R27: not the host


def test_a_guest_cannot_lock_and_gets_not_host(service, repo, fake_clock):
    code, tokens = make_group(service, ["Host", "Bo"])
    fake_clock.advance(timedelta(minutes=10))
    before = repo.get_group_order(code)

    assert_rejected("NOT_HOST", service.lock, tokens[1], code)

    assert repo.get_group_order(code) == before


def test_a_user_who_is_not_in_the_group_gets_not_host(service, repo):
    code, _ = make_group(service)
    outsider = service.create_session()
    before = repo.get_group_order(code)

    assert_rejected("NOT_HOST", service.lock, outsider, code)

    assert repo.get_group_order(code) == before


def test_not_host_comes_before_empty_participant(service):
    code, tokens = make_group(service, ["Host", "Bo"])
    service.remove_item(tokens[1], code, 2, ITEM_A)

    assert_rejected("NOT_HOST", service.lock, tokens[1], code)


# ============================================================ sessions and codes


@pytest.mark.parametrize("token", [None, "", "never-issued"])
def test_a_missing_or_unknown_session_gives_invalid_session(service, repo, token):
    code, _ = make_group(service)

    assert_rejected("INVALID_SESSION", service.lock, token, code)

    assert repo.get_group_order(code)["status"] == "OPEN"


def test_a_wrong_code_gives_invalid_code(service):
    _, tokens = make_group(service)

    assert_rejected("INVALID_CODE", service.lock, tokens[0], "nope42")


def test_invalid_session_is_checked_before_invalid_code(service):
    assert_rejected("INVALID_SESSION", service.lock, "never-issued", "nope42")


# ===================================================== the group is not open anymore


def test_locking_an_already_locked_group_gives_order_locked(service, repo, fake_clock):
    code, tokens = make_group(service)
    service.lock(tokens[0], code)
    fake_clock.advance(timedelta(minutes=10))
    before = repo.get_group_order(code)

    assert_rejected("ORDER_LOCKED", service.lock, tokens[0], code)

    assert repo.get_group_order(code) == before


def test_locking_a_checked_out_group_gives_order_checked_out(service, repo):
    code, tokens = make_group(service)
    set_status(repo, code, "CHECKED_OUT")

    assert_rejected("ORDER_CHECKED_OUT", service.lock, tokens[0], code)

    assert repo.get_group_order(code)["status"] == "CHECKED_OUT"


def test_locking_an_expired_group_gives_order_expired(service, repo):
    code, tokens = make_group(service)
    set_status(repo, code, "EXPIRED")

    assert_rejected("ORDER_EXPIRED", service.lock, tokens[0], code)

    assert repo.get_group_order(code)["status"] == "EXPIRED"


def test_the_status_errors_come_before_not_host(service, repo):
    code, tokens = make_group(service, ["Host", "Bo"])

    set_status(repo, code, "EXPIRED")
    assert_rejected("ORDER_EXPIRED", service.lock, tokens[1], code)
    set_status(repo, code, "CHECKED_OUT")
    assert_rejected("ORDER_CHECKED_OUT", service.lock, tokens[1], code)
    set_status(repo, code, "LOCKED")
    assert_rejected("ORDER_LOCKED", service.lock, tokens[1], code)


def test_the_status_errors_come_before_empty_participant(service, repo):
    code, tokens = make_group(service, ["Host", "Bo"])
    service.remove_item(tokens[1], code, 2, ITEM_A)
    set_status(repo, code, "EXPIRED")

    assert_rejected("ORDER_EXPIRED", service.lock, tokens[0], code)


# ===================================================== R31, R32: expiry on lock


def test_locking_at_1_59_59_still_works(service, repo, fake_clock):
    code, tokens = make_group(service)
    fake_clock.advance(TWO_HOURS - ONE_SECOND)

    service.lock(tokens[0], code)

    assert repo.get_group_order(code)["status"] == "LOCKED"


def test_locking_at_exactly_2_hours_gives_order_expired_and_saves_expired(service, repo, fake_clock):
    code, tokens = make_group(service)
    before = repo.get_group_order(code)
    fake_clock.advance(TWO_HOURS)

    assert_rejected("ORDER_EXPIRED", service.lock, tokens[0], code)

    assert repo.get_group_order(code) == {**before, "status": "EXPIRED"}  # saved; nothing else changed


def test_locking_after_2_hours_and_1_second_gives_order_expired(service, repo, fake_clock):
    code, tokens = make_group(service)
    fake_clock.advance(TWO_HOURS + ONE_SECOND)

    assert_rejected("ORDER_EXPIRED", service.lock, tokens[0], code)

    assert repo.get_group_order(code)["status"] == "EXPIRED"


def test_a_non_host_on_an_expired_group_gets_order_expired_not_not_host(service, fake_clock):
    code, tokens = make_group(service, ["Host", "Bo"])
    fake_clock.advance(TWO_HOURS)

    assert_rejected("ORDER_EXPIRED", service.lock, tokens[1], code)


def test_an_expired_group_with_an_empty_participant_gives_order_expired(service, fake_clock):
    code, tokens = make_group(service, ["Host", "Bo"])
    service.remove_item(tokens[1], code, 2, ITEM_A)
    fake_clock.advance(TWO_HOURS)

    assert_rejected("ORDER_EXPIRED", service.lock, tokens[0], code)


# ===================================================== R30: lock is activity


def test_a_successful_lock_moves_last_activity(service, repo, fake_clock):
    code, tokens = make_group(service)
    fake_clock.advance(timedelta(hours=1))

    service.lock(tokens[0], code)

    assert repo.get_group_order(code)["last_activity_at"] == fake_clock.now().isoformat()


def test_a_successful_lock_restarts_the_countdown_for_the_locked_group(service, repo, fake_clock):
    code, tokens = make_group(service)
    fake_clock.advance(timedelta(hours=1, minutes=30))
    service.lock(tokens[0], code)  # activity at 1:30

    fake_clock.advance(TWO_HOURS - ONE_SECOND)  # 1:59:59 after the lock
    assert service.get_summary(tokens[0], code)["status"] == "LOCKED"

    fake_clock.advance(ONE_SECOND)  # exactly 2:00:00 after the lock
    assert service.get_summary(tokens[0], code)["status"] == "EXPIRED"
    assert repo.get_group_order(code)["status"] == "EXPIRED"


def test_a_locked_group_can_expire(service, repo, fake_clock):
    code, tokens = make_group(service)
    service.lock(tokens[0], code)
    fake_clock.advance(TWO_HOURS)

    assert_rejected("ORDER_EXPIRED", service.lock, tokens[0], code)

    assert repo.get_group_order(code)["status"] == "EXPIRED"


def test_a_rejected_lock_does_not_restart_the_countdown(service, repo, fake_clock):
    code, tokens = make_group(service, ["Host", "Bo"])
    fake_clock.advance(timedelta(hours=1))
    assert_rejected("NOT_HOST", service.lock, tokens[1], code)
    service.remove_item(tokens[1], code, 2, ITEM_A)  # activity at 1:00 (a real change)
    fake_clock.advance(timedelta(minutes=30))
    assert_rejected("EMPTY_PARTICIPANT", service.lock, tokens[0], code)

    assert repo.get_group_order(code)["last_activity_at"] == (START + timedelta(hours=1)).isoformat()

    fake_clock.advance(timedelta(hours=1, minutes=30))  # clock is at 3:00, exactly 2:00:00 after the remove at 1:00
    assert_rejected("ORDER_EXPIRED", service.lock, tokens[0], code)


# ============================================ what a locked group does afterwards


def test_items_cannot_change_after_the_lock(service, repo):
    code, tokens = make_group(service, ["Host", "Bo"])
    service.lock(tokens[0], code)
    before = repo.get_group_order(code)

    assert_rejected("ORDER_LOCKED", service.add_item, tokens[1], code, 2, ITEM_B, 1)
    assert_rejected("ORDER_LOCKED", service.change_item, tokens[1], code, 2, ITEM_A, 3)
    assert_rejected("ORDER_LOCKED", service.remove_item, tokens[1], code, 2, ITEM_A)
    assert_rejected("ORDER_LOCKED", service.remove_item, tokens[0], code, 2, ITEM_A)  # even the host

    assert repo.get_group_order(code) == before


def test_nobody_can_join_after_the_lock(service, repo):
    code, tokens = make_group(service, ["Host", "Bo"])
    service.lock(tokens[0], code)

    assert_rejected("ORDER_LOCKED", service.join, service.create_session(), code, "Late")

    assert len(repo.get_group_order(code)["participants"]) == 2


def test_the_summary_still_works_after_the_lock(service):
    code, tokens = make_group(service, ["Host", "Bo", "Cy"])
    service.lock(tokens[0], code)

    summary = service.get_summary(tokens[2], code)

    assert summary["status"] == "LOCKED"
    assert sum(e["fee_share_cents"] for e in summary["participants"]) == 499


# ============================================== simultaneous requests (no lost updates)


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


def test_simultaneous_locks_succeed_exactly_once(service, repo):
    code, tokens = make_group(service, ["Host", "Bo"])

    results, rejected = run_at_the_same_time([lambda: service.lock(tokens[0], code) for _ in range(8)])

    assert len(results) == 1
    assert rejected == ["ORDER_LOCKED"] * 7
    assert repo.get_group_order(code)["status"] == "LOCKED"


def test_a_group_is_never_locked_with_an_empty_participant(service, repo):
    """The guest removes their only item while the host locks, many times over.

    Either the lock wins (the guest's removal is then rejected with ORDER_LOCKED) or the
    removal wins (the lock is then rejected with EMPTY_PARTICIPANT). So exactly one of the
    two requests is rejected, and a LOCKED group never has an empty participant. If the
    requests could overlap, both would succeed and the removal would be overwritten.
    """
    for round_number in range(30):
        code, tokens = make_group(service, ["Host", "Bo"])
        jobs = [
            lambda: service.lock(tokens[0], code),
            lambda: service.remove_item(tokens[1], code, 2, ITEM_A),
        ]
        if round_number % 2:
            jobs.reverse()  # the last thread to reach the barrier tends to run first, so alternate

        _, rejected = run_at_the_same_time(jobs)

        group = repo.get_group_order(code)
        guest_items = [i for i in group["items"] if i["participant_id"] == 2]
        assert len(rejected) == 1 and rejected[0] in ("ORDER_LOCKED", "EMPTY_PARTICIPANT"), rejected
        if rejected == ["ORDER_LOCKED"]:
            assert group["status"] == "LOCKED" and len(guest_items) == 1
        else:
            assert group["status"] == "OPEN" and guest_items == []


def test_an_item_added_at_the_same_moment_as_the_lock_is_either_kept_or_rejected(service, repo):
    for _ in range(15):
        code, tokens = make_group(service, ["Host", "Bo"])

        _, rejected = run_at_the_same_time(
            [
                lambda: service.lock(tokens[0], code),
                lambda: service.add_item(tokens[1], code, 2, ITEM_B, 1),
            ]
        )

        group = repo.get_group_order(code)
        added = any(i["menu_item_id"] == ITEM_B for i in group["items"])
        assert group["status"] == "LOCKED"  # the lock always succeeds here
        assert added == ("ORDER_LOCKED" not in rejected)


# ================================================================ injected clock


def test_locking_uses_only_the_injected_clock(service, repo, fake_clock):
    code, tokens = make_group(service)
    fake_clock.advance(timedelta(minutes=5))

    service.lock(tokens[0], code)

    assert repo.get_group_order(code)["last_activity_at"] == (START + timedelta(minutes=5)).isoformat()
