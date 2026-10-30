# AGENTS.md (rules for the AI assistant)

- Language: Python 3, FastAPI. Tests: pytest.
- Layers: routes -> services -> repository. No SQL. No business rules in routes. The memory for this project is going to be a txt file. 
- Time: never call datetime.now() in rules. Accept an injected clock.
- Money: integer cents only. Never floats.
- Do not add dependencies. Do not create files I did not name.
- Only edit the files listed in the prompt. Tests first, then implementation.
- Follow docs/requirements.md; if a requirement is unclear, ask instead of guessing.
