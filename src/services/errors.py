class MiniDashError(Exception):
    """A rejected request. `code` is stable and meant for clients and tests."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# Error codes used by group orders. Each constant equals its own name, so the
# string a client sees is the same as the name used in the code.
RESTAURANT_NOT_FOUND = "RESTAURANT_NOT_FOUND"
INVALID_SESSION = "INVALID_SESSION"
INVALID_CODE = "INVALID_CODE"
ORDER_EXPIRED = "ORDER_EXPIRED"
ORDER_CHECKED_OUT = "ORDER_CHECKED_OUT"
ORDER_LOCKED = "ORDER_LOCKED"
ALREADY_JOINED = "ALREADY_JOINED"
GROUP_FULL = "GROUP_FULL"
NOT_ALLOWED = "NOT_ALLOWED"
INVALID_QUANTITY = "INVALID_QUANTITY"
ITEM_NOT_ON_MENU = "ITEM_NOT_ON_MENU"
ITEM_NOT_IN_ORDER = "ITEM_NOT_IN_ORDER"
NOT_HOST = "NOT_HOST"
EMPTY_PARTICIPANT = "EMPTY_PARTICIPANT"
NOT_LOCKED = "NOT_LOCKED"
RESTAURANT_CLOSED = "RESTAURANT_CLOSED"
INVALID_ADDRESS = "INVALID_ADDRESS"
