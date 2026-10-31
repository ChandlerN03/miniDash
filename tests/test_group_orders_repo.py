import copy
import json
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
