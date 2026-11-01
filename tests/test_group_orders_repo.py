import copy
import json
import threading
import time
from datetime import datetime

import pytest

from src.repository.group_orders_repo import (
    REQUIRED_FIELDS,
    DuplicateShareCodeError,
    GroupOrderNotFoundError,
    GroupOrderRepository,
)
from src.repository.orders_repo import OrderRepository
from src.store import file_store
from src.store.file_store import FileStore
from src.store.seed import SEED_DATA


def open_repo(data_file) -> GroupOrderRepository:
    """Open the data file the way the app does: store, seed, repository."""
    store = FileStore(data_file)
    store.initialize(SEED_DATA)
    return GroupOrderRepository(store)


@pytest.fixture
def repo(data_file):
    return open_repo(data_file)


def make_group(clock, code="Ab3dEf", **overrides) -> dict:
    now = clock.now().isoformat()
    group = {
        "code": code,
        "id": 1,
        "restaurant_id": 2,
        "host_token": "tok-host",
        "status": "OPEN",
        "last_activity_at": now,
        "order_id": None,
        "created_at": now,
        "participants": [
            {"participant_id": 1, "token": "tok-host", "display_name": "Host", "joined_at": now},
        ],
        "items": [
            {"participant_id": 1, "menu_item_id": 5, "quantity": 2},
        ],
    }
    group.update(overrides)
    return group


def participant(participant_id: int, name: str, clock) -> dict:
    return {
        "participant_id": participant_id,
        "token": f"tok-{participant_id}",
        "display_name": name,
        "joined_at": clock.now().isoformat(),
    }


def read_file(data_file) -> dict:
    return json.loads(data_file.read_text())


# ------------------------------------------------------ saved data loads back unchanged


def test_saved_group_loads_back_unchanged(repo, clock):
    group = make_group(clock)

    repo.create_group_order(group)

    assert repo.get_group_order("Ab3dEf") == group


def test_group_with_several_participants_and_items_loads_back_unchanged(repo, clock):
    group = make_group(
        clock,
        participants=[participant(1, "Host", clock), participant(2, "Bo", clock), participant(3, "Cy", clock)],
        items=[
            {"participant_id": 1, "menu_item_id": 5, "quantity": 2},
            {"participant_id": 2, "menu_item_id": 6, "quantity": 1},
            {"participant_id": 2, "menu_item_id": 7, "quantity": 9},
        ],
    )

    repo.create_group_order(group)

    assert repo.get_group_order("Ab3dEf") == group


def test_group_is_still_there_when_the_file_is_opened_again(data_file, clock):
    group = make_group(clock)
    open_repo(data_file).create_group_order(group)

    assert open_repo(data_file).get_group_order("Ab3dEf") == group


def test_group_is_stored_in_the_file_under_its_share_code(repo, data_file, clock):
    group = make_group(clock)

    repo.create_group_order(group)

    assert read_file(data_file)["group_orders"]["Ab3dEf"] == group


def test_get_group_order_returns_none_for_an_unknown_code(repo):
    assert repo.get_group_order("nope42") is None


def test_changing_a_loaded_group_does_not_change_the_stored_one(repo, clock):
    repo.create_group_order(make_group(clock))

    loaded = repo.get_group_order("Ab3dEf")
    loaded["status"] = "LOCKED"
    loaded["participants"].clear()

    assert repo.get_group_order("Ab3dEf") == make_group(clock)


def test_changing_the_dict_after_create_does_not_change_the_stored_group(repo, clock):
    group = make_group(clock)
    repo.create_group_order(group)

    group["status"] = "LOCKED"

    assert repo.get_group_order("Ab3dEf")["status"] == "OPEN"


# ------------------------------------------------------------ created_at (date and time)


