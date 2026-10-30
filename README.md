# MiniDash

A small food-delivery REST API built with FastAPI. Data is stored in a text file (`data.txt`) that holds JSON, so there is no database. There is no authentication.

## Requirements

- Python 3.10 or newer
- Packages: `fastapi`, `uvicorn`, `pytest` (nothing else)

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn pytest
```

On macOS, `python` only exists after `source .venv/bin/activate`. Without activating, use `python3` to create the venv and `.venv/bin/python` in place of `python` in the commands below.

## Run the API

From the project root:

```bash
python -m uvicorn src.main:create_app --factory --reload
```

The API is at http://127.0.0.1:8000 and interactive docs are at http://127.0.0.1:8000/docs.

On first start, `data.txt` is filled with 3 restaurants and their menu items. If the file already has data, it is left alone. To reset (for example after changing `src/store/seed.py`), empty `data.txt` and restart. This also deletes any orders.

## Run the tests

```bash
python -m pytest
```

Tests use a temporary data file and a fake clock, so they never touch `data.txt`.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/restaurants` | List restaurants |
| GET | `/restaurants/{id}/menu` | Menu for one restaurant |
| POST | `/orders` | Place an order (201) |
| GET | `/orders/{id}` | Get an order with its items |
| PATCH | `/orders/{id}/status` | Change the order status |

Example:

```bash
curl -X POST http://127.0.0.1:8000/orders \
  -H 'content-type: application/json' \
  -d '{"restaurant_id": 1, "address": "12 Elm Street", "items": [{"menu_item_id": 1, "quantity": 2}]}'

curl -X PATCH http://127.0.0.1:8000/orders/1/status \
  -H 'content-type: application/json' \
  -d '{"status": "PREPARING"}'
```

Money is always an integer number of cents (`price_cents`, `total_cents`).

Restaurants and menu items each have an `image_url` (a link to a picture). The seed data uses placeholder links on `example.com`. Replace them in `src/store/seed.py` with real image links.

### Order statuses

`PLACED` -> `PREPARING` -> `OUT_FOR_DELIVERY` -> `DELIVERED`. An order can also become `CANCELLED` from `PLACED` or `PREPARING`. `DELIVERED` and `CANCELLED` are final.

### Errors

Every rejected request returns `{"error": {"code": "...", "message": "..."}}`. Clients should rely on the `code`:

| Code | HTTP status |
|------|-------------|
| `RESTAURANT_NOT_FOUND`, `ORDER_NOT_FOUND` | 404 |
| `INVALID_STATUS_TRANSITION` | 409 |
| `INVALID_ADDRESS`, `EMPTY_ORDER`, `INVALID_QUANTITY`, `ITEM_NOT_ON_MENU`, `INVALID_STATUS` | 400 |
| `VALIDATION_ERROR` (wrong types or missing fields) | 422 |

## Project layout

```
src/
  main.py            builds the app (create_app)
  clock.py           Clock interface and the real clock
  routes/            HTTP only: parse requests, return responses
  services/          business rules
  repository/        reads and writes data through the store
  store/             JSON file store and seed data
tests/               pytest tests (temporary data file, fake clock)
```
