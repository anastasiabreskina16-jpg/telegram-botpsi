from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.handlers import observation as observation_handler
from app.states.observation import ObservationStates


class _FakeState:
    def __init__(self, data: dict | None = None) -> None:
        self.data = dict(data or {})
        self.current_state: str | None = None

    async def get_data(self) -> dict:
        return dict(self.data)

    async def update_data(self, **kwargs) -> None:
        self.data.update(kwargs)

    async def set_state(self, next_state) -> None:
        self.current_state = getattr(next_state, "state", next_state)

    async def clear(self) -> None:
        self.data.clear()
        self.current_state = None


class _FakeMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.from_user = SimpleNamespace(id=123, username="tester")
        self.sent: list[str] = []

    async def answer(self, text: str, reply_markup=None) -> None:
        self.sent.append(text)


class _FakeSession:
    def __init__(self) -> None:
        self.commit = AsyncMock()


class _FakeSessionContext:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> _FakeSession:
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class ObservationReflectionSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_next_question_with_progress(self) -> None:
        state = _FakeState(
            {
                "pair_task_id": 10,
                "reflection_role": "teen",
                "reflection_task_code": "interest_moments",
                "reflection_question_code": "teen_reflection_q1",
            }
        )
        message = _FakeMessage("Мой ответ")
        session = _FakeSession()
        questions = [
            ("q1", "Первый вопрос"),
            ("q2", "Второй вопрос"),
            ("q3", "Третий вопрос"),
        ]

        with (
            patch.object(observation_handler, "AsyncSessionLocal", return_value=_FakeSessionContext(session)),
            patch.object(observation_handler, "get_or_create_user", AsyncMock(return_value=(SimpleNamespace(id=77), False))),
            patch.object(observation_handler, "save_pair_task_response", AsyncMock()),
            patch.object(observation_handler, "get_user_answers_count", AsyncMock(return_value=1)),
            patch.object(observation_handler, "get_reflection_questions_for_role", return_value=questions),
        ):
            await observation_handler._handle_pair_task_reflection_answer(message, state)

        self.assertEqual(state.current_state, ObservationStates.entering_pair_task_reflection_2.state)
        self.assertEqual(state.data["reflection_question_code"], "q2")
        self.assertEqual(message.sent, ["Вопрос 2/3\n\nВторой вопрос"])
        session.commit.assert_awaited_once()

    async def test_finishes_phase_and_waits_for_other_user(self) -> None:
        state = _FakeState(
            {
                "pair_task_id": 10,
                "reflection_role": "teen",
                "reflection_task_code": "interest_moments",
                "reflection_question_code": "teen_reflection_q2",
            }
        )
        message = _FakeMessage("Финальный ответ")
        session = _FakeSession()
        questions = [
            ("q1", "Первый вопрос"),
            ("q2", "Второй вопрос"),
        ]

        with (
            patch.object(observation_handler, "AsyncSessionLocal", return_value=_FakeSessionContext(session)),
            patch.object(observation_handler, "get_or_create_user", AsyncMock(return_value=(SimpleNamespace(id=77), False))),
            patch.object(observation_handler, "save_pair_task_response", AsyncMock()),
            patch.object(observation_handler, "get_user_answers_count", AsyncMock(return_value=2)),
            patch.object(observation_handler, "get_reflection_questions_for_role", return_value=questions),
            patch.object(observation_handler, "both_users_completed_phase", AsyncMock(return_value=False)),
        ):
            await observation_handler._handle_pair_task_reflection_answer(message, state)

        self.assertEqual(state.current_state, ObservationStates.in_pair_task_menu.state)
        self.assertEqual(message.sent, ["Вы завершили фазу. Ожидаем второго участника."])
        session.commit.assert_awaited_once()

    async def test_moves_to_next_phase_when_both_roles_done(self) -> None:
        state = _FakeState(
            {
                "pair_task_id": 10,
                "reflection_role": "parent",
                "reflection_task_code": "interest_moments",
                "reflection_question_code": "parent_reflection_q2",
            }
        )
        message = _FakeMessage("Финальный ответ")
        session = _FakeSession()
        questions = [
            ("q1", "Первый вопрос"),
            ("q2", "Второй вопрос"),
        ]

        with (
            patch.object(observation_handler, "AsyncSessionLocal", return_value=_FakeSessionContext(session)),
            patch.object(observation_handler, "get_or_create_user", AsyncMock(return_value=(SimpleNamespace(id=88), False))),
            patch.object(observation_handler, "save_pair_task_response", AsyncMock()),
            patch.object(observation_handler, "get_user_answers_count", AsyncMock(return_value=2)),
            patch.object(observation_handler, "get_reflection_questions_for_role", return_value=questions),
            patch.object(observation_handler, "both_users_completed_phase", AsyncMock(return_value=True)),
        ):
            await observation_handler._handle_pair_task_reflection_answer(message, state)

        self.assertEqual(state.current_state, ObservationStates.in_pair_task_menu.state)
        self.assertEqual(message.sent, ["Переходим к следующей фазе."])
        session.commit.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()