def test_each_group_keeps_its_own_created_at(repo, clock):
    first = make_group(clock, code="aaaaaa", created_at="2026-10-30T09:15:00+00:00")
    second = make_group(clock, code="bbbbbb", created_at="2026-10-31T18:45:30+00:00")

    repo.create_group_order(first)
    repo.create_group_order(second)

    assert repo.get_group_order("aaaaaa")["created_at"] == "2026-10-30T09:15:00+00:00"
    assert repo.get_group_order("bbbbbb")["created_at"] == "2026-10-31T18:45:30+00:00"


def test_stored_created_at_is_a_date_and_time_that_can_be_parsed(repo, clock):
    repo.create_group_order(make_group(clock))

    created_at = repo.get_group_order("Ab3dEf")["created_at"]

    assert datetime.fromisoformat(created_at) == clock.now()


def test_created_at_is_not_changed_by_saving_the_group(repo, clock):
    repo.create_group_order(make_group(clock))
    group = repo.get_group_order("Ab3dEf")
    group["status"] = "LOCKED"

    repo.save_group_order(group)

    assert repo.get_group_order("Ab3dEf")["created_at"] == clock.now().isoformat()


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_group_missing_a_field_is_rejected_and_not_stored(repo, data_file, clock, field):
    group = make_group(clock)
    del group[field]
    before = data_file.read_text()

    with pytest.raises(ValueError, match=field):
        repo.create_group_order(group)

    assert data_file.read_text() == before


def test_required_fields_are_the_ones_in_the_slice_spec():
    assert set(REQUIRED_FIELDS) == {
        "code",
        "id",
        "restaurant_id",
        "host_token",
        "status",
        "last_activity_at",
        "order_id",
        "created_at",
        "participants",
        "items",
    }


# --------------------------------------------------- no two groups under one code (R6)


def test_creating_a_group_under_an_existing_code_raises(repo, clock):
    repo.create_group_order(make_group(clock))

    with pytest.raises(DuplicateShareCodeError):
        repo.create_group_order(make_group(clock, id=2, host_token="tok-other"))


def test_the_first_group_is_kept_when_a_duplicate_code_is_rejected(repo, data_file, clock):
    first = make_group(clock)
    repo.create_group_order(first)
    before = data_file.read_text()

    with pytest.raises(DuplicateShareCodeError):
        repo.create_group_order(make_group(clock, id=2, host_token="tok-other", status="LOCKED"))

    assert repo.get_group_order("Ab3dEf") == first
    assert data_file.read_text() == before


def test_a_code_stays_taken_after_the_group_is_expired_or_checked_out(repo, clock):
    for status in ["EXPIRED", "CHECKED_OUT"]:
        code = f"code-{status}"
        repo.create_group_order(make_group(clock, code=code, status=status))

        with pytest.raises(DuplicateShareCodeError):
            repo.create_group_order(make_group(clock, code=code, id=99))

        assert repo.get_group_order(code)["status"] == status


def test_codes_that_differ_only_in_case_are_different_codes(repo, clock):
    repo.create_group_order(make_group(clock, code="abcdef", id=1))
    repo.create_group_order(make_group(clock, code="ABCDEF", id=2))

    assert repo.get_group_order("abcdef")["id"] == 1
    assert repo.get_group_order("ABCDEF")["id"] == 2


def test_groups_with_different_codes_are_stored_side_by_side(repo, clock):
    repo.create_group_order(make_group(clock, code="aaaaaa", id=1))
    repo.create_group_order(make_group(clock, code="bbbbbb", id=2))
    repo.create_group_order(make_group(clock, code="cccccc", id=3))

    assert [repo.get_group_order(c)["id"] for c in ["aaaaaa", "bbbbbb", "cccccc"]] == [1, 2, 3]


# ----------------------------------------------------------------- join order is kept


