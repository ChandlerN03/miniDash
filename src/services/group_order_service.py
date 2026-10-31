import secrets
import uuid
from datetime import datetime, timedelta

from src.clock import Clock
from src.repository.group_orders_repo import (
    DuplicateShareCodeError,
    GroupOrderNotFoundError,
    GroupOrderRepository,
)
from src.repository.restaurants_repo import RestaurantRepository
from src.services import errors
from src.services.activity_timer import ActivityTimer
from src.services.errors import MiniDashError
from src.services.share_code import generate_share_code

OPEN = "OPEN"
LOCKED = "LOCKED"
EXPIRED = "EXPIRED"
CHECKED_OUT = "CHECKED_OUT"

MAX_PARTICIPANTS = 10
DEFAULT_TTL = timedelta(hours=2)
CREATE_ATTEMPTS = 10


class GroupOrderService:
    def __init__(
        self,
        groups: GroupOrderRepository,
        restaurants: RestaurantRepository,
        clock: Clock,
        ttl: timedelta = DEFAULT_TTL,
    ):
        self._groups = groups
        self._restaurants = restaurants
        self._clock = clock
        self._ttl = ttl

    # ------------------------------------------------------------ sessions (R1)

    def create_session(self) -> str:
        token = secrets.token_urlsafe(32)
        self._groups.create_session(token, self._now())
        return token

    # ------------------------------------------------------- create group (R3, R4)

    def create_group_order(self, token: str | None, restaurant_id: int, display_name: str) -> dict:
        self._require_session(token)
        if self._restaurants.get_restaurant(restaurant_id) is None:
            raise MiniDashError(errors.RESTAURANT_NOT_FOUND, f"Restaurant {restaurant_id} does not exist.")

        now = self._now()
        for _ in range(CREATE_ATTEMPTS):
            code = generate_share_code(_IssuedCodes(self._groups))
            group = {
                "code": code,
                "id": uuid.uuid4().hex,
                "restaurant_id": restaurant_id,
                "host_token": token,
                "status": OPEN,
                "last_activity_at": now,
                "order_id": None,
                "created_at": now,
                "participants": [
                    {"participant_id": 1, "token": token, "display_name": display_name, "joined_at": now}
                ],
                "items": [],
            }
            try:
                self._groups.create_group_order(group)
            except DuplicateShareCodeError:
                continue  # another request took this code a moment ago; draw a new one
            return {"code": code, "status": OPEN}

        raise RuntimeError("Could not store a group order under an unused share code.")

    # ------------------------------------------------------------ join (R7-R12)

    def join(self, token: str | None, code: str, display_name: str) -> dict:
        self._require_session(token)

        def attempt(group: dict) -> tuple[MiniDashError | None, dict | None]:
            # Runs inside the repository's lock: the checks and the change are
            # one step, so simultaneous joins cannot overwrite each other.
            now = self._now()
            self._expire_if_inactive(group)  # R31, may change group["status"]
            rejection = self._join_rejection(group, token)
            if rejection is not None:
                return rejection, None  # returned, not raised, so a saved EXPIRED survives

            participant = {
                "participant_id": max((p["participant_id"] for p in group["participants"]), default=0) + 1,
                "token": token,
                "display_name": display_name,
                "joined_at": now,
            }
            group["participants"].append(participant)
            group["last_activity_at"] = now  # a successful join is activity (R30)
            return None, participant

        try:
            rejection, participant = self._groups.update_group_order(code, attempt)
        except GroupOrderNotFoundError:
            raise MiniDashError(errors.INVALID_CODE, "No group order matches this code.") from None
        if rejection is not None:
            raise rejection
        return participant

    # ------------------------------------------------------------------ helpers

    def _now(self) -> str:
        return self._clock.now().isoformat()

    def _require_session(self, token: str | None) -> None:
        if not token or not self._groups.session_exists(token):
            raise MiniDashError(errors.INVALID_SESSION, "A valid session token is required.")

    def _expire_if_inactive(self, group: dict) -> None:
        """Apply expiry (R31) to a loaded group: OPEN or LOCKED and inactive for
        the whole ttl becomes EXPIRED. The caller's update saves this change even
        when the request is then rejected (R31, R38).
        """
        if group["status"] in (OPEN, LOCKED) and self._inactive_too_long(group):
            group["status"] = EXPIRED

    def _join_rejection(self, group: dict, token: str) -> MiniDashError | None:
        """The error a join must be rejected with, or None. Checked in the order
        ORDER_EXPIRED, ORDER_CHECKED_OUT, ORDER_LOCKED, ALREADY_JOINED, GROUP_FULL.
        """
        if group["status"] == EXPIRED:
            return MiniDashError(errors.ORDER_EXPIRED, "This group order has expired.")  # R32
        if group["status"] == CHECKED_OUT:
            return MiniDashError(errors.ORDER_CHECKED_OUT, "This group order has already been checked out.")
        if group["status"] == LOCKED:
            return MiniDashError(errors.ORDER_LOCKED, "This group order is locked.")
        if any(p["token"] == token for p in group["participants"]):
            return MiniDashError(errors.ALREADY_JOINED, "You have already joined this group order.")
        if len(group["participants"]) >= MAX_PARTICIPANTS:
            return MiniDashError(
                errors.GROUP_FULL, f"A group order can have at most {MAX_PARTICIPANTS} participants."
            )
        return None

    def _inactive_too_long(self, group: dict) -> bool:
        # ActivityTimer starts counting when it is created, so build it "at" the
        # stored last activity, then give it the real clock. `clock` is a public
        # attribute of ActivityTimer.
        last_activity = datetime.fromisoformat(group["last_activity_at"])
        timer = ActivityTimer(_FixedClock(last_activity), self._ttl)
        timer.clock = self._clock
        return timer.is_expired()


class _FixedClock:
    def __init__(self, moment: datetime):
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


class _IssuedCodes:
    """Every share code ever issued, as a collection generate_share_code can check.

    Group orders are never deleted, so a stored group means the code was issued
    (R6), whatever its status.
    """

    def __init__(self, groups: GroupOrderRepository):
        self._groups = groups

    def __contains__(self, code: object) -> bool:
        return isinstance(code, str) and self._groups.get_group_order(code) is not None
