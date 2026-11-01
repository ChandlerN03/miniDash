from typing import Any

from pydantic import BaseModel, StrictInt


class OrderItemIn(BaseModel):
    menu_item_id: StrictInt
    quantity: StrictInt


class OrderIn(BaseModel):
    restaurant_id: StrictInt
    address: str
    items: list[OrderItemIn]


class StatusIn(BaseModel):
    status: str


# --- group orders. These only describe the shape of the JSON; the service checks the values.


class GroupOrderIn(BaseModel):
    restaurant_id: StrictInt
    display_name: str


class JoinIn(BaseModel):
    display_name: str


class GroupItemIn(BaseModel):
    menu_item_id: StrictInt
    quantity: StrictInt


class QuantityIn(BaseModel):
    quantity: StrictInt


class CheckoutIn(BaseModel):
    # Any type is accepted here so that a missing, blank or non-string address
    # gets the service's INVALID_ADDRESS error instead of a generic validation error.
    address: Any = None
