from __future__ import annotations

from app.services.dialogue_test_data import PHASE2_QUESTIONS, PHASE3_SCENARIOS, PHASE4_VALUES

PHASE_1_QUESTION = {
    "text": "Когда думаешь о будущем — что чувствуешь?",
    "type": "scale_1_10",
}

PAIR_QUESTIONS: dict[int, dict[str, list[str]]] = {
    2: {
        "teen": [q["teenager"] for q in PHASE2_QUESTIONS],
        "parent": [q["parent"] for q in PHASE2_QUESTIONS],
    }
}

SCENARIOS = [
    {
        "text": scenario["situation"],
        "teen_options": list(scenario["teenager_options"]),
        "parent_options": list(scenario["parent_options"]),
    }
    for scenario in PHASE3_SCENARIOS
]

VALUES = list(PHASE4_VALUES)


def get_phase_questions_for_role(phase: int, role: str) -> list[str]:
    if role not in ["teen", "parent"]:
        raise ValueError("Invalid role")
    phase_questions = PAIR_QUESTIONS.get(phase)
    if phase_questions is None:
        return []
    return list(phase_questions[role])


def get_phase_question(phase: int, role: str, index: int) -> str:
    questions = get_phase_questions_for_role(phase, role)
    if index < 0 or index >= len(questions):
        raise IndexError("Question index out of range")
    return questions[index]
