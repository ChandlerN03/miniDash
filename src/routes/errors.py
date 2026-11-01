from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.services.errors import MiniDashError

# HTTP status for each stable error code. Unlisted codes fall back to 400.
STATUS_BY_CODE = {
    "RESTAURANT_NOT_FOUND": 404,
    "ORDER_NOT_FOUND": 404,
    "INVALID_STATUS_TRANSITION": 409,
    # Group orders
    "INVALID_QUANTITY": 400,
    "INVALID_ADDRESS": 400,
    "ITEM_NOT_ON_MENU": 400,
    "INVALID_SESSION": 401,
    "NOT_HOST": 403,
    "NOT_ALLOWED": 403,
    "INVALID_CODE": 404,
    "ITEM_NOT_IN_ORDER": 404,
    "GROUP_FULL": 409,
    "ALREADY_JOINED": 409,
    "ORDER_LOCKED": 409,
    "ORDER_EXPIRED": 409,
    "ORDER_CHECKED_OUT": 409,
    "NOT_LOCKED": 409,
    "EMPTY_PARTICIPANT": 409,
    "RESTAURANT_CLOSED": 409,
}


def error_body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(MiniDashError)
    async def handle_minidash_error(request: Request, exc: MiniDashError) -> JSONResponse:
        status_code = STATUS_BY_CODE.get(exc.code, 400)
        return JSONResponse(status_code=status_code, content=error_body(exc.code, exc.message))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()
        )
        return JSONResponse(status_code=422, content=error_body("VALIDATION_ERROR", problems))
