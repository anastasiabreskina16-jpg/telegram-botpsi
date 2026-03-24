import sys
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.pair_task_service import (
    get_reflection_questions_for_role,
    render_pair_task_text,
)
from app.services.pair_task_templates import PAIR_TASK_TEMPLATES


class PairTaskServiceSmokeTests(unittest.TestCase):
    def test_templates_have_expected_count_and_fields(self) -> None:
        self.assertEqual(len(PAIR_TASK_TEMPLATES), 10)

        required = {
            "task_code",
            "title",
            "short_description",
            "teen_instruction",
            "parent_observation_focus",
            "steps",
            "teen_reflection_questions",
            "parent_reflection_questions",
            "summary_hint",
        }
        for code, template in PAIR_TASK_TEMPLATES.items():
            self.assertEqual(template.get("task_code"), code)
            self.assertTrue(required.issubset(template.keys()))
            self.assertIsInstance(template["steps"], list)
            self.assertGreaterEqual(len(template["steps"]), 3)

    def test_reflection_questions_exist_for_both_roles(self) -> None:
        teen_questions = get_reflection_questions_for_role("teen", task_code="interest_moments")
        parent_questions = get_reflection_questions_for_role("parent", task_code="interest_moments")

        self.assertGreaterEqual(len(teen_questions), 1)
        self.assertGreaterEqual(len(parent_questions), 1)

    def test_legacy_code_aliases_work(self) -> None:
        legacy_questions = get_reflection_questions_for_role("teen", task_code="three_interest_moments")
        self.assertGreaterEqual(len(legacy_questions), 1)

    def test_render_includes_required_sections(self) -> None:
        pair_task = SimpleNamespace(
            task_code="interest_moments",
            title="Три момента интереса",
            status="active",
            description="stub",
        )
        text = render_pair_task_text(pair_task)

        self.assertIn("Что делает подросток:", text)
        self.assertIn("Что наблюдает родитель:", text)
        self.assertIn("Шаги:", text)


if __name__ == "__main__":
    unittest.main()
