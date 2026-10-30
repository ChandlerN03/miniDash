## Requirements: <Feature Group Ordering>

## Summary
A host creates a group order for one resturant and gets a share code. Friends join with the code and add, change, or remove their own items until the host locks the order. The summary shows each person's subtotal plus an even share of the delivery fee (leftover cents handled so the shares always add up). When the host checks out, the group order bcecomes a normal MiniDash order. Groups hold at most 10 people and expire after 2 hours of inactivity.

## User Stories
- As a host, I want to crate a group order and share one code so many friends can add their own food without me typing it all in. 
- As a host, I want to lock the order and check out for everyone so one person places the final order.
- As a participant, I want to join with a code and manage only my own items so I don't mess up anyone else's food.


## Acceptance criteria

Error format used by every criterion below: a rejected request returns an error with a stable code (e.g. GROUP_FULL) and a human readable "message". Tests check the code, never the messaqge wording. 

| ID | Criterion |
|----|-----------|

Identity
| R1 | WHEN a client reqeusts a session. THE SYSTEM SHALL issue a unique session token that identifies that user in all later requests.
| R2 | IF a group-order request carries a misisng or unknown session token, THEN THE SYSTEM SHALL reject it with error INVALID_SESSION.

Creating a group order and share codes
| R3 | WHEN a user creates a group order for an existing resturant, THE SYSTEM SHALL create it with status OPEN, make that user the host and its first participant, and return the share code.
| R4 | IF the resturant does not exist, THEN THE SYSTEM SHALL reject the request with error RESTURANT_NOT_FOUND.
| R5 | THE SYSTEM SHALL generate every share code as exactly 6 case-sensitive characters from A-Z, a-z, and 0-9, excluding the ambigous characters 0, O, 1, I, and l.
| R6 | THE SYSTEM SHALL never issue a share code that was issued to any earlier group order.

Joining
| R7 | When a user joins with the code of an OPEN group order that has fewer than 10 participants, THE SYSTEM SHALL add them as a participant, kept in join order. 
| R8 | IF the group order already has 10 particpants, THEN THE SYSTEM SHALL reject the join with error GROUP_FULL.  
| R9 | IF no group order matches the code, THEN THE SYSTEM SHALL reject the join with error INVALID_CODE
| R10 | IF the group order is LOCKED, THEN THE SYSTEM SHALL reject the join with error ORDER_LOCKED 
| R11 | IF the group order is CHECKED_OUT, THEN THE SYSTEM SHALL reject the join with error ORDER_CHECKED_OUT
| R12 | IF the user is already a participant, THEN THE SYSTEM SHALL reject the join with error ALREADY_JOINED and keep exactly one record for that user. 

Items
| R13 | WHEN a participant adds a menu item from the group's resturant with a quantity from 1 to 9, THE SYSTEM SHALL record it under that participantl adding an item they already have increases its quantity
| R14 | IF a quantity is not a whole number from 1 to 9 (including a resulting total total above 9), THEN THE SYSTEM SHALL reject the request with error INVALID_QUANTITY.
| R15 | IF the item is not on the menu of the group's resturant. THEN THE SYSTEM SHALL reject the request with error ITEM_NOT_ON_MENU.
| R16 | WHEN a particpant changes the quantity of, or removes, one of their own items, THE SYSTEM SHALL apply the changes to the item only.
| R17 | IF a participant tries to change or remove another participant's item, THEN THE SYSTEM SHALL reject the request with error NOT_ALLOWED.
| R18 | WHEN the host removes any particpant's item, THE SYSTEM SHALL remove that time.
| R19 | WHEN the host removes a participant, THE SYSTEM SHALL remove that participant and all of their items. 

Summary and delivery fee
| R20 | WHEN any participant requests the summary. THE SYSTE SHALL return, for each participant in join order, their name. item subtotal, fee share, and total (subtotal + fee share), all in integer cents.
| R21 | THE SYSTEM SHALL use one fixed delivery fee, set in configuration, for every group order. 
| R22 | WHEN the summary is computed, THE SYSTEM SHALL give each participant. including the host, a base fee share equal to the delivery fee divided by the number of partipcants, rounded down to whole cents. 
| R23 | WHEN the delivery fee does not divide evenly among the participants. THE SYSTEM SHALL add one extra cent to each participant's share, starting with the last participant to join and moving toward the first, until the leftover cents are used up.
| R24 | THE SYSTEM SHALL ensure the participant's fee shares sum to exactly the delivery fee. 

