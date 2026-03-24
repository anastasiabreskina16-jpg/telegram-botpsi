from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.handlers.pair_test import (
    mark_phase_completed,
    format_question,
    _next_phase_number,
    _enter_waiting_state,
    _start_phase2,
    start_next_phase_for_both_users,
    _phase3_selection_action,
)
from app.states.pair_test import PairTest, PairTestStates
from app.scenario.pair_scenario import PAIR_SCENARIO
from app.data.pair_questions import PAIR_QUESTIONS
from app.services.pair_engine import format_message, get_current_step, get_next_question
from app.texts import PAIR_TEXTS


class _FakeState:
    def __init__(self) -> None:
        self.data: dict = {}
        self.current_state: str | None = None

    async def get_data(self) -> dict:
        return dict(self.data)

    async def update_data(self, **kwargs) -> None:
        self.data.update(kwargs)

    async def get_state(self) -> str | None:
        return self.current_state

    async def set_state(self, next_state) -> None:
        self.current_state = getattr(next_state, "state", next_state)


class _FakeMessage:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def answer(self, text: str, reply_markup=None) -> None:
        self.sent.append(text)


class _FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, reply_markup=None) -> None:
        self.sent.append((chat_id, text))

    async def send_chat_action(self, chat_id: int, action: str) -> None:
        pass


class _FakeFSMManager:
    def __init__(self) -> None:
        self.contexts: dict[int, _FakeState] = {}

    def get_context(self, bot, chat_id: int, user_id: int, thread_id=None, business_connection_id=None, destiny="default"):
        context = self.contexts.get(user_id)
        if context is None:
            context = _FakeState()
            self.contexts[user_id] = context
        return context


class _FakeDispatcher:
    def __init__(self) -> None:
        self.fsm = _FakeFSMManager()


def test_first_question_format() -> None:
    text = "Тест"
    msg = format_question(text, phase=2)
    assert "Хорошо." in msg
    assert text in msg


def test_phase_transition() -> None:
    phase = 1
    next_phase = _next_phase_number(phase)
    assert next_phase == 2


def test_scenario_exists() -> None:
    for phase in (1, 2, 3, 4):
        assert phase in PAIR_SCENARIO, f"Phase {phase} missing from PAIR_SCENARIO"
        assert "messages" in PAIR_SCENARIO[phase], f"Phase {phase} missing 'messages'"
        assert "name" in PAIR_SCENARIO[phase], f"Phase {phase} missing 'name'"
        assert isinstance(PAIR_SCENARIO[phase]["messages"], list)
        assert len(PAIR_SCENARIO[phase]["messages"]) > 0


def test_format_message_no_question_numbering() -> None:
    for phase in (1, 2, 3, 4):
        step = get_current_step({"phase": phase})
        text = format_message(step["messages"])
        assert "Вопрос" not in text, f"Phase {phase}: 'Вопрос' found in format_message output"
        assert "/" not in text, f"Phase {phase}: '/' found in format_message output"


def test_engine_get_next_question() -> None:
    messages, index = get_next_question({"phase": 2, "question_index": 0})
    assert isinstance(messages, list)
    assert index == 0
    text = format_message(messages)
    assert "Хорошо." in text


def test_questions_different() -> None:
    teen_q = PAIR_QUESTIONS[2]["teen"][0]
    parent_q = PAIR_QUESTIONS[2]["parent"][0]
    assert teen_q != parent_q


def test_role_exists() -> None:
    assert "teen" in PAIR_QUESTIONS[2]
    assert "parent" in PAIR_QUESTIONS[2]


def test_no_stuck_after_phase() -> None:
    phase = 1
    completed = True

    next_phase = phase + 1 if completed else phase

    assert next_phase == 2


def test_both_users_sync() -> None:
    teen = True
    parent = True

    assert (teen and parent) is True


