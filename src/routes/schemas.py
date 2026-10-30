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
