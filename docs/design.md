## Design: Group Order

Implements the criteria in requirements.md (R1-R39). Fits the MiniDash layers: routes -> services -> repository -> JSON file store.

# Components touched

component                            New / Changed
routes/group_orders.py                 New
services/group_order_service.py        New
services/fee_split.py                  New
repository/group_orders_repo.py       New
store/file_store.py                    New
services/order_service.py              Existing,reused
Clock (injected)                       New

Request Flow: the route reads the token header, calls the service with the clock and repository injected, and thruns a raised GroupOrderError(code) into the shared error body.

# Data changes (JSON file store)
one JSON text file mimics the database (for example data/group_orders.json). Only the repository layer touches it, so the rest of the code does not care how data is stored.

```json
{
    "sessions": { "<token>": { "created_at": "..."} },
    "group_orders": {
        "<code>": { // the share code is the key, so codes are unique (R5,R6)
            "id": 1,
            "restaurant_id": 2,
            "host_token": "...",
            "status": "OPEN",    // OPEN | LOCKED | EXPIRED | CHECKED_OUT
            "last_activity_at": "...", // used by the 2-hour check (R30, R31)
            "order_id": null, // set when checked out (R36)
            "created_at": "...",
            "participants": [ // list order = join order, which decides who gets leftover cents
            { "token": "...", "display_name": "...", "joined_at": "..." }
            ],
            "items": [
                { "token": "...", "menu_item_id": 5, "quantity": 2 }
            ]
        }
    }
}
```

Rules for the file store: 
- Every change is load, modify, save inside one lock, so two requests can't overwrite each other.
- Save writes a temporary file and then replaces the real one, so a crash can't leave half a file.
- Group orders are never deleted, which is what keeps codes from being reused (R6).
- The path is injectable, so tests use a temporary file and never touch real data.
- Prices are not copied into items, subtotals read the menu item price when the summary or checkout runs.
- The delivery fee is a constant DELIVERY_FEE_CENTS = 499 ($4.99) in configuration (R21).

Interfaces
All group endpoints require header X-Session-Token. Rejected requests return {"error": { "code": "...", "message": "..."}} (R39).

| Endpoint | Purpose | Success | Error codes |
| POST /sessions | Get a session token | 201 {token} | none |
| POST /group-orders {restaurant_id, display_name} | Create, become host | 201 {code, status} | INVALID_SESSION, RESTAURANT_NOT_FOUND |           
| POST /group-orders/{code}/join {display_name} | Join | 201 | INVALID_CODE, ORDER_EXPIRED, ORDER_LOCKED, ORDER_CHECKED_OUT, GROUP_FULL, ALREADY_JOINED |
| POST /group_orders/{code}/items {menu_item_id, quantity } | Add item | 201 | INVALID_QUANTITY, ITEM_NOT_ON_MENU, ORDER_LOCKED, ORDER_EXPIRED |
| PATCH /group-orders/{code}/items/{menu_item_id}{quantity} | Remove own item | 204 | NOT_ALLOWED, ORDER_LOCKED |
| DELETE /group-orders/{code}/items/{menu_item_id} | Remove own item | 204 | NOT_ALLOWED, ORDER_LOCKED |
| GET /group-orders/{code}/summary | Subtotal,fee share, total per person | 200 | INVALID_CODE |
| POST /group-orders/{code}/lock | Lock | 200 | NOT_HOST,EMPTY_PARTICIPANT, ORDER_EXPIRED |
| POST /group-orders/{code}/checkout {address} | Create the normal order | 201 {order_id} | NOT_HOST, NOT_LOCKED, RESTURANT_CLOSED, INVALID_ADDRESS, ORDER_CHECKED_OUT, ORDER EXPIRED |

Suggested HTTP statuses: 400 INVALID_QUANTITY / INVALID_ADDRESS / ITEM_NOT_ON_MENU, 401 INVALID_SESSION, 403 NOT_HOST / NOT_ALLOWED, 404 INVALID_CODE / RESTAURANT_NOT_FOUND, 409 for state conflicts (GROUP_FULL, ALREADY_JOINED, ORDER_LOCKED, ORDER_EXPIRED, ORDER_CHECKED_OUT, NOT_LOCKED, EMPTY_PARTICIPANT, RESTAURANT_CLOSED).

# Diagram: joining a group order
![Image of group order process not loading](diagram.png)
The EXPIRED status change is saved before the error is raised, even though the request itself is rejected.

# ADR-1: How to generate the share code
Context: Participants join with a code (R5,R6). It must be short enough to read out loud or tupe, and stangers should not be able to join someone's group by guessing.

Options considered 
1. Random 6-character code from a restricted alphabet (no 0,O,1,l,I), checked for uniqueness. 
2. Derived from the group order's id (for example, the auto-increment id turned into a short string)
3. Long random token (for example, a UUID)

Decision: Option 1, with the repository refusing to store a code that already exists a and a retry if a collision happens. 

Consequences
- Option 2 needs no uniqueness check, but codes come out in order, so anyone can try the neighbor codes and join other people's groups. That is the main reason it lost.
- Option 3 is partically unguessable, but is far too long ot share by voice or text, which defeats the point of a share code.
- Option 1 costs a uniqueness check and a rare retry. The alpabet has 57 characters (62 letters and digits minus the 5 ambiguous ones). so 7 characters give 57^6. about 34 billion codes. That makes random guesssing unliekly, but not impossible: there is no rate limit, which is out of scope. I accept that for this assignment. 
- Codes are nver resued (R6), so an old code reports EXPIRED or CHECKED_OUT instead of landing in a new group.

Other decisions
- Expiry is a lazy check on access. Every service method loads the group through one helper taht applies R31 first. No background job. Every endpoint needs a test for the expired case.
- Checkout reuses the existing order service. Identical items from different participants are merged by adding quantities, so the normal order looks like any other. 
- Time is injected. The service takes a Clock; the default is real time and tests pass a fake. 
- Money is integer cents anywhere.
- Storage is a JSON file behind the repository.
