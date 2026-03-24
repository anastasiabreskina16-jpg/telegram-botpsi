---
name: mvp-step
description: Run one MVP step end-to-end: inspect, plan, implement, review, validate.
context: fork
agent: mvp-coordinator
---

# MVP Step

Task: $ARGUMENTS

Rules:
- Work only on the current step.
- Do not move to the next product stage.
- First inspect relevant files and explain current blockers briefly.
- Then make a short plan.
- Then implement only the requested step.
- Then ask the code-reviewer subagent to review the patch.
- Then run validation commands.
- Then return:
  1. changed files
  2. what changed
  3. review findings
  4. validation results
  5. remaining blockers

Current product focus:
- stable /start
- role selection
- role persistence
- repeated /start behavior
- no test flow yet
- no scoring yet
- no AI report yet
- no Docker/Alembic changes unless explicitly requested