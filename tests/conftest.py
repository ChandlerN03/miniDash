"""Shared test fixtures.

FastAPI's TestClient needs the `httpx` package, which is not one of the allowed
dependencies. `AsgiClient` below calls the ASGI app directly instead, so the
tests only need fastapi and pytest.
"""

import asyncio
import json
from datetime import datetime, timezone

import pytest

from src.main import create_app


class FixedClock:
    """A clock the tests control."""

    def __init__(self, now: datetime):
        self._now = now

    def now(self) -> datetime:
        return self._now


class Response:
    def __init__(self, status_code: int, body: bytes):
        self.status_code = status_code
        self.body = body

    def json(self):
        return json.loads(self.body)


class AsgiClient:
    def __init__(self, app):
        self._app = app

    def get(self, path: str) -> Response:
        return self._request("GET", path)

    def post(self, path: str, json_body=None, raw_body: bytes | None = None) -> Response:
        return self._request("POST", path, json_body, raw_body)

    def patch(self, path: str, json_body=None) -> Response:
        return self._request("PATCH", path, json_body)

    def _request(self, method, path, json_body=None, raw_body=None) -> Response:
        if raw_body is not None:
            body = raw_body
        elif json_body is not None:
            body = json.dumps(json_body).encode()
        else:
            body = b""
        return asyncio.run(self._call(method, path, body))

    async def _call(self, method: str, path: str, body: bytes) -> Response:
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", b"testserver"),
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
        request_sent = False

        async def receive():
            nonlocal request_sent
            if not request_sent:
                request_sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        status = 500
        chunks: list[bytes] = []

        async def send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))

        await self._app(scope, receive, send)
        return Response(status, b"".join(chunks))


@pytest.fixture
def clock():
    return FixedClock(datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc))


@pytest.fixture
def data_file(tmp_path):
    return tmp_path / "data.txt"


@pytest.fixture
def app(data_file, clock):
    return create_app(data_path=data_file, clock=clock)


@pytest.fixture
def client(app):
    return AsgiClient(app)