def test_participants_keep_join_order(repo, clock):
    names = ["Zed", "Amy", "Mia", "Bob", "Yan"]  # not alphabetical on purpose
    group = make_group(
        clock,
        participants=[participant(i, name, clock) for i, name in enumerate(names, start=1)],
    )

    repo.create_group_order(group)

    stored = repo.get_group_order("Ab3dEf")["participants"]
    assert [p["display_name"] for p in stored] == names
    assert [p["participant_id"] for p in stored] == [1, 2, 3, 4, 5]


def test_participants_keep_join_order_when_the_file_is_opened_again(data_file, clock):
    names = ["Zed", "Amy", "Mia"]
    group = make_group(
        clock,
        participants=[participant(i, name, clock) for i, name in enumerate(names, start=1)],
    )
    open_repo(data_file).create_group_order(group)

    stored = open_repo(data_file).get_group_order("Ab3dEf")["participants"]

    assert [p["display_name"] for p in stored] == names


def test_a_participant_who_joins_later_stays_last_after_saving(repo, clock):
    repo.create_group_order(
        make_group(clock, participants=[participant(1, "Zed", clock), participant(2, "Amy", clock)])
    )

    group = repo.get_group_order("Ab3dEf")
    group["participants"].append(participant(3, "Abe", clock))
    repo.save_group_order(group)

    stored = repo.get_group_order("Ab3dEf")["participants"]
    assert [p["display_name"] for p in stored] == ["Zed", "Amy", "Abe"]


def test_items_keep_their_order_and_values(repo, clock):
    items = [
        {"participant_id": 2, "menu_item_id": 8, "quantity": 3},
        {"participant_id": 1, "menu_item_id": 5, "quantity": 1},
        {"participant_id": 2, "menu_item_id": 6, "quantity": 9},
    ]
    repo.create_group_order(make_group(clock, items=items))

    assert repo.get_group_order("Ab3dEf")["items"] == items


# -------------------------------------------------------------------- save_group_order


def test_saving_a_changed_group_stores_the_change(repo, clock):
    repo.create_group_order(make_group(clock))
    group = repo.get_group_order("Ab3dEf")
    group["status"] = "LOCKED"
    group["last_activity_at"] = "2026-10-30T12:30:00+00:00"
    group["items"].append({"participant_id": 1, "menu_item_id": 6, "quantity": 1})

    repo.save_group_order(group)

    assert repo.get_group_order("Ab3dEf") == group


def test_saving_one_group_leaves_other_groups_unchanged(repo, clock):
    repo.create_group_order(make_group(clock, code="aaaaaa", id=1))
    other = make_group(clock, code="bbbbbb", id=2)
    repo.create_group_order(other)
    group = repo.get_group_order("aaaaaa")
    group["status"] = "LOCKED"

    repo.save_group_order(group)

    assert repo.get_group_order("bbbbbb") == other


def test_saving_an_unknown_code_raises_and_does_not_create_a_group(repo, clock):
    with pytest.raises(GroupOrderNotFoundError):
        repo.save_group_order(make_group(clock, code="nope42"))

    assert repo.get_group_order("nope42") is None


def test_saving_a_group_with_a_missing_field_is_rejected(repo, clock):
    repo.create_group_order(make_group(clock))
    group = repo.get_group_order("Ab3dEf")
    del group["created_at"]
    group["status"] = "LOCKED"

    with pytest.raises(ValueError, match="created_at"):
        repo.save_group_order(group)

    assert repo.get_group_order("Ab3dEf")["status"] == "OPEN"


# -------------------------------------------------------------------------- sessions


def test_a_stored_session_can_be_looked_up(repo):
    repo.create_session("token-1")

    assert repo.session_exists("token-1") is True


def test_an_unknown_session_does_not_exist(repo):
    assert repo.session_exists("never-issued") is False


def test_session_exists_is_false_before_any_session_is_created(repo):
    assert repo.session_exists("token-1") is False


def test_several_sessions_are_stored_independently(repo):
    repo.create_session("token-1")
    repo.create_session("token-2")

    assert repo.session_exists("token-1") is True
    assert repo.session_exists("token-2") is True
    assert repo.session_exists("token-3") is False


