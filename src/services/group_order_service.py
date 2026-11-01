import copy
import secrets
import uuid
from datetime import datetime, time, timedelta, timezone

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
from src.services.fee_split import split_evenly
from src.services.order_service import OrderService
from src.services.share_code import generate_share_code

DELIVERY_FEE_CENTS = 499  # R21: one fixed delivery fee for every group order, in integer cents

OPEN = "OPEN"
LOCKED = "LOCKED"
EXPIRED = "EXPIRED"
CHECKED_OUT = "CHECKED_OUT"

MAX_PARTICIPANTS = 10
MIN_QUANTITY = 1
MAX_QUANTITY = 9
DEFAULT_TTL = timedelta(hours=2)
CREATE_ATTEMPTS = 10


class EmptyParticipantError(MiniDashError):
    """A lock was rejected because some participants have no items (R26).

    `participants` lists them in join order as {"participant_id", "display_name"}.
    The names are also in the message.
    """

    def __init__(self, participants: list[dict]):
        names = ", ".join(p["display_name"] for p in participants)
        super().__init__(errors.EMPTY_PARTICIPANT, f"Every participant needs at least one item. Missing: {names}.")
        self.participants = participants


class GroupOrderService:
    def __init__(
        self,
        groups: GroupOrderRepository,
        restaurants: RestaurantRepository,
        clock: Clock,
        ttl: timedelta = DEFAULT_TTL,
        orders: OrderService | None = None,
    ):
        self._groups = groups
        self._restaurants = restaurants
        self._clock = clock
        self._ttl = ttl
        self._orders = orders  # only needed for checkout

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
            # A copy with the restaurant added, so the joiner knows which menu to show.
            # The stored participant record does not get a restaurant_id.
            return None, {**participant, "restaurant_id": group["restaurant_id"]}

        try:
            rejection, participant = self._groups.update_group_order(code, attempt)
        except GroupOrderNotFoundError:
            raise MiniDashError(errors.INVALID_CODE, "No group order matches this code.") from None
        if rejection is not None:
            raise rejection
        return participant

    # ---------------------------------------------------- items (R13-R17, R28)

    def add_item(self, token: str | None, code: str, participant_id: int, menu_item_id: int, quantity: int) -> dict:
        """Add `quantity` of a menu item for a participant. Adding an item they
        already have increases its quantity. Returns the stored item.
        """
        return self._edit_item("add", token, code, participant_id, menu_item_id, quantity)

    def change_item(
        self, token: str | None, code: str, participant_id: int, menu_item_id: int, quantity: int
    ) -> dict:
        """Set the quantity of an item the participant already has. Returns the stored item."""
        return self._edit_item("change", token, code, participant_id, menu_item_id, quantity)

    def remove_item(self, token: str | None, code: str, participant_id: int, menu_item_id: int) -> None:
        """Remove an item the participant has."""
        self._edit_item("remove", token, code, participant_id, menu_item_id, None)

    def _edit_item(
        self,
        action: str,
        token: str | None,
        code: str,
        participant_id: int,
        menu_item_id: int,
        quantity: int | None,
    ) -> dict | None:
        self._require_session(token)

        def attempt(group: dict) -> tuple[MiniDashError | None, dict | None]:
            # Runs inside the repository's lock, like join: checks and change are one step.
            now = self._now()
            self._expire_if_inactive(group)  # R31, may change group["status"]
            rejection = self._item_rejection(group, action, token, participant_id, menu_item_id, quantity)
            if rejection is not None:
                return rejection, None  # returned, not raised, so a saved EXPIRED survives

            result = self._apply_item_change(group, action, participant_id, menu_item_id, quantity)
            group["last_activity_at"] = now  # a successful add, change or remove is activity (R30)
            return None, result

        try:
            rejection, result = self._groups.update_group_order(code, attempt)
        except GroupOrderNotFoundError:
            raise MiniDashError(errors.INVALID_CODE, "No group order matches this code.") from None
        if rejection is not None:
            raise rejection
        return result

    # ----------------------------------------------------------- summary (R20-R24)

    def get_summary(self, token: str | None, code: str) -> dict:
        """What each participant owes, in join order. Any participant may read it.

        Reading is not activity (R30) and writes nothing, except that expiry
        (R31) is still applied: an inactive group is saved as EXPIRED and the
        summary is returned with that status instead of being rejected.
        """
        self._require_session(token)
        group = self._groups.get_group_order(code)
        if group is None:
            raise MiniDashError(errors.INVALID_CODE, "No group order matches this code.")

        if group["status"] in (OPEN, LOCKED) and self._inactive_too_long(group):
            def expire(stored: dict) -> dict:
                self._expire_if_inactive(stored)  # re-checked inside the lock
                return copy.deepcopy(stored)

            try:
                group = self._groups.update_group_order(code, expire)
            except GroupOrderNotFoundError:
                raise MiniDashError(errors.INVALID_CODE, "No group order matches this code.") from None

        if not any(p["token"] == token for p in group["participants"]):
            raise MiniDashError(errors.NOT_ALLOWED, "Only participants can see the summary.")
        return self._build_summary(group, token)

    def _build_summary(self, group: dict, token: str) -> dict:
        # Names and prices are read from the menu now and never stored on the group order.
        menu = {item["id"]: item for item in self._restaurants.list_menu(group["restaurant_id"])}
        restaurant = self._restaurants.get_restaurant(group["restaurant_id"])
        shares = split_evenly(DELIVERY_FEE_CENTS, len(group["participants"]))  # R22-R24, join order
        me = next(p for p in group["participants"] if p["token"] == token)  # get_summary checked this

        entries = []
        for participant, fee_share in zip(group["participants"], shares):
            items = [
                {
                    "menu_item_id": item["menu_item_id"],
                    "name": menu[item["menu_item_id"]]["name"],
                    "quantity": item["quantity"],
                    "line_total_cents": menu[item["menu_item_id"]]["price_cents"] * item["quantity"],
                }
                for item in group["items"]
                if item["participant_id"] == participant["participant_id"]
            ]
            subtotal = sum(item["line_total_cents"] for item in items)
            entries.append(
                {
                    "participant_id": participant["participant_id"],
                    "display_name": participant["display_name"],
                    "subtotal_cents": subtotal,
                    "fee_share_cents": fee_share,
                    "total_cents": subtotal + fee_share,
                    "items": items,
                }
            )
        return {
            "status": group["status"],
            "delivery_fee_cents": DELIVERY_FEE_CENTS,
            "restaurant_id": group["restaurant_id"],
            "restaurant_name": restaurant["name"],
            "order_id": group["order_id"],  # None until the host checks out
            # Who is asking. Never a token: only the participant id and the host flag.
            "you": {"participant_id": me["participant_id"], "is_host": token == group["host_token"]},
            "participants": entries,
        }

    # ------------------------------------------------------------- lock (R25-R27)

    def lock(self, token: str | None, code: str) -> dict:
        """The host locks an OPEN group in which every participant has an item."""
        self._require_session(token)

        def attempt(group: dict) -> tuple[MiniDashError | None, None]:
            now = self._now()
            self._expire_if_inactive(group)  # R31, may change group["status"]
            rejection = self._lock_rejection(group, token)
            if rejection is not None:
                return rejection, None  # returned, not raised, so a saved EXPIRED survives
            group["status"] = LOCKED
            group["last_activity_at"] = now  # a successful lock is activity (R30)
            return None, None

        self._update_group(code, attempt)
        return {"code": code, "status": LOCKED}

    def _lock_rejection(self, group: dict, token: str) -> MiniDashError | None:
        """The error a lock must be rejected with, or None. Checked in the order
        ORDER_EXPIRED, ORDER_CHECKED_OUT, ORDER_LOCKED, NOT_HOST, EMPTY_PARTICIPANT.
        """
        rejection = self._status_rejection(group)
        if rejection is not None:
            return rejection
        if token != group["host_token"]:  # R27
            return MiniDashError(errors.NOT_HOST, "Only the host can lock the group order.")

        with_items = {item["participant_id"] for item in group["items"]}
        empty = [
            {"participant_id": p["participant_id"], "display_name": p["display_name"]}
            for p in group["participants"]
            if p["participant_id"] not in with_items
        ]
        if empty:  # R26
            return EmptyParticipantError(empty)
        return None

    # ------------------------------------------------------- checkout (R33-R37)

    def checkout(self, token: str | None, code: str, address: str) -> dict:
        """The host turns a LOCKED group into one normal MiniDash order.

        The order is created through the existing order service, inside the same
        atomic update that marks the group CHECKED_OUT. If anything fails, no
        order is kept and the group stays LOCKED (R38); two checkouts at once
        cannot create two orders (R37).
        """
        if self._orders is None:
            raise RuntimeError("GroupOrderService needs an order service to check out (pass orders=...).")
        self._require_session(token)

        def attempt(group: dict) -> tuple[MiniDashError | None, dict | None]:
            self._expire_if_inactive(group)  # R31, may change group["status"]
            rejection = self._checkout_rejection(group, token, address)
            if rejection is not None:
                return rejection, None  # returned, not raised, so a saved EXPIRED survives

            order = self._orders.create_order(
                group["restaurant_id"],
                address,
                _merged_order_lines(group),
                delivery_fee_cents=DELIVERY_FEE_CENTS,
            )
            group["status"] = CHECKED_OUT
            group["order_id"] = order["id"]
            return None, {"order_id": order["id"], "status": CHECKED_OUT, "total_cents": order["total_cents"]}

        return self._update_group(code, attempt)

    def _checkout_rejection(self, group: dict, token: str, address: object) -> MiniDashError | None:
        """The error a checkout must be rejected with, or None. Checked in the order
        ORDER_EXPIRED, ORDER_CHECKED_OUT, NOT_HOST, NOT_LOCKED, RESTAURANT_CLOSED, INVALID_ADDRESS.
        """
        if group["status"] == EXPIRED:  # R32
            return MiniDashError(errors.ORDER_EXPIRED, "This group order has expired.")
        if group["status"] == CHECKED_OUT:  # R37
            return MiniDashError(errors.ORDER_CHECKED_OUT, "This group order has already been checked out.")
        if token != group["host_token"]:  # R27
            return MiniDashError(errors.NOT_HOST, "Only the host can check out the group order.")
        if group["status"] != LOCKED:  # R33
            return MiniDashError(errors.NOT_LOCKED, "The group order must be locked before checkout.")

        restaurant = self._restaurants.get_restaurant(group["restaurant_id"])
        if restaurant is None:
            return MiniDashError(errors.RESTAURANT_NOT_FOUND, "The restaurant does not exist.")
        if not self._is_open(restaurant):  # R34
            return MiniDashError(
                errors.RESTAURANT_CLOSED,
                f"The restaurant is open from {restaurant['opens_at']} to {restaurant['closes_at']} (UTC).",
            )

        if not isinstance(address, str) or not address.strip():  # R35
            return MiniDashError(errors.INVALID_ADDRESS, "A delivery address is required.")
        return None

    def _is_open(self, restaurant: dict) -> bool:
        """Open from opens_at up to, but not including, closes_at, in UTC.

        The hours are "HH:MM" strings without a timezone, so they are compared with
        the injected clock's time in UTC. Hours that run past midnight (closes_at not
        after opens_at) are not supported and count as always closed.
        """
        now = self._clock.now().astimezone(timezone.utc).time()
        return time.fromisoformat(restaurant["opens_at"]) <= now < time.fromisoformat(restaurant["closes_at"])

    # ------------------------------------------------------------------ helpers

    def _update_group(self, code: str, attempt) -> object:
        """Run `attempt(group)` atomically. It returns (rejection, result): a rejection is
        raised after the update is saved, otherwise the result is returned.
        """
        try:
            rejection, result = self._groups.update_group_order(code, attempt)
        except GroupOrderNotFoundError:
            raise MiniDashError(errors.INVALID_CODE, "No group order matches this code.") from None
        if rejection is not None:
            raise rejection
        return result

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

    def _status_rejection(self, group: dict) -> MiniDashError | None:
        """The error for a group that is no longer open to changes, or None.
        Checked in the order ORDER_EXPIRED (R32), ORDER_CHECKED_OUT, ORDER_LOCKED (R10, R28).
        """
        if group["status"] == EXPIRED:
            return MiniDashError(errors.ORDER_EXPIRED, "This group order has expired.")
        if group["status"] == CHECKED_OUT:
            return MiniDashError(errors.ORDER_CHECKED_OUT, "This group order has already been checked out.")
        if group["status"] == LOCKED:
            return MiniDashError(errors.ORDER_LOCKED, "This group order is locked.")
        return None

    def _join_rejection(self, group: dict, token: str) -> MiniDashError | None:
        """The error a join must be rejected with, or None. Checked in the order
        ORDER_EXPIRED, ORDER_CHECKED_OUT, ORDER_LOCKED, ALREADY_JOINED, GROUP_FULL.
        """
        rejection = self._status_rejection(group)
        if rejection is not None:
            return rejection
        if any(p["token"] == token for p in group["participants"]):
            return MiniDashError(errors.ALREADY_JOINED, "You have already joined this group order.")
        if len(group["participants"]) >= MAX_PARTICIPANTS:
            return MiniDashError(
                errors.GROUP_FULL, f"A group order can have at most {MAX_PARTICIPANTS} participants."
            )
        return None

    def _item_rejection(
        self,
        group: dict,
        action: str,
        token: str,
        participant_id: int,
        menu_item_id: int,
        quantity: int | None,
    ) -> MiniDashError | None:
        """The error an add, change or remove must be rejected with, or None. Checked in the order
        ORDER_EXPIRED, ORDER_CHECKED_OUT, ORDER_LOCKED, NOT_ALLOWED, INVALID_QUANTITY,
        ITEM_NOT_ON_MENU, then (change and remove only) ITEM_NOT_IN_ORDER.
        """
        rejection = self._status_rejection(group)
        if rejection is not None:
            return rejection

        # R17: the caller may only act for their own participant_id.
        # R18: the exception is the host, who may also REMOVE any participant's item
        # (not add or change it). The person must still be a participant of this group.
        owner = next((p for p in group["participants"] if p["participant_id"] == participant_id), None)
        is_own_item = owner is not None and owner["token"] == token
        host_removing = action == "remove" and owner is not None and token == group["host_token"]
        if not (is_own_item or host_removing):
            return MiniDashError(
                errors.NOT_ALLOWED,
                "You can only change your own items. Only the host can remove other people's items.",
            )

        existing = _find_item(group, participant_id, menu_item_id)

        if action != "remove":  # R14
            # Adding increases what they already have, so the total must stay in range too.
            already_have = existing["quantity"] if action == "add" and existing else 0
            if (
                not _is_whole_number(quantity)
                or not MIN_QUANTITY <= quantity <= MAX_QUANTITY
                or already_have + quantity > MAX_QUANTITY
            ):
                return MiniDashError(
                    errors.INVALID_QUANTITY,
                    f"Quantity must be a whole number from {MIN_QUANTITY} to {MAX_QUANTITY}, "
                    f"including what you already have of this item.",
                )

        menu_ids = {item["id"] for item in self._restaurants.list_menu(group["restaurant_id"])}
        if menu_item_id not in menu_ids:  # R15
            return MiniDashError(errors.ITEM_NOT_ON_MENU, f"Menu item {menu_item_id} is not on this menu.")

        if action != "add" and existing is None:
            return MiniDashError(errors.ITEM_NOT_IN_ORDER, f"You have no item {menu_item_id} in this order.")
        return None

    def _apply_item_change(
        self, group: dict, action: str, participant_id: int, menu_item_id: int, quantity: int | None
    ) -> dict | None:
        """Make the change to the loaded group (only called once every check has passed)."""
        existing = _find_item(group, participant_id, menu_item_id)
        if action == "remove":
            group["items"].remove(existing)
            return None
        if action == "change":
            existing["quantity"] = quantity
            return dict(existing)
        if existing is not None:  # add to an item they already have
            existing["quantity"] += quantity
            return dict(existing)
        item = {"participant_id": participant_id, "menu_item_id": menu_item_id, "quantity": quantity}
        group["items"].append(item)
        return dict(item)

    def _inactive_too_long(self, group: dict) -> bool:
        # ActivityTimer starts counting when it is created, so build it "at" the
        # stored last activity, then give it the real clock. `clock` is a public
        # attribute of ActivityTimer.
        last_activity = datetime.fromisoformat(group["last_activity_at"])
        timer = ActivityTimer(_FixedClock(last_activity), self._ttl)
        timer.clock = self._clock
        return timer.is_expired()


def _is_whole_number(value: object) -> bool:
    # bool is a subclass of int, so True would otherwise count as 1.
    return type(value) is int


def _merged_order_lines(group: dict) -> list[dict]:
    """Everyone's items as order lines: the same menu item is one line with the quantities added."""
    quantities: dict[int, int] = {}
    for item in group["items"]:
        quantities[item["menu_item_id"]] = quantities.get(item["menu_item_id"], 0) + item["quantity"]
    return [{"menu_item_id": menu_item_id, "quantity": quantity} for menu_item_id, quantity in quantities.items()]


def _find_item(group: dict, participant_id: int, menu_item_id: int) -> dict | None:
    for item in group["items"]:
        if item["participant_id"] == participant_id and item["menu_item_id"] == menu_item_id:
            return item
    return None


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
