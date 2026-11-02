from fastapi import APIRouter, Header, Request, Response

from src.routes.schemas import CheckoutIn, GroupItemIn, GroupOrderIn, JoinIn, QuantityIn
from src.services.group_order_service import GroupOrderService

# Routes only read the request and call the service. Every rule, including
# "is there a session token?", is decided by the service.
router = APIRouter()


def _service(request: Request) -> GroupOrderService:
    return request.app.state.group_order_service


# The session token comes from the X-Session-Token header (FastAPI turns the
# underscores of the parameter name into hyphens).


@router.post("/sessions", status_code=201)
def create_session(request: Request):
    return {"token": _service(request).create_session()}


@router.post("/group-orders", status_code=201)
def create_group_order(body: GroupOrderIn, request: Request, x_session_token: str | None = Header(default=None)):
    return _service(request).create_group_order(x_session_token, body.restaurant_id, body.display_name)


@router.post("/group-orders/{code}/join", status_code=201)
def join(code: str, body: JoinIn, request: Request, x_session_token: str | None = Header(default=None)):
    participant = _service(request).join(x_session_token, code, body.display_name)
    # The participant's token stays server-side; send back only what the client needs.
    return {key: participant[key] for key in ("participant_id", "display_name", "joined_at", "restaurant_id")}


@router.post("/group-orders/{code}/participants/{participant_id}/items", status_code=201)
def add_item(
    code: str,
    participant_id: int,
    body: GroupItemIn,
    request: Request,
    x_session_token: str | None = Header(default=None),
):
    return _service(request).add_item(x_session_token, code, participant_id, body.menu_item_id, body.quantity)


@router.patch("/group-orders/{code}/participants/{participant_id}/items/{menu_item_id}", status_code=204)
def change_item(
    code: str,
    participant_id: int,
    menu_item_id: int,
    body: QuantityIn,
    request: Request,
    x_session_token: str | None = Header(default=None),
):
    _service(request).change_item(x_session_token, code, participant_id, menu_item_id, body.quantity)
    return Response(status_code=204)


@router.delete("/group-orders/{code}/participants/{participant_id}/items/{menu_item_id}", status_code=204)
def remove_item(
    code: str,
    participant_id: int,
    menu_item_id: int,
    request: Request,
    x_session_token: str | None = Header(default=None),
):
    _service(request).remove_item(x_session_token, code, participant_id, menu_item_id)
    return Response(status_code=204)


@router.post("/group-orders/{code}/leave", status_code=204)
def leave(code: str, request: Request, x_session_token: str | None = Header(default=None)):
    _service(request).leave(x_session_token, code)
    return Response(status_code=204)


@router.delete("/group-orders/{code}/participants/{participant_id}", status_code=204)
def remove_participant(
    code: str,
    participant_id: int,
    request: Request,
    x_session_token: str | None = Header(default=None),
):
    _service(request).remove_participant(x_session_token, code, participant_id)
    return Response(status_code=204)


@router.get("/group-orders/{code}/summary")
def get_summary(code: str, request: Request, x_session_token: str | None = Header(default=None)):
    return _service(request).get_summary(x_session_token, code)


@router.post("/group-orders/{code}/lock")
def lock(code: str, request: Request, x_session_token: str | None = Header(default=None)):
    return _service(request).lock(x_session_token, code)


@router.post("/group-orders/{code}/checkout", status_code=201)
def checkout(
    code: str,
    request: Request,
    body: CheckoutIn | None = None,
    x_session_token: str | None = Header(default=None),
):
    address = body.address if body is not None else None
    return _service(request).checkout(x_session_token, code, address)