def test_session_tokens_are_case_sensitive(repo):
    repo.create_session("AbCdEf")

    assert repo.session_exists("abcdef") is False


def test_sessions_are_still_there_when_the_file_is_opened_again(data_file):
    open_repo(data_file).create_session("token-1")

    assert open_repo(data_file).session_exists("token-1") is True


def test_session_is_stored_with_its_created_time(repo, data_file, clock):
    repo.create_session("token-1", created_at=clock.now().isoformat())

    stored = read_file(data_file)["sessions"]["token-1"]
    assert datetime.fromisoformat(stored["created_at"]) == clock.now()


def test_creating_the_same_session_twice_keeps_the_first_one(repo, data_file):
    repo.create_session("token-1", created_at="2026-10-30T09:00:00+00:00")

    repo.create_session("token-1", created_at="2026-10-30T10:00:00+00:00")

    assert read_file(data_file)["sessions"]["token-1"]["created_at"] == "2026-10-30T09:00:00+00:00"


# -------------------------------------- restaurants and orders are not affected


def test_group_and_session_writes_leave_restaurants_menus_and_orders_unchanged(repo, data_file, clock):
    before = read_file(data_file)

    repo.create_session("token-1")
    repo.create_group_order(make_group(clock))
    group = repo.get_group_order("Ab3dEf")
    group["status"] = "LOCKED"
    repo.save_group_order(group)

    after = read_file(data_file)
    for collection in ["restaurants", "menu_items", "orders", "order_items"]:
        assert after[collection] == before[collection]


def test_orders_still_work_next_to_group_orders(data_file, clock):
    store = FileStore(data_file)
    store.initialize(SEED_DATA)
    group_repo = GroupOrderRepository(store)
    order_repo = OrderRepository(store)

    group_repo.create_group_order(make_group(clock))
    order = order_repo.add(
        restaurant_id=2,
        status="PLACED",
        total_cents=1798,
        address="5 Oak Ave",
        created_at=clock.now().isoformat(),
        items=[{"menu_item_id": 5, "quantity": 2, "unit_price_cents": 899}],
    )

    assert order_repo.get(order["id"])["total_cents"] == 1798
    assert group_repo.get_group_order("Ab3dEf") == make_group(clock)


# ------------------------------------------------------------- the file store itself


def test_a_new_data_file_gets_empty_sessions_and_group_orders(data_file):
    FileStore(data_file).initialize(SEED_DATA)

    data = read_file(data_file)
    assert data["sessions"] == {}
    assert data["group_orders"] == {}


def test_an_older_data_file_gets_the_new_collections_without_losing_anything(data_file):
    old_data = copy.deepcopy(SEED_DATA)
    del old_data["sessions"]
    del old_data["group_orders"]
    old_data["orders"].append(
        {
            "id": 1,
            "restaurant_id": 2,
            "status": "PLACED",
            "total_cents": 1798,
            "address": "5 Oak Ave",
            "created_at": "2026-10-30T09:00:00+00:00",
        }
    )
    data_file.write_text(json.dumps(old_data))

    FileStore(data_file).initialize(SEED_DATA)

    data = read_file(data_file)
    assert data["sessions"] == {}
    assert data["group_orders"] == {}
    for collection in ["restaurants", "menu_items", "orders", "order_items"]:
        assert data[collection] == old_data[collection]


def test_initialize_does_not_change_collections_that_already_have_data(data_file, clock):
    repo = open_repo(data_file)
    repo.create_session("token-1")
    repo.create_group_order(make_group(clock))
    before = read_file(data_file)

    open_repo(data_file)  # app restart

    assert read_file(data_file) == before


