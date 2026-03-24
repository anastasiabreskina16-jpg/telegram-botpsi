# CLAUDE.md

## Project Overview
This project is an MVP Telegram bot for psychology-based AI career guidance.

Main audience:
- teenagers 12–17
- parents

Main product flow:
1. User opens the Telegram bot
2. Chooses role: teenager or parent
3. Completes a test
4. Answers are saved
5. System builds a structured profile
6. AI generates a readable report
7. Bot offers next step: consultation or development route

## Product Goals
This is not a general chatbot.
This is a structured diagnostic bot with AI-generated reporting.

Core value:
- collect answers reliably
- build structured scoring output
- convert structured profile into clear human-readable report
- guide user to the next step

## MVP Scope
The MVP must cover only:

1. `/start`
2. role selection
3. FSM test flow
4. answer persistence
5. scoring into structured JSON
6. AI report stub
7. final result screen with CTA

## Current Development Priorities
Work in this order unless explicitly told otherwise:

1. config + db session + models
2. `/start` + role selection
3. `TestSession` + FSM flow with 3–5 hardcoded questions
4. answer persistence
5. scoring to structured JSON
6. report stub
7. final result screen + CTA
8. restart / cancel handling
9. logging and cleanup
10. Docker later

Do not skip ahead unless requested.

## Architecture Rules
Keep the code simple, modular, and MVP-focused.

### General rules
- Keep handlers thin
- Put business logic into `services/`
- Database access only through `db/` layer or repository functions
- Do not mix Telegram transport logic with scoring or reporting logic
- Do not refactor unrelated files
- Add code incrementally
- Prefer simple, safe implementations over clever abstractions

### Expected structure
Preferred structure:

- `main.py`
- `config.py`
- `states.py`
- `handlers/`
- `services/`
- `db/`
- `keyboards/`

### Responsibilities
- `handlers/` → Telegram update handling only
- `services/` → business logic
- `db/` → models, session, repository access
- `keyboards/` → Telegram keyboards
- `states.py` → FSM states
- `config.py` → `.env` settings
- `main.py` → app entrypoint and router registration

## Data Model Rules
Current minimal models:

- `User`
- `TestSession`
- `Answer`

### User
Should store only minimal useful Telegram user info for MVP:
- telegram_id
- role
- username
- first_name
- created_at

### TestSession
Used to track one test run:
- user_id
- role_snapshot
- status
- started_at
- completed_at

### Answer
Used to store test answers:
- session_id
- user_id
- question_code
- answer_value
- created_at

### Important constraints
- Keep `role` as simple string for now
- Keep `question_code` as string
- Keep `answer_value` as string
- No enums unless clearly needed
- No premature normalization
- No complex analytics fields yet
- Do not add unnecessary sensitive personal data

## AI / Scoring Rules
The AI must not invent the whole result from scratch.

Required logic:
1. answers are collected
2. scoring logic builds structured profile
3. report service turns structured profile into readable text

### Scoring
`services/scoring.py` should:
- accept stored answers
- return structured JSON / dict
- be deterministic and testable
- contain no Telegram-specific logic

### Report
`services/report.py` should:
- accept structured profile
- return readable text
- start as a stub
- remain replaceable later with a real LLM call

## Workflow Rules for Claude
Before changing code:
- inspect relevant files first
- explain current flow briefly
- identify what must change
- for non-trivial tasks, provide a short step-by-step plan

When implementing:
- implement only the requested step
- modify only necessary files
- keep scope tight
- avoid unrelated cleanup
- do not redesign the whole project unless explicitly asked

After implementing:
- list changed files
- explain what changed
- explain why those files changed
- provide validation commands
- report remaining issues honestly

## Validation Rules
Always verify the result.

Preferred order:
1. targeted checks for changed modules
2. import checks
3. minimal runtime or async smoke checks
4. broader checks only if needed

At minimum verify:
- imports work
- DB engine/session can be created
- models load correctly
- obvious runtime errors are absent

If tests do not exist:
- add minimal tests only for critical pure logic
- do not create large test suites during early MVP steps

## Code Style Rules
- Use Python 3.11
- Prefer clear and explicit code
- Use type hints where helpful
- Keep functions focused
- Avoid unnecessary abstractions
- Avoid overly generic helper layers
- Avoid magic behavior
- Keep naming consistent and simple

## Non-Goals
Do not add these unless explicitly requested:
- full production architecture
- Docker-first workflow
- Alembic too early
- admin panels
- payment systems
- advanced analytics
- PDF generation
- CRM features
- multi-tenant design
- complex AI orchestration
- heavy refactoring
- extra bot features beyond MVP scope

## Safety / Data Handling
This project touches psychology and minors, so be conservative.

Rules:
- avoid collecting unnecessary sensitive data
- store only what is needed for MVP
- do not fabricate official personal data
- prefer placeholders over guessed facts
- keep business logic deterministic where possible

## Output Expectations
When asked to implement a task, respond with:

1. short restatement of the task
2. files to create/change
3. assumptions
4. full code for changed files
5. short explanation per file
6. validation commands
7. remaining limitations

## Current Product Interpretation
Treat this project as:
- a diagnostic Telegram bot
- not a free-form therapist bot
- not a generic AI assistant
- not a large platform yet

The main priority is a stable flow:
`/start -> role -> test -> save answers -> scoring -> report -> CTA`