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
WHat I changed and why | I added teh image component to the resturant and to the food item. 
Outcome | commited code and API page made. 

Entry 5: 