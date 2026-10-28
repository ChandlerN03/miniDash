Task: Group Orders 

Each slice is a commit and one AI_log entry, written right after the slice. 

Paths below assume src/ and test/ ;rename them to match the generated baseline.

For each slice, the "done" check is the same:
1. Tests pass.
2. Mutation check: break the rule on purpose, a test fails, undo it. 
3. Read the whole diff: nothing outside the slice, no new dependencies. 
4. Commit message says what changed and how AI was used. Add the log entry

# Slice 1: Fee split (pure function)

Implements: R22, R23, R24 Files: src/group_orders/fee_split.py , tests/test_fee_split.py. Verification: 100 across 3 gives [33,34,34]: 101 gives [33,34,34]: 2 across 5 gives [0,0,0,1,1]: even split 300 across 3: a loop over many totals and group sizes checks the shares always sum to the total and differ by at most 1 cent: parts < 1 or a negative total raises ValueError. Mutation check: change the loop so the extra cents go to the first people; tests fail. 

# Slice 2: Inactivity timer with an injected clock

Implements: R30 and R31 (the rule only, not the endpoints yet) Files: src/group_orders/activity_timer.py, tests/test_activity_timer. Verification: 1:59:59 is not expired; exactly 2:00:00 is expired; touch restarts the countdown; a custom ttl works; a test fails if the code reads the real clock. Mutation check: change >= to >; the boundary test fails. AI use: written by hand first (bootcamp drill 2), AI used to review.

# Slice 3: Share code generator

Implements: R5,R6 (generation and uniqueness) Files: src/group_orders/share_code.py , tests/test_share_code.py Verification: every code is exactly 6 characters: none contain 0, O, I, l: both upper and lower case appear ovver many samples: given a set of existing codes, a collision is retried and the result is never in the set: an injected random source makes the collision test deterministic. Mutation check: add 0 back to the alphabet; the forbidden-character test fails.

# Slice 4: JSON file store and repository 

Implements: R6 (never reuse a code), supports R38 (state is stored exactly as written) Files: src/store/file_store.py, src/repository/group_orders_repo.py, tests/test_group_orders_repo.py Verification: using a tenoorary file path, saved data loads unchanged: two groups cannot be stored under the same code: particpants keep loads back unchanged: two groups cannot be stored under the same code: particpants keep join order; a crash style test confirms the real file isn't left half-written: sessions can be stored and looked up. Mutation check: let the repo overwrite an exisitng code; the duplicate test fails. 

# Slice 5: Services part 1 (sessions, create, join, laxy expiry)

Implements: R1, R2, R3, R4, R7, R8, R9,R10,R11,R12,R30,R31,R32,R38 for these files: src/services/group_order_service.py , tests/test_group_order_services_join.py. Verification: uses a fake clock and a temp file store. Creating a group makes the creator host and first participant; unknown restaurant gives RESTAURANT_NOT_FOUND; the 10th participant joins the the 11th gets GROUP_FULL; wrong ocde gives INVALID_CODE; locked, checked out, and expired groups give their codes; joining twice gives ALREADY_JOINED with one record; advancing the clock exaclty 2 hours then joining gives ORDER_EXPIRED and the stored status is EXPIRED; every rejected request leaves participants and last_acitvity unchanged. Mutation check: change the limit from 10 to 11; the boundary test fails. Remove the expiry check; the expired test fails. 


# Slice 6: Services part 2 (items, summary, lock)

Implements: R13, R14, R15, R16 , R17, R20, R21, R22 to R24 (using slice 1), R25, R26, R27 (lock). R28, R30, R31, R32 Files: same service file. tests/test_group_order _service_items.py, tests/test_group_order_service_lock.py Verification: adding the same item twice merges quantity; quantities 0, 1, 9, 10 (and a total above 9) behave correctly; an item from another restaurant gives ITEM_NOT_ON_MENU; changing or removing someone else's item gives NOT_ALLOWED; the summary shows subtotal, fee share, and total per person in join order, with fee shares summing to 499; locking with an empty participant gives EMPTY_PARTICIPANT and stays OPEN; a non-host lock gives NOT_HOST; items cannot change while LOCKED; item changes and locking count as activity; viewing the summary does not. Mutation check: let a participant edit someone else's item; the NOT_ALLOWED test fails. AI use: AI drafts; I check that the summary calls the slice 1 function instead of copying it.

# Slice 7: Service part 3 (checkout)

Implements: R27 (checkout), R31, R32, R33, R34, R35, R36, R37. Files: same service file, tests/test_group_order _service_checkout.py Verification: checkout of an OPEN order gives NOT_LOCKED; closed resturant gives RESTAURANT_CLOSED; blank address gives INVALID_ADDRESS; a successful checkout creates exactly one normal order through the existing order service, identical items merged with quantities added, total equal to all subtotals plus 499, and the group becomes CHECKED_OUT; a second checkout gives ORDER_CHECKED_OUT and creates no second order; a failed checkout leaves the group LOCKED and creates no order. Mutation check: remove the CHECKED_OUT guard; the double-checkout test fails. AI use: AI drafts; I check that it calls the existing order service and doesn't write order data directly.

# Slice 8: Routes, error format, end-to-end test, README

Implements: R1, R2, R39 (error body), plus the HTTP shape of every endpoint in design.md Files: src/routes/group_orders.py, tests/test_group_orders_api.py, README.md Verification: each endpoint returns the status code listed in the design; every error response has the shape {"error": {"code", "message"}}; a missing or unknown X-Session-Token gives INVALID_SESSION; one end-to-end test runs create, join, add items, summary, lock, checkout; the README shows how to run the app and the tests, and the tests pass from a fresh clone. Mutation check: change one status code; its route test fails. AI use: AI drafts the routes; I check that routes contain no business rules.

# Traceability (requirement to slices)

Requirement | Slices

R1,R2 | 5,8
R3,R4 | 5
R5 | 3
R6 | 3,4
R7 to R12 | 5
R13 to R17 | 6
R20 | 6
R21 | 6
R22 to R24 | 1,6
R25,R26,R28 | 6
R27 | 5/6/7 (host-only checks), 8
R30 | 2,5,6
R31,R32 | 2,5,6,7
R33 to R37 | 7
R38 | 4,5,6,7
R39 | 8
R18,R19,R29 | not planned
