Fix bug in aiogram bot.

Problem:
inline buttons not working

Root cause:
catch-all callback handler in pair_test.py

Task:
1. remove handler
2. do not touch other logic

Constraints:
- no refactor
- no renaming