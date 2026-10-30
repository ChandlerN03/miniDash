AI usage Log: MiniDash Group Orders (Track B)

Tools used: Claude

Entry 1: Requirements review and rewrite 

Field | Entry

Entry # / date | 1 10/27/26

Tool, model, mode | Claude, chat

Slice | Spec: docs/requirements.md

Prompt | Wrote my oen draft EARS criteria and uploaded it and asked for a critique and to make any necessary reword needs.

What the AI produced | A revised requirements.md with 39 criteria, error codes,a MUST/LATER priority column, and review notes. It found: criteria that described screens (popups,spinners) in an API project, a missing checkout criterion, a typo that reversed R5's meaning, a dupliated R11, empty rows, and a contradiction between :failures change nothing" and lazy expiry. 

What I verfied | Ensuring each criteria made sense for this project and the particular architectural decisions I made for this project.

What I changed and why | The design decisions stayed mine: host counts toward the limit, leftover cents go the last joiners, a fixed delivery fee, lazy expiry. I changed some wording and some decisions that I felt didnt align exaclty with what I was envisioning.

Outcome | I modified and then accepted and commited to the repository. 

Entry 2: Design Draft
Entry # / Date | 1 / 10/27/26
Tool, model, mode | Claude, chat
Slice | Design docs/design.md
Prompt | Asked Claude to review my notes and modify my draft to better match industry standards. I merged identical items at the checkout. ADR topic is the share coce, teh join flow for the sequence diagrma, a $4.99 flat fee. I left the session token placement to Claude, which picked a rquest header. 
What the AI produced | design.md with components, data layout, endpoint table with error codes, a Mermaid join diagram, and the share code ADR. It also corrected a number in my notes: 57 usable characters over 6 positions is baout 34 billion codes, not 1 billion. 
What I verified | checked that the diagrams makes sense and the overall architecture design was sound.
What I changed and why | Changed the storage to a JSON format in a txt file. 
Outcome | accpeted and commited code. 


Entry 3: Task plan
Field | Entry
Entry # / date | 3
Tool, model, mode | Claude, chat
Slice | Plan docs/tasks.md
Prompt | Asked for the task list with slices ordered so my fee split is first and my timer is second, basd on my requirements and design. 
What the AI produced | tasks.md with 8 slices, each with the requiremnts it covers, its verification tests, and a mutation check, plus a traceabilitity table. Only MUST criteria were planned. 
What I Verfied | had my original draft for the tasks and read over the responses given see align that the divions make sense.
What I changed and why | the wording for some slices that don't completely align with the slice. 

Entry 4: baseline creation
Field | Entry
Entry # / date | 4 
Tool, model, mode | Kiro, Sonnet 5.5, Default
Slice | inital environment setup
Prompt | Read AGENTS.md. Create a small food-delivery REST API called MiniDash in Python with FastAPI. Store data in a JSON file instead of a database. Data: restaurants (id, name, cuisine, opens_at, closes_at, avg_prep_minutes), menu_items (id, restaurant_id, name, price_cents), orders (id, restaurant_id, status, total_cents, address, created_at), and order items. Endpoints: GET /restaurants, GET /restaurants/{id}/menu, POST /orders, GET /orders/{id}, PATCH /orders/{id}/status. Use a layered structure (routes, services, repository). Seed 3 restaurants with a few menu items each. Add pytest tests for each endpoint using a temporary data file, and a README with run instructions. No authentication. Don’t add any dependency beyond fastapi, uvicorn, and pytest without telling me why.
what the AI produced | It created the standard api setup and paths, it reate the src file, making industry standard seperations and all that. The page itself looks like the standard api page. 
What I verified | that the page works currectly nothing looks visually off and verified the test of it and it all looked sound. 
WHat I changed and why | I added the image component to the resturant and to the food item. 
Outcome | commited code and API page made. 

Entry 5: fee-split 
Field | Entry
Entry # / date | 5
Tool, model, mode | Kiro, Sonnet 5.5 , Default
Slice | pay split logic
Prompt | Read AGENTS.md. I’m implementing Slice 1. The function split_evenly(total_cents, parts) already exists in src/services/fee_split.py, and I wrote it myself. Don’t change it. Write tests in tests/test_fee_split.py for these requirements: R22: each participant gets the delivery fee divided by the number of participants, rounded down to whole cents. R23: leftover cents are given one at a time, starting with the last participant and moving toward the first. R24: the shares always sum to exactly the fee. Required examples: 100 across 3 gives [33, 33, 34]; 101 across 3 gives [33, 34, 34]; 2 across 5 gives [0, 0, 0, 1, 1]; 300 across 3 gives [100, 100, 100]; 499 across 1 gives [499]. Also a loop over many totals and group sizes checking the sum and that shares differ by at most 1 cent; parts below 1 or a negative total raises ValueError. Only edit tests/test_fee_split.py. No new dependencies. If you think my function has a bug, tell me instead of fixing it.
What I verfied | that the logic for the tests make sense and that it would check the case there is a not even distribution of cost for each person. I also had mutation check to see if it tracks the changes. 
What I changed and why | for this one I did not change anything I made the algorithm for fee splitting, just had it makes the tests which it is good at doing. 
Outcome | test for the function and commit ready code. 

Entry 6: activity timer
Field | entry
Entry # / date | 6
Tool, model, node | kiro, Sonnect 5.5, Default
Slice | pay split logic
Prompt | Read AGENTS.md and src/clock.py. I'm implementing Slice 2. I wrote the class ActivityTimer myself in
src/services/activity_timer.py. Do not change it. Write tests in tests/test_activity_timer.py for this
requirement: WHEN any request reaches an OPEN or LOCKED group order whose last activity was 2 hours
or more ago (exactly 2:00:00 counts), THE SYSTEM SHALL set its status to EXPIRED. The class takes a
clock object with a now() method, and a ttl that defaults to 2 hours. Test with a fake clock: a new
timer is not expired; 1:59:59 is not expired; exactly 2:00:00 is expired; 2:00:01 is expired; touch()
restarts the countdown; a custom ttl works. Add a test that fails if the code calls the real datetime.now()
instead of the clock. If the interface of src/clock.py differs from what my class expects, tell me instead
of changing my class. Only edit tests/test_activity_timer.py. No new dependencies. If you think my code
has a bug, tell me instead of fixing it.
What I verified | that the logic was sound and did check the different scenarios I was looking at. 
What I changed | nothing I did the algorithm so it was just tasked to tests
Outcome | tests for the function and commit ready code. 

