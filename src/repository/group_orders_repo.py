from src.store.file_store import FileStore

# Every group order dict must have these fields. "code" is the share code and
# is also the key the group is stored under. "created_at" is the date and time
# the group order was created, as an ISO 8601 string.
REQUIRED_FIELDS = (
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
)


class DuplicateShareCodeError(Exception):
    """A group order already exists under this share code (R6)."""


class GroupOrderNotFoundError(Exception):
    """No group order exists under this share code."""


class GroupOrderRepository:
    """Stores sessions and group orders through the file store.

    Group orders are never deleted, so a share code is never issued twice (R6).
    """

    def __init__(self, store: FileStore):
        self._store = store

    # -------------------------------------------------------------- sessions

    def create_session(self, token: str, created_at: str | None = None) -> None:
        """Store a session token. Creating an existing token keeps the first one."""
        with self._store.transaction() as data:
            data["sessions"].setdefault(token, {"created_at": created_at})

    def session_exists(self, token: str) -> bool:
        return token in self._store.read()["sessions"]

    # ---------------------------------------------------------- group orders

    def create_group_order(self, group: dict) -> None:
        """Store a new group order under its share code.

        Raises DuplicateShareCodeError if the code was used before.
        """
        _check_fields(group)
        with self._store.transaction() as data:
            if group["code"] in data["group_orders"]:
                raise DuplicateShareCodeError(f"Share code {group['code']!r} already exists.")
            data["group_orders"][group["code"]] = group

    def get_group_order(self, code: str) -> dict | None:
        return self._store.read()["group_orders"].get(code)

    def save_group_order(self, group: dict) -> None:
        """Replace an existing group order. Raises GroupOrderNotFoundError for an unknown code."""
        _check_fields(group)
        with self._store.transaction() as data:
            if group["code"] not in data["group_orders"]:
                raise GroupOrderNotFoundError(f"No group order with share code {group['code']!r}.")
            data["group_orders"][group["code"]] = group


def _check_fields(group: dict) -> None:
    missing = [field for field in REQUIRED_FIELDS if field not in group]
    if missing:
        raise ValueError(f"Group order is missing: {', '.join(missing)}")