def test_a_crash_while_writing_leaves_the_real_file_unchanged(repo, data_file, clock):
    repo.create_group_order(make_group(clock, code="aaaaaa"))
    before = data_file.read_text()

    def crashing_dump(obj, fp, **kwargs):
        fp.write('{"restaurants": [ {"id": 1, "na')  # half a file, then the "crash"
        raise OSError("disk full")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(file_store.json, "dump", crashing_dump)
        with pytest.raises(OSError):
            repo.create_group_order(make_group(clock, code="bbbbbb"))

    assert data_file.read_text() == before
    assert read_file(data_file)["group_orders"].keys() == {"aaaaaa"}
    assert list(data_file.parent.glob(".minidash-*.tmp")) == []
    assert repo.get_group_order("bbbbbb") is None


# ------------------------------------------------- update_group_order (atomic change)


def test_update_applies_the_change_and_stores_it(repo, clock):
    repo.create_group_order(make_group(clock))

    def lock(group):
        group["status"] = "LOCKED"

    repo.update_group_order("Ab3dEf", lock)

    assert repo.get_group_order("Ab3dEf")["status"] == "LOCKED"


def test_update_returns_what_the_change_function_returns(repo, clock):
    repo.create_group_order(make_group(clock))

    result = repo.update_group_order("Ab3dEf", lambda group: len(group["participants"]))

    assert result == 1


def test_update_gives_the_change_function_the_stored_group(repo, clock):
    group = make_group(clock)
    repo.create_group_order(group)
    seen = []

    repo.update_group_order("Ab3dEf", lambda stored: seen.append(copy.deepcopy(stored)))

    assert seen == [group]


def test_update_keeps_participant_join_order(repo, clock):
    repo.create_group_order(make_group(clock, participants=[participant(1, "Zed", clock)]))

    repo.update_group_order("Ab3dEf", lambda g: g["participants"].append(participant(2, "Amy", clock)))
    repo.update_group_order("Ab3dEf", lambda g: g["participants"].append(participant(3, "Abe", clock)))

    names = [p["display_name"] for p in repo.get_group_order("Ab3dEf")["participants"]]
    assert names == ["Zed", "Amy", "Abe"]


def test_update_leaves_other_groups_unchanged(repo, clock):
    repo.create_group_order(make_group(clock, code="aaaaaa", id=1))
    other = make_group(clock, code="bbbbbb", id=2)
    repo.create_group_order(other)

    repo.update_group_order("aaaaaa", lambda g: g.update(status="LOCKED"))

    assert repo.get_group_order("bbbbbb") == other


def test_update_survives_reopening_the_file(data_file, clock):
    open_repo(data_file).create_group_order(make_group(clock))

    open_repo(data_file).update_group_order("Ab3dEf", lambda g: g.update(status="LOCKED"))

    assert open_repo(data_file).get_group_order("Ab3dEf")["status"] == "LOCKED"


def test_update_unknown_code_raises_and_never_calls_the_change_function(repo):
    calls = []

    with pytest.raises(GroupOrderNotFoundError):
        repo.update_group_order("nope42", lambda group: calls.append(group))

    assert calls == []
    assert repo.get_group_order("nope42") is None


def test_update_stores_nothing_when_the_change_function_raises(repo, data_file, clock):
    repo.create_group_order(make_group(clock))
    before = data_file.read_text()

    def half_done(group):
        group["status"] = "LOCKED"  # changed, then fails
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        repo.update_group_order("Ab3dEf", half_done)

    assert data_file.read_text() == before
    assert repo.get_group_order("Ab3dEf")["status"] == "OPEN"


def test_update_rejects_a_change_that_removes_a_required_field(repo, data_file, clock):
    repo.create_group_order(make_group(clock))
    before = data_file.read_text()

    with pytest.raises(ValueError, match="created_at"):
        repo.update_group_order("Ab3dEf", lambda group: group.pop("created_at"))

    assert data_file.read_text() == before


