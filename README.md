# MiniDash

A small food-delivery REST API built with FastAPI. Data is stored in a text file (`data.txt`) that holds JSON, so there is no database. There are no accounts or passwords. Group orders use a session token that you get from `POST /sessions` and send in the `X-Session-Token` header.

You can browse restaurants and menus, place an order, and follow its status. Friends can also build one order together as a **group order**: the host creates it and shares a 6-character code, everyone adds their own items, the host locks it and checks out, and the group becomes one normal order. The delivery fee is split between the participants.

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

On first start, `data.txt` is filled with 3 restaurants and their menu items. If the file already has data, it is left alone, and an older file gets the new `sessions` and `group_orders` collections added without losing anything. To reset (for example after changing `src/store/seed.py`), empty `data.txt` and restart. This also deletes all orders, sessions and group orders.

## Run the tests

```bash
python -m pytest
```

Tests use a temporary data file and a fake clock, so they never touch `data.txt`.

## Endpoints

### Restaurants and orders

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

### Group orders

Every endpoint except `POST /sessions` needs the header `X-Session-Token: <token>`.

| Method | Path | Success | Description |
|--------|------|---------|-------------|
| POST | `/sessions` | 201 `{token}` | Get a session token |
| POST | `/group-orders` | 201 `{code, status}` | Create a group order as the host. Body: `restaurant_id`, `display_name` |
| POST | `/group-orders/{code}/join` | 201 | Join with the code. Body: `display_name` |
| POST | `/group-orders/{code}/participants/{participant_id}/items` | 201 | Add an item. Body: `menu_item_id`, `quantity` |
| PATCH | `/group-orders/{code}/participants/{participant_id}/items/{menu_item_id}` | 204 | Set the quantity of an item. Body: `quantity` |
| DELETE | `/group-orders/{code}/participants/{participant_id}/items/{menu_item_id}` | 204 | Remove an item |
| GET | `/group-orders/{code}/summary` | 200 | What each participant owes |
| POST | `/group-orders/{code}/lock` | 200 | The host locks the group |
| POST | `/group-orders/{code}/checkout` | 201 `{order_id, status, total_cents}` | The host places the order. Body: `address` |

How it works:
- **Participants:** the host is participant 1, and everyone else gets the next number when they join. Joining returns your `participant_id`. A participant changes only their own items. The host can also remove anyone's item.
- **Quantities:** each item is 1 to 9 per person. Adding an item you already have increases its quantity, and the total cannot go above 9.
- **Limits:** at most 10 participants, and the host counts as one.
- **Summary:** for each participant, in join order: `subtotal_cents`, `fee_share_cents` and `total_cents`. The delivery fee is a fixed 499 cents, split evenly. Any leftover cents go one at a time to the last people to join, so the shares always add up to exactly 499.
- **Lock:** only the host can lock, and only when every participant has at least one item. After that nobody can join or change items.
- **Checkout:** only the host, only on a locked group, only while the restaurant is open, and with a non-blank address. It creates one normal order (see `/orders/{id}`) with everyone's items merged (the same menu item becomes one line) and a total of all subtotals plus the 499 cent fee.
- **Expiry:** a group that is open or locked and has had no activity for 2 hours expires, and then rejects changes with `ORDER_EXPIRED`. Joining, adding, changing or removing items, and locking count as activity. Reading the summary, checkout and rejected requests do not.
- **Restaurant hours** are compared in **UTC**. A restaurant is open from its `opens_at` up to, but not including, its `closes_at` (seed data: restaurant 1 is 11:00-22:00, restaurant 2 is 12:00-21:30, restaurant 3 is 10:00-23:00). If you try checkout by hand outside those hours, you get `RESTAURANT_CLOSED`.

Example (replace the `<...>` values with what the previous call returned):