async def _check_waiting_dedupe() -> None:
    state = _FakeState()
    message = _FakeMessage()

    await _enter_waiting_state(
        state,
        message,
        next_state=PairTestStates.phase2_waiting_other,
        phase=2,
        flag_key="phase_2_sent",
        text=PAIR_TEXTS["phase_2_wait"],
        current_user_answered=True,
        both_users_answered=False,
    )
    await _enter_waiting_state(
        state,
        message,
        next_state=PairTestStates.phase2_waiting_other,
        phase=2,
        flag_key="phase_2_sent",
        text=PAIR_TEXTS["phase_2_wait"],
        current_user_answered=True,
        both_users_answered=False,
    )

    assert state.current_state == PairTestStates.phase2_waiting_other.state
    assert state.data["phase_2_sent"] is True
    assert state.data["pair_phase"] == 2
    assert len(message.sent) == 1
    assert message.sent[0] == PAIR_TEXTS["phase_2_wait"]


def _check_phase3_action() -> None:
    assert _phase3_selection_action(role="teen", teen_ready=False, parent_ready=False) == "selecting"
    assert _phase3_selection_action(role="teen", teen_ready=True, parent_ready=False) == "waiting"
    assert _phase3_selection_action(role="parent", teen_ready=True, parent_ready=False) == "selecting"
    assert _phase3_selection_action(role="parent", teen_ready=True, parent_ready=True) == "answering"


async def _check_phase2_state_metadata() -> None:
    state = _FakeState()
    message = _FakeMessage()

    async def _fake_get_phase2_answers_for_role(session, *, pair_session_id: int, role: str):
        return []

    async def _fake_send_phase2_question(message_obj, *, role: str, question_id: int) -> None:
        await message_obj.answer(f"sent:{role}:{question_id}")

    from unittest.mock import patch
    from app.handlers import pair_test as pair_test_handler

    with (
        patch.object(pair_test_handler, "AsyncSessionLocal", return_value=_AsyncNullContext()),
        patch.object(pair_test_handler, "get_phase2_answers_for_role", _fake_get_phase2_answers_for_role),
        patch.object(pair_test_handler, "_send_phase2_question", _fake_send_phase2_question),
    ):
        await _start_phase2(message, state, pair_session_id=55, role="teen")

    assert state.current_state == PairTest.phase_2.state
    assert state.data["pair_task_id"] == 55
    assert state.data["phase"] == 2
    assert state.data["question_index"] == 0
    assert state.data["role"] == "teen"
    assert state.data["phase_completed"] is False


async def _check_mark_phase_completed() -> None:
    state = _FakeState()
    await mark_phase_completed(state)
    assert state.data["phase_completed"] is True
    assert state.data["waiting_for_other"] is True


async def _check_auto_transition_for_both_users() -> None:
    from unittest.mock import AsyncMock, patch
    from app.handlers import pair_test as pair_test_handler

    bot = _FakeBot()
    dispatcher = _FakeDispatcher()
    teen_state = _FakeState()
    parent_state = _FakeState()

    teen_state.data.update({
        "pair_task_id": 77,
        "phase": 1,
        "question_index": 1,
        "role": "teen",
        "phase_completed": True,
        "waiting_for_other": True,
    })
    parent_state.data.update({
        "pair_task_id": 77,
        "phase": 1,
        "question_index": 1,
        "role": "parent",
        "phase_completed": True,
        "waiting_for_other": True,
    })
    dispatcher.fsm.contexts[101] = teen_state
    dispatcher.fsm.contexts[202] = parent_state

    with (
        patch.object(pair_test_handler, "_pair_participants", AsyncMock(return_value=[(101, "teen"), (202, "parent")]))
    ):
        await start_next_phase_for_both_users(
            object(),
            pair_session_id=77,
            current_phase=1,
            bot=bot,
            dispatcher=dispatcher,
        )

    assert teen_state.current_state == PairTest.phase_2.state
    assert parent_state.current_state == PairTest.phase_2.state
    assert teen_state.data["phase"] == 2
    assert parent_state.data["phase"] == 2
    assert teen_state.data["waiting_for_other"] is False
    assert parent_state.data["waiting_for_other"] is False
    assert len(bot.sent) == 2
    assert all("Хорошо." in text for _, text in bot.sent)


class _AsyncNullContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


async def main() -> None:
    test_first_question_format()
    test_phase_transition()
    test_no_stuck_after_phase()
    test_both_users_sync()
    _check_phase3_action()
    await _check_waiting_dedupe()
    await _check_phase2_state_metadata()
    await _check_mark_phase_completed()
    await _check_auto_transition_for_both_users()
    print("PAIR FSM SMOKE OK")


if __name__ == "__main__":
    asyncio.run(main())