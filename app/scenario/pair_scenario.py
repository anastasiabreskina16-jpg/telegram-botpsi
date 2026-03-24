"""Spec-driven pair dialogue scenario.

Each phase entry defines:
- name      : phase identifier
- messages  : conversational opener(s) shown before the actual question content
- type      : interaction type used by the engine / UI layer
- options   : (optional) static options for choice / multi_choice phases

The actual question data (survey items, scenarios, values) lives in
app/services/dialogue_test_data.py.  This file owns only the UX structure.
"""

PAIR_SCENARIO: dict[int, dict] = {
    1: {
        "name": "emotion",
        "messages": [
            "Давай начнём с простого.",
        ],
        "type": "choice",
        "options": ["Спокойствие", "Интерес", "Тревогу", "Не думаю об этом"],
    },
    2: {
        "name": "exploration",
        "messages": [
            "Хорошо.",
        ],
        "type": "scale",
    },
    3: {
        "name": "conflict",
        "messages": [
            "Сейчас будет интересно 👇",
        ],
        "type": "compare",
    },
    4: {
        "name": "values",
        "messages": [
            "Выберите, что откликается:",
        ],
        "type": "multi_choice",
        "options": ["Свобода", "Деньги", "Интерес", "Стабильность", "Польза"],
    },
}
