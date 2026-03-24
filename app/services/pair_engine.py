"""Pair dialogue engine — spec-driven step coordination.

Responsibilities:
- read the scenario spec (PAIR_SCENARIO)
- provide pure helpers: get_current_step, get_next_question, format_message
- provide try_transition: single call-site for phase completion logic

Imports from handlers use lazy imports to avoid circular dependencies.
"""
from __future__ import annotations

import builtins

from app.scenario.pair_scenario import PAIR_SCENARIO


def get_current_step(state: builtins.dict) -> builtins.dict:
    """Return the scenario spec for the current phase."""
    phase = state["phase"]
    return PAIR_SCENARIO[phase]


def get_next_question(
    state: builtins.dict,
) -> builtins.tuple[builtins.list[builtins.str], builtins.int]:
    """Return (opener messages, current question index) for the current phase."""
    phase = state["phase"]
    index = state["question_index"]
    step = PAIR_SCENARIO[phase]
    return step["messages"], index


def format_message(messages: builtins.list[builtins.str]) -> builtins.str:
    """Join scenario opener messages into a single bot message."""
    return "\n\n".join(messages)


async def try_transition(
    session,
    *,
    pair_session_id: builtins.int,
    phase: builtins.int,
    bot,
    dispatcher,
) -> builtins.bool:
    """Check whether both users finished *phase* and trigger the cross-user
    phase transition if so.

    Returns True when the transition was started (both users done).
    Returns False when the current user is done but the other is not yet.

    Call this once after every answer that could complete a phase.
    """
    from sqlalchemy import and_, select

    from app.db.models import PairTestAnswer
    from app.services.pair_test_service import get_dialogue_progress
    from app.handlers.pair_test import start_next_phase_for_both_users

    progress = await get_dialogue_progress(session, pair_session_id=pair_session_id)
    phase_key = f"phase{phase}"
    phase_payload = progress.get(phase_key)
    if builtins.isinstance(phase_payload, builtins.dict) and phase_payload.get("completed"):
        marker_result = await session.execute(
            select(PairTestAnswer)
            .where(
                and_(
                    PairTestAnswer.pair_test_session_id == pair_session_id,
                    PairTestAnswer.block_id == phase,
                    PairTestAnswer.role.in_(("teen", "parent")),
                )
            )
            .order_by(PairTestAnswer.updated_at.desc(), PairTestAnswer.id.desc())
            .limit(1)
        )
        marker = marker_result.scalar_one_or_none()
        if marker is not None:
            if marker.locked:
                return False
            marker.locked = True
            marker.status = "completed"
            await session.commit()

        await start_next_phase_for_both_users(
            session,
            pair_session_id=pair_session_id,
            current_phase=phase,
            bot=bot,
            dispatcher=dispatcher,
        )
        return True

    role_status = phase_payload if builtins.isinstance(phase_payload, builtins.dict) else {}
    teen_done = builtins.bool(role_status.get("teen", {}).get("done", role_status.get("teen_done", False)))
    parent_done = builtins.bool(role_status.get("parent", {}).get("done", role_status.get("parent_done", False)))
    if teen_done ^ parent_done:
        partial_role = "teen" if teen_done else "parent"
        partial_result = await session.execute(
            select(PairTestAnswer)
            .where(
                and_(
                    PairTestAnswer.pair_test_session_id == pair_session_id,
                    PairTestAnswer.block_id == phase,
                    PairTestAnswer.role == partial_role,
                )
            )
            .order_by(PairTestAnswer.updated_at.desc(), PairTestAnswer.id.desc())
            .limit(1)
        )
        partial_answer = partial_result.scalar_one_or_none()
        if partial_answer is not None and partial_answer.status != "partial":
            partial_answer.status = "partial"
            await session.commit()

    return False