```bash
# 1. Two people each get a session
curl -X POST http://127.0.0.1:8000/sessions
#    {"token":"<host-token>"}      (run it again for <guest-token>)

# 2. The host creates a group order at restaurant 3
curl -X POST http://127.0.0.1:8000/group-orders \
  -H 'content-type: application/json' -H 'X-Session-Token: <host-token>' \
  -d '{"restaurant_id": 3, "display_name": "Hana"}'
#    {"code":"<code>","status":"OPEN"}

# 3. The guest joins with the code
curl -X POST http://127.0.0.1:8000/group-orders/<code>/join \
  -H 'content-type: application/json' -H 'X-Session-Token: <guest-token>' \
  -d '{"display_name": "Bo"}'
#    {"participant_id":2,"display_name":"Bo","joined_at":"..."}

# 4. Both add items (the host is participant 1)
curl -X POST http://127.0.0.1:8000/group-orders/<code>/participants/1/items \
  -H 'content-type: application/json' -H 'X-Session-Token: <host-token>' \
  -d '{"menu_item_id": 9, "quantity": 2}'
curl -X POST http://127.0.0.1:8000/group-orders/<code>/participants/2/items \
  -H 'content-type: application/json' -H 'X-Session-Token: <guest-token>' \
  -d '{"menu_item_id": 10, "quantity": 1}'

# 5. Anyone in the group can look at the summary
curl http://127.0.0.1:8000/group-orders/<code>/summary -H 'X-Session-Token: <guest-token>'

# 6. The host locks, then checks out
curl -X POST http://127.0.0.1:8000/group-orders/<code>/lock -H 'X-Session-Token: <host-token>'
curl -X POST http://127.0.0.1:8000/group-orders/<code>/checkout \
  -H 'content-type: application/json' -H 'X-Session-Token: <host-token>' \
  -d '{"address": "12 Elm Street"}'
#    {"order_id":1,"status":"CHECKED_OUT","total_cents":...}
```

### Order statuses

`PLACED` -> `PREPARING` -> `OUT_FOR_DELIVERY` -> `DELIVERED`. An order can also become `CANCELLED` from `PLACED` or `PREPARING`. `DELIVERED` and `CANCELLED` are final.

A group order has its own status: `OPEN` -> `LOCKED` -> `CHECKED_OUT`, or `EXPIRED` from `OPEN` or `LOCKED`. `CHECKED_OUT` and `EXPIRED` are final. Unlocking a group is not built.

### Errors

Every rejected request returns `{"error": {"code": "...", "message": "..."}}`. Clients should rely on the `code`:

| Code | HTTP status |
|------|-------------|
| `INVALID_ADDRESS`, `EMPTY_ORDER`, `INVALID_QUANTITY`, `ITEM_NOT_ON_MENU`, `INVALID_STATUS` | 400 |
| `INVALID_SESSION` (missing, empty or unknown `X-Session-Token`) | 401 |
| `NOT_HOST`, `NOT_ALLOWED` | 403 |
| `RESTAURANT_NOT_FOUND`, `ORDER_NOT_FOUND`, `INVALID_CODE`, `ITEM_NOT_IN_ORDER` | 404 |
| `INVALID_STATUS_TRANSITION`, `GROUP_FULL`, `ALREADY_JOINED`, `ORDER_LOCKED`, `ORDER_EXPIRED`, `ORDER_CHECKED_OUT`, `NOT_LOCKED`, `EMPTY_PARTICIPANT`, `RESTAURANT_CLOSED` | 409 |
| `VALIDATION_ERROR` (bad JSON, wrong types, missing fields, or a path parameter that is not a number) | 422 |

`EMPTY_PARTICIPANT` (locking while someone has no items) names those participants in its `message`. `NOT_ALLOWED` is also returned when someone who is not in the group asks for its summary.

## Project layout

```
src/
  main.py            builds the app (create_app)
  clock.py           Clock interface and the real clock
  routes/            HTTP only: parse requests, return responses
  services/          business rules (orders, restaurants, group orders)
  repository/        reads and writes data through the store
  store/             JSON file store and seed data
tests/               pytest tests (temporary data file, fake clock)
docs/                requirements, design, task plan and AI log
```

More detail on how group orders work, and what is not built yet, is in `docs/design.md`.
