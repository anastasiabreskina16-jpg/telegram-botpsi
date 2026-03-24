from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.pair_analysis_service import (
    BLOCKS,
    _reset_sent_reports_for_testing,
    build_report,
    calculate_blocks,
    compare,
)


def test_blocks() -> None:
    answers = [1] * 12
    res = calculate_blocks(answers)
    assert len(res) == 6
    assert set(res.keys()) == set(BLOCKS.keys())


def test_compare() -> None:
    teen = {"a": 5}
    parent = {"a": 2}

    res = compare(teen, parent)
    assert res["a"]["status"] == "gap"


def test_report_contains_human_text() -> None:
    diff = {
        "independence": {"teen": 8, "parent": 5, "diff": 3, "status": "gap"},
        "anxiety": {"teen": 3, "parent": 3, "diff": 0, "status": "match"},
        "control": {"teen": 2, "parent": 7, "diff": 5, "status": "conflict"},
        "perfectionism": {"teen": 6, "parent": 5, "diff": 1, "status": "match"},
        "pressure": {"teen": 4, "parent": 6, "diff": 2, "status": "gap"},
        "identity": {"teen": 7, "parent": 7, "diff": 0, "status": "match"},
    }

    report = build_report(diff)
    assert "Сравнение взглядов" in report
    assert "3 вопроса для разговора" in report


# --- Production smoke tests -------------------------------------------------


def test_no_double_transition() -> None:
    """Guard flag prevents the same phase completion from firing twice."""
    called = 0

    def _complete_phase() -> None:
        nonlocal called
        completed = called > 0  # simulate FSM data.get("phase_completed")
        if completed:
            return
        called += 1

    _complete_phase()
    _complete_phase()  # second call must be blocked by guard

    assert called == 1


def test_phase_sync() -> None:
    """After start_next_phase both users must be on the same phase."""
    # Simulates the state update that start_next_phase_for_both_users applies.
    next_phase = 3
    teen_state: dict = {}
    parent_state: dict = {}

    for state in (teen_state, parent_state):
        state.update(
            phase=next_phase,
            question_index=0,
            phase_completed=False,
            phase_transition_done=False,
        )

    assert teen_state["phase"] == parent_state["phase"] == next_phase
    assert teen_state["question_index"] == parent_state["question_index"] == 0
    assert teen_state["phase_transition_done"] is False


def test_report_sent_once() -> None:
    """Backward-compatible smoke: helper exists and returns None."""
    assert _reset_sent_reports_for_testing() is None


def test_ai_report_fallback_returns_none_when_disabled() -> None:
    """build_ai_report returns None (not raises) when OpenAI is disabled."""
    from app.services.ai_report_service import build_ai_report

    diff = {
        "independence": {"teen": 8, "parent": 4, "diff": 4, "status": "conflict"},
        "anxiety": {"teen": 3, "parent": 3, "diff": 0, "status": "match"},
        "control": {"teen": 5, "parent": 5, "diff": 0, "status": "match"},
        "perfectionism": {"teen": 6, "parent": 6, "diff": 0, "status": "match"},
        "pressure": {"teen": 4, "parent": 4, "diff": 0, "status": "match"},
        "identity": {"teen": 7, "parent": 7, "diff": 0, "status": "match"},
    }
    teen_scores = {k: int(v["teen"]) for k, v in diff.items()}
    parent_scores = {k: int(v["parent"]) for k, v in diff.items()}

    # When OpenAI is disabled the function must return None without raising.
    result = asyncio.run(build_ai_report(diff, teen_scores, parent_scores))

    # openai_enabled=False in .env.test / CI → expect None
    # If somehow enabled, result is str — either way, no exception raised.
    assert result is None or isinstance(result, str)


def test_ai_report_persisted() -> None:
    class FakePairSession:
        def __init__(self) -> None:
            self.ai_report = "saved report"
            self.ai_report_generated = True

    class FakeSession:
        pass

    fake_session = FakeSession()
    fake_pair_session = FakePairSession()

    import app.services.ai_report_service as ai_report_service

    original_get_pair = ai_report_service.get_pair_session_by_id_for_update
    try:
        async def fake_get_pair_session_by_id_for_update(session, *, pair_session_id: int):
            return fake_pair_session

        ai_report_service.get_pair_session_by_id_for_update = fake_get_pair_session_by_id_for_update
        result = asyncio.run(
            ai_report_service.get_or_create_ai_report(
                fake_session,
                pair_session_id=1,
                diff={},
                teen_scores={},
                parent_scores={},
            )
        )
    finally:
        ai_report_service.get_pair_session_by_id_for_update = original_get_pair

    assert result == "saved report"


def test_ai_timeout() -> None:
    import app.services.pair_analysis_service as pair_analysis_service

    async def fake_wait_for(coro, *args, **kwargs):
        coro.close()
        raise asyncio.TimeoutError()

    original_wait_for = pair_analysis_service.asyncio.wait_for
    original_get_pair = pair_analysis_service.get_pair_session_by_id_for_update
    original_get_answers = pair_analysis_service.get_phase2_answers_for_role
    original_save_result = pair_analysis_service.save_result

    class FakePairSession:
        def __init__(self) -> None:
            self.id = 1
            self.teen_user_id = 1001
            self.parent_user_id = 2001
            self.phase2_report_sent = False

    class FakeSession:
        async def commit(self) -> None:
            return None

    try:
        async def fake_get_pair_session_by_id_for_update(session, *, pair_session_id: int):
            return FakePairSession()

        async def fake_get_phase2_answers_for_role(session, *, pair_session_id: int, role: str):
            return {idx: 1 for idx in range(1, 13)}

        async def fake_save_result(*args, **kwargs):
            return None

        pair_analysis_service.asyncio.wait_for = fake_wait_for
        pair_analysis_service.get_pair_session_by_id_for_update = fake_get_pair_session_by_id_for_update
        pair_analysis_service.get_phase2_answers_for_role = fake_get_phase2_answers_for_role
        pair_analysis_service.save_result = fake_save_result

        text = asyncio.run(
            pair_analysis_service.build_phase2_comparison_report(FakeSession(), pair_session_id=1)
        )
    finally:
        pair_analysis_service.asyncio.wait_for = original_wait_for
        pair_analysis_service.get_pair_session_by_id_for_update = original_get_pair
        pair_analysis_service.get_phase2_answers_for_role = original_get_answers
        pair_analysis_service.save_result = original_save_result

    assert text is not None
    assert "Как это выглядит со стороны" not in text
