# Project AI instructions

We are building an MVP Telegram bot for psychology-based AI career guidance.

Current priorities:
1. stable /start
2. role selection
3. local smoke test
4. test flow later
5. scoring later
6. AI report later

Architecture rules:
- handlers contain Telegram transport logic only
- business logic goes to services
- db logic stays in db layer
- keep code simple and practical
- avoid unnecessary abstractions
- do not refactor unrelated files
- do not add extra features unless explicitly requested

Current product rules:
- this is a structured diagnostic bot, not a free-form chatbot
- role values must stay simple strings
- do not add complex data fields too early
- do not move to scoring or report until the current step is stable

Current working focus:
- config consistency
- one final models.py version
- /start -> teen/parent -> save role -> repeated /start shows role

Validation expectations:
- imports must work
- models must load
- DB session must initialize
- local smoke test must pass before new features are added

When suggesting code:
- prefer minimal changes
- explain changed files briefly
- include validation commands
- mention blockers honestly