def test_update_can_keep_a_change_and_report_a_problem_to_the_caller(repo, clock):
    """The change function returns a problem instead of raising, so its change is saved."""
    repo.create_group_order(make_group(clock))

    def expire_and_report(group):
        group["status"] = "EXPIRED"
        return "ORDER_EXPIRED"

    assert repo.update_group_order("Ab3dEf", expire_and_report) == "ORDER_EXPIRED"
    assert repo.get_group_order("Ab3dEf")["status"] == "EXPIRED"


def test_simultaneous_updates_are_not_lost(repo, clock):
    repo.create_group_order(make_group(clock, participants=[participant(1, "Host", clock)]))
    total = 20
    barrier = threading.Barrier(total)

    def add_participant(number):
        def change(group):
            time.sleep(0.002)  # widens the window in which a lost update could happen
            group["participants"].append(participant(number, f"P{number}", clock))

        barrier.wait()
        repo.update_group_order("Ab3dEf", change)

    threads = [threading.Thread(target=add_participant, args=(n,)) for n in range(2, total + 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    ids = sorted(p["participant_id"] for p in repo.get_group_order("Ab3dEf")["participants"])
    assert ids == [1] + list(range(2, total + 2))


def test_each_simultaneous_update_sees_the_previous_one(repo, clock):
    repo.create_group_order(make_group(clock, participants=[participant(1, "Host", clock)]))
    total = 15
    barrier = threading.Barrier(total)
    seen_sizes = []

    def add_participant(number):
        def change(group):
            seen_sizes.append(len(group["participants"]))
            time.sleep(0.001)
            group["participants"].append(participant(number, f"P{number}", clock))

        barrier.wait()
        repo.update_group_order("Ab3dEf", change)

    threads = [threading.Thread(target=add_participant, args=(n,)) for n in range(2, total + 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(seen_sizes) == list(range(1, total + 1))  # each saw a different, growing size


# ----------------------------------------- FileStore transactions can be nested


@pytest.fixture
def store(data_file):
    file_store_ = FileStore(data_file)
    file_store_.initialize(SEED_DATA)
    return file_store_


def test_a_nested_transaction_changes_are_saved_with_the_outer_one(store, data_file):
    with store.transaction() as outer:
        outer["sessions"]["outer"] = {"created_at": None}
        with store.transaction() as inner:
            inner["sessions"]["inner"] = {"created_at": None}

    assert set(read_file(data_file)["sessions"]) == {"outer", "inner"}


def test_the_nested_transaction_works_on_the_same_data_as_the_outer_one(store):
    with store.transaction() as outer:
        with store.transaction() as inner:
            inner["sessions"]["inner"] = {"created_at": None}
        assert "inner" in outer["sessions"]  # the outer one sees the inner change immediately


def test_a_nested_transaction_does_not_overwrite_the_inner_change(store, data_file, clock):
    """The bug this fixes: an order created inside a group update used to be lost."""
    orders = OrderRepository(store)
    repo = GroupOrderRepository(store)
    repo.create_group_order(make_group(clock))

    def update(group):
        orders.add(  # opens its own transaction inside the group update
            restaurant_id=2,
            status="PLACED",
            total_cents=100,
            address="5 Oak Ave",
            created_at=clock.now().isoformat(),
            items=[{"menu_item_id": 5, "quantity": 1, "unit_price_cents": 100}],
        )
        group["status"] = "CHECKED_OUT"

    repo.update_group_order("Ab3dEf", update)

    data = read_file(data_file)
    assert len(data["orders"]) == 1
    assert data["group_orders"]["Ab3dEf"]["status"] == "CHECKED_OUT"


def test_nested_transactions_write_the_file_only_once(store, monkeypatch):
    real_replace = file_store.os.replace
    writes = []
    monkeypatch.setattr(file_store.os, "replace", lambda *args: (writes.append(args), real_replace(*args))[1])

    with store.transaction():
        with store.transaction():
            with store.transaction():
                pass

    assert len(writes) == 1


def test_if_the_outer_transaction_fails_the_inner_change_is_not_saved_either(store, data_file):
    before = data_file.read_text()

    with pytest.raises(RuntimeError):
        with store.transaction():
            with store.transaction() as inner:
                inner["sessions"]["inner"] = {"created_at": None}
            raise RuntimeError("boom")

    assert data_file.read_text() == before


def test_if_the_inner_transaction_fails_nothing_is_saved_when_it_propagates(store, data_file):
    before = data_file.read_text()

    with pytest.raises(RuntimeError):
        with store.transaction() as outer:
            outer["sessions"]["outer"] = {"created_at": None}
            with store.transaction() as inner:
                inner["sessions"]["inner"] = {"created_at": None}
                raise RuntimeError("boom")

    assert data_file.read_text() == before


def test_a_failed_inner_transaction_is_undone_even_if_the_outer_one_carries_on(store, data_file):
    with store.transaction() as outer:
        outer["sessions"]["before"] = {"created_at": None}
        try:
            with store.transaction() as inner:
                inner["sessions"]["half-done"] = {"created_at": None}
                inner["orders"].append({"id": 99})
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        outer["sessions"]["after"] = {"created_at": None}

    data = read_file(data_file)
    assert set(data["sessions"]) == {"before", "after"}  # the failed inner change is gone
    assert data["orders"] == []


def test_the_store_works_normally_again_after_a_failed_transaction(store, data_file):
    with pytest.raises(RuntimeError):
        with store.transaction():
            with store.transaction():
                raise RuntimeError("boom")

    with store.transaction() as data:  # must be a normal top-level transaction, not "nested"
        data["sessions"]["later"] = {"created_at": None}

    assert "later" in read_file(data_file)["sessions"]


def test_reading_inside_a_transaction_sees_the_changes_made_so_far(store, data_file):
    with store.transaction() as data:
        data["sessions"]["draft"] = {"created_at": None}

        assert "draft" in store.read()["sessions"]  # same thread: sees its own uncommitted change
        assert "draft" not in read_file(data_file)["sessions"]  # but the file is not written yet


def test_a_read_inside_a_transaction_is_a_copy(store):
    with store.transaction() as data:
        snapshot = store.read()
        snapshot["sessions"]["scribble"] = {"created_at": None}

        assert "scribble" not in data["sessions"]


def test_reading_outside_a_transaction_sees_only_saved_data(store, data_file):
    with pytest.raises(RuntimeError):
        with store.transaction() as data:
            data["sessions"]["draft"] = {"created_at": None}
            raise RuntimeError("boom")

    assert "draft" not in store.read()["sessions"]


def test_another_thread_waits_for_a_transaction_and_then_sees_the_committed_data(store):
    seen = []
    reader = threading.Thread(target=lambda: seen.append(set(store.read()["sessions"])))

    with store.transaction() as data:
        data["sessions"]["draft"] = {"created_at": None}
        reader.start()
        reader.join(timeout=0.1)
        assert reader.is_alive()  # blocked: it must not read half-finished data
        with store.transaction() as inner:
            inner["sessions"]["draft2"] = {"created_at": None}

    reader.join(timeout=5)
    assert seen == [{"draft", "draft2"}]


def test_simultaneous_nested_transactions_do_not_lose_updates(store, data_file):
    total = 12
    barrier = threading.Barrier(total)

    def add_session(number):
        barrier.wait()
        with store.transaction() as outer:
            time.sleep(0.001)
            with store.transaction() as inner:
                inner["sessions"][f"s{number}"] = {"created_at": None}
            outer["sessions"][f"t{number}"] = {"created_at": None}

    threads = [threading.Thread(target=add_session, args=(n,)) for n in range(total)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    sessions = read_file(data_file)["sessions"]
    assert {f"s{n}" for n in range(total)} | {f"t{n}" for n in range(total)} == set(sessions)