Locking
| R25 | WHEN the host locks are OPEN group order in which every participant has at least one item, THE SYSTEM SHALL set its status to LOCKED. 
| R26 | IF any participant has no items when the host locks, THEN THE SYSTEM SHALL reject the lock with error EMPTY_PARTICIPANT, name those participants, and leave the status open. 
| R27 | IF a user who is not the host tries to lock, unlock, remove a participant, or check out, THEN THE SYSTEM SHALL reject the requst with error NOT_HOST.
| R28 | WHILE a group order is LOCKED, THE SYSTEM SHALL reject adding, changing, or removing items with error ORDER_LOCKED.
| R29 | WHEN the host unlocks a LOCKED order, THE SYSTEM SHALL set its status back to OPEN. 

Expiry 
| R30 | WHEN a participant joins, adds, changes, or removes an item, or the host locks or unlocks. THE SYSTEM SHALL record it as activity and restart the 2-hour inactivitity countdown. Viewing the summary and rejected requests are not activity.
| R31 | WHEN any request teaches an OPEN or LOCKED group order whose last activity was 2 hours or more ago (exactly 2:00:00 counts). THE SYSTEM SHALL set its status to EXPIRED before handling the request. 
| R32 | WHILE a group order is EXPIRED, THE SYSTEM SHALL reject joining, item changes, locking, unlocking, and checkout with error ORDER_EXPIRED.

Checkout
| R33 | IF the host checks out a group order that is not LOCKED, THEN THE SYSTEM SHALL reject the request with error NOT_LOCKED
| R34 | IF the resturant is closed at checkout time, THEN THE SYSTEM SHALL reject the request with error RESTAURANT_CLOSED
| R35 | IF the delivery address is missing or blank at checkout, THEN THE SYSTEM SHALL reject the request with error INVALID_ADDRESS.
| R36 | WHEN the host checks out a LOCKED group order with a vlaid address while the resturant is open, THE SYSTEM SHALL create one normal MiniDash order through the existing order service for the group's restaurant, containing every participants itmes, with a total equal to all subtotals plus the delivery fee, and set the group order to CHECK_OUT.
| R37 | IF checkout is requested for a CHECKED_OUT group order, THEN THE SYSTEM SHALL reject it with error ORDER_CHECKED_OUT and create no second order.

Failure behavior
| R38 | IF any request is rejected. THEN THE SYSTEM SHALL leave the group order's participants, items, status, and activity coutdown unchanged, excpet that the expiry transition in R31 still applies.
| R39 | IF any request is rejected, THEN THE SYSTEM SHALL return an error containing  a stable code and a message. 

Out of scope
- Payments and card entry (checkout stops at creating the normal MiniDash order)
- Notifications of any kind, including expiry warnings or a grace period after expiry
- Accounts, passwords, or login; protection against someone stealing another user's session token
- Any front end: popups, buttons, spinners, drop-downs, or screens (the API only returns data and error codes)
- Leaving one group to join another with a confirmation prompt
- A "copy someone else's item" shortcut (a participant can just add the same menu item themselves)
- Editing a group order after checkout
- Expiring orders with a background job (see ADR-1)

Assumptions
- The host counts toward the 10-person limit.
- Each user is identified only by their session token; a display name is supplied when joining.
- The host cannot be removed from their own group order.
- Locking requires every participant to have an item, so at checkout the fee is split among all participants. Before locking, the summary is provisional because people may still join or leave.
- Share codes are never reused, so an old code always reports EXPIRED or CHECKED_OUT instead of silently pointing at a new group.
- A LOCKED order can still expire. Locking counts as activity, so the 2 hours restart at lock.
- CHECKED_OUT is final and never expires. EXPIRED is final: nothing revives it.
- Any participant may read the summary; reading it does not reset the countdown.
- The delivery fee is a constant of DELIVERY_FEE_CENTS = ___ (fill in your value).
- A "valid address" means a non-blank string, because the baseline stores only an address string.
- Restaurants and menus come from the baseline's seeded data.
- The 2-hour limit is a default in configuration; tests use a fake clock.