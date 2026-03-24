"""Service layer for the new pair scenario "Dialog about choice"."""
from __future__ import annotations

import builtins
import random
import string
from datetime import datetime, timezone

from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PairTestAnswer, PairTestSession
from app.services.retention_service import mark_pair_finished, touch_user_activity
from app.services.dialogue_test_data import (
    PHASE2_BLOCKS,
    PHASE2_BLOCKS_BY_ID,
    PHASE2_QUESTIONS,
    PHASE2_QUESTIONS_BY_ID,
    PHASE2_TOTAL_QUESTIONS,
    PHASE3_MAX_CHOICES,
    PHASE3_MIN_CHOICES,
    PHASE3_SCENARIOS_BY_ID,
    PHASE4_REQUIRED_COUNT,
    PHASE4_VALUES,
)

ValueError = builtins.ValueError

_CODE_CHARS = string.ascii_uppercase + string.digits
_CODE_LEN = 5
_AMBIGUOUS = set("0O1I")
_SAFE_CHARS = [c for c in _CODE_CHARS if c not in _AMBIGUOUS]

_ROLE_PARENT = "parent"
_ROLE_TEEN = "teen"

# Synthetic question-id ranges for phase storage in pair_test_answers.
_Q_PHASE1_SCORE = 10
_Q_PHASE1_WORD_LEN = 11
_Q_PHASE1_WORD_CHAR_BASE = 20
_Q_PHASE1_WORD_CHAR_MAX = 50

_Q_PHASE2_BASE = 200

_Q_PHASE3_SELECTED_BASE = 300
_Q_PHASE3_SELECTED_MAX = _Q_PHASE3_SELECTED_BASE + PHASE3_MAX_CHOICES - 1
_Q_PHASE3_SELECT_READY = 320
_Q_PHASE3_ANSWER_BASE = 400

_Q_PHASE4_SELECTED_BASE = 500
_Q_PHASE4_SELECTED_MAX = _Q_PHASE4_SELECTED_BASE + PHASE4_REQUIRED_COUNT - 1
_Q_PHASE4_DONE = 520


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _generate_code() -> str:
    return "".join(random.choices(_SAFE_CHARS, k=_CODE_LEN))


def _is_role(role: str) -> bool:
    return role in (_ROLE_PARENT, _ROLE_TEEN)


def _latest_answers_by_qid(answers: list[PairTestAnswer], *, role: str) -> dict[int, PairTestAnswer]:
    latest: dict[int, PairTestAnswer] = {}
    for ans in sorted(
        answers,
        key=lambda a: (
            getattr(a, "created_at", None) is None,
            getattr(a, "created_at", None),
            getattr(a, "id", 0),
        ),
    ):
        if ans.role == role:
            latest[ans.question_id] = ans
    return latest


async def _insert_answer(
    session: AsyncSession,
    *,
    pair_test_session_id: int,
    user_id: int,
    role: str,
    question_id: int,
    block_id: int,
    answer_value: int,
) -> PairTestAnswer:
    answer = PairTestAnswer(
        pair_test_session_id=pair_test_session_id,
        user_id=user_id,
        role=role,
        status="partial",
        locked=False,
        question_id=question_id,
        block_id=block_id,
        answer_value=answer_value,
        updated_at=_now(),
        reminder_sent=False,
        timeout_triggered=False,
    )
    session.add(answer)
    await session.flush()
    await touch_user_activity(
        session,
        user_id=user_id,
        pair_id=pair_test_session_id,
        question_id=question_id,
    )
    return answer


async def _clear_role_qid_range(
    session: AsyncSession,
    *,
    pair_test_session_id: int,
    role: str,
    min_qid: int,
    max_qid: int,
) -> None:
    await session.execute(
        delete(PairTestAnswer).where(
            PairTestAnswer.pair_test_session_id == pair_test_session_id,
            PairTestAnswer.role == role,
            PairTestAnswer.question_id >= min_qid,
            PairTestAnswer.question_id <= max_qid,
        )
    )


# ── Session helpers ─────────────────────────────────────────────────────────

async def get_pair_session_by_code(
    session: AsyncSession, *, pair_code: str
) -> PairTestSession | None:
    result = await session.execute(
        select(PairTestSession).where(PairTestSession.pair_code == pair_code.upper().strip())
    )
    return result.scalar_one_or_none()


async def get_pair_session_by_id(
    session: AsyncSession,
    *,
    pair_session_id: int,
) -> PairTestSession | None:
    result = await session.execute(
        select(PairTestSession).where(PairTestSession.id == pair_session_id)
    )
    return result.scalar_one_or_none()


async def get_pair_session_by_id_for_update(
    session: AsyncSession,
    *,
    pair_session_id: int,
) -> PairTestSession | None:
    result = await session.execute(
        select(PairTestSession)
        .where(PairTestSession.id == pair_session_id)
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def get_persisted_ai_report(
    session: AsyncSession,
    *,
    pair_session_id: int,
) -> str | None:
    pair_session = await get_pair_session_by_id(session, pair_session_id=pair_session_id)
    if pair_session is None or not pair_session.ai_report_generated:
        return None
    return pair_session.ai_report


async def save_persisted_ai_report(
    session: AsyncSession,
    *,
    pair_session_id: int,
    ai_report: str,
) -> PairTestSession | None:
    pair_session = await get_pair_session_by_id_for_update(session, pair_session_id=pair_session_id)
    if pair_session is None:
        return None
    pair_session.ai_report = ai_report
    pair_session.ai_report_generated = True
    await session.flush()
    return pair_session


async def get_active_pair_session_for_user(
    session: AsyncSession, *, user_id: int, role: str
) -> PairTestSession | None:
    if role == _ROLE_PARENT:
        cond = and_(
            PairTestSession.parent_user_id == user_id,
            PairTestSession.status.notin_(["completed", "cancelled", "expired"]),
        )
    else:
        cond = and_(
            PairTestSession.teen_user_id == user_id,
            PairTestSession.status.notin_(["completed", "cancelled", "expired"]),
        )
    result = await session.execute(
        select(PairTestSession).where(cond).order_by(PairTestSession.id.desc())
    )
    return result.scalars().first()


_CANCELLABLE_STATUSES = ("pending", "active", "parent_done", "teen_done")


async def get_parent_cancellable_pair_session(
    session: AsyncSession,
    *,
    parent_user_id: int,
) -> PairTestSession | None:
    result = await session.execute(
        select(PairTestSession)
        .where(
            PairTestSession.parent_user_id == parent_user_id,
            PairTestSession.status.in_(list(_CANCELLABLE_STATUSES)),
        )
        .order_by(PairTestSession.id.desc())
    )
    return result.scalars().first()


async def create_pair_session(
    session: AsyncSession,
    *,
    parent_user_id: int,
    family_link_id: int | None = None,
) -> PairTestSession:
    for _ in range(20):
        code = _generate_code()
        existing = await get_pair_session_by_code(session, pair_code=code)
        if existing is None:
            break
    else:
        raise ValueError("Could not generate unique pair code")

    pair_session = PairTestSession(
        pair_code=code,
        parent_user_id=parent_user_id,
        family_link_id=family_link_id,
        status="pending",
    )
    session.add(pair_session)
    await session.commit()
    await session.refresh(pair_session)
    return pair_session


async def join_pair_session(
    session: AsyncSession,
    *,
    pair_code: str,
    teen_user_id: int,
) -> PairTestSession:
    pair_session = await get_pair_session_by_code(session, pair_code=pair_code)
    if pair_session is None:
        raise ValueError("not_found")
    if pair_session.parent_user_id == teen_user_id:
        raise ValueError("self_join")
    if pair_session.status in ("cancelled", "expired"):
        raise ValueError("not_joinable")
    if pair_session.teen_user_id == teen_user_id:
        return pair_session
    if pair_session.teen_user_id is not None and pair_session.teen_user_id != teen_user_id:
        raise ValueError("already_joined")
    if pair_session.status not in ("pending", "parent_done"):
        raise ValueError("not_joinable")

    pair_session.teen_user_id = teen_user_id
    if pair_session.status == "pending":
        pair_session.status = "active"
    if pair_session.started_at is None:
        pair_session.started_at = _now()
    await session.commit()
    await session.refresh(pair_session)
    return pair_session


async def cancel_pair_session(
    session: AsyncSession,
    *,
    pair_session_id: int,
    parent_user_id: int,
) -> PairTestSession:
    result = await session.execute(
        select(PairTestSession).where(PairTestSession.id == pair_session_id)
    )
    pair_session = result.scalar_one_or_none()
    if pair_session is None:
        raise ValueError("not_found")
    if pair_session.parent_user_id != parent_user_id:
        raise ValueError("forbidden")
    if pair_session.status not in _CANCELLABLE_STATUSES:
        raise ValueError("not_cancellable")

    pair_session.status = "cancelled"
    pair_session.completed_at = _now()
    await session.commit()
    await session.refresh(pair_session)
    return pair_session


async def get_pair_answers_for_session(
    session: AsyncSession, *, pair_test_session_id: int
) -> list[PairTestAnswer]:
    result = await session.execute(
        select(PairTestAnswer)
        .where(PairTestAnswer.pair_test_session_id == pair_test_session_id)
        .order_by(PairTestAnswer.question_id)
    )
    return list(result.scalars().all())


async def count_pair_answers(
    session: AsyncSession,
    *,
    pair_test_session_id: int,
    user_id: int,
) -> int:
    result = await session.execute(
        select(func.count(PairTestAnswer.id)).where(
            PairTestAnswer.pair_test_session_id == pair_test_session_id,
            PairTestAnswer.user_id == user_id,
        )
    )
    return result.scalar_one()


async def mark_role_done(
    session: AsyncSession,
    *,
    pair_session_id: int,
    role: str,
) -> PairTestSession:
    result = await session.execute(
        select(PairTestSession).where(PairTestSession.id == pair_session_id)
    )
    pair_session = result.scalar_one()

    if pair_session.status in ("completed", "cancelled", "expired"):
        return pair_session

    if role == _ROLE_PARENT:
        if pair_session.status == "teen_done":
            pair_session.status = "completed"
            pair_session.completed_at = _now()
        else:
            pair_session.status = "parent_done"
    elif role == _ROLE_TEEN:
        if pair_session.status == "parent_done":
            pair_session.status = "completed"
            pair_session.completed_at = _now()
        else:
            pair_session.status = "teen_done"

    if pair_session.status == "completed":
        await mark_pair_finished(session, pair_id=pair_session_id)

    await session.commit()
    await session.refresh(pair_session)
    return pair_session


# ── Phase 1 ─────────────────────────────────────────────────────────────────

async def save_phase1_score(
    session: AsyncSession,
    *,
    pair_session_id: int,
    user_id: int,
    role: str,
    score: int,
) -> None:
    if not _is_role(role):
        raise ValueError("invalid_role")
    if score < 1 or score > 10:
        raise ValueError("invalid_score")
    await _clear_role_qid_range(
        session,
        pair_test_session_id=pair_session_id,
        role=role,
        min_qid=_Q_PHASE1_SCORE,
        max_qid=_Q_PHASE1_SCORE,
    )
    await _insert_answer(
        session,
        pair_test_session_id=pair_session_id,
        user_id=user_id,
        role=role,
        question_id=_Q_PHASE1_SCORE,
        block_id=1,
        answer_value=score,
    )
    await session.commit()


async def save_phase1_word(
    session: AsyncSession,
    *,
    pair_session_id: int,
    user_id: int,
    role: str,
    word: str,
) -> None:
    if not _is_role(role):
        raise ValueError("invalid_role")
    clean = " ".join((word or "").strip().split())
    if not clean:
        raise ValueError("empty_word")
    clean = clean[: (_Q_PHASE1_WORD_CHAR_MAX - _Q_PHASE1_WORD_CHAR_BASE + 1)]

    await _clear_role_qid_range(
        session,
        pair_test_session_id=pair_session_id,
        role=role,
        min_qid=_Q_PHASE1_WORD_LEN,
        max_qid=_Q_PHASE1_WORD_CHAR_MAX,
    )

    await _insert_answer(
        session,
        pair_test_session_id=pair_session_id,
        user_id=user_id,
        role=role,
        question_id=_Q_PHASE1_WORD_LEN,
        block_id=1,
        answer_value=len(clean),
    )
    for idx, ch in enumerate(clean):
        await _insert_answer(
            session,
            pair_test_session_id=pair_session_id,
            user_id=user_id,
            role=role,
            question_id=_Q_PHASE1_WORD_CHAR_BASE + idx,
            block_id=1,
            answer_value=ord(ch),
        )
    await session.commit()


def _decode_word(latest: dict[int, PairTestAnswer]) -> str | None:
    length_row = latest.get(_Q_PHASE1_WORD_LEN)
    if length_row is None:
        return None
    length = max(0, int(length_row.answer_value))
    chars: list[str] = []
    for idx in range(length):
        row = latest.get(_Q_PHASE1_WORD_CHAR_BASE + idx)
        if row is None:
            break
        try:
            chars.append(chr(int(row.answer_value)))
        except Exception:
            break
    text = "".join(chars).strip()
    return text or None


async def get_phase1_results(session: AsyncSession, *, pair_session_id: int) -> dict:
    answers = await get_pair_answers_for_session(session, pair_test_session_id=pair_session_id)
    teen = _latest_answers_by_qid(answers, role=_ROLE_TEEN)
    parent = _latest_answers_by_qid(answers, role=_ROLE_PARENT)

    teen_score = teen.get(_Q_PHASE1_SCORE)
    parent_score = parent.get(_Q_PHASE1_SCORE)
    teen_word = _decode_word(teen)
    parent_word = _decode_word(parent)

    payload = {
        "teen": {
            "score": int(teen_score.answer_value) if teen_score else None,
            "word": teen_word,
            "done": teen_score is not None and bool(teen_word),
        },
        "parent": {
            "score": int(parent_score.answer_value) if parent_score else None,
            "word": parent_word,
            "done": parent_score is not None and bool(parent_word),
        },
    }
    t_score = payload["teen"]["score"]
    p_score = payload["parent"]["score"]
    payload["diff"] = abs(t_score - p_score) if isinstance(t_score, int) and isinstance(p_score, int) else None
    payload["completed"] = bool(payload["teen"]["done"] and payload["parent"]["done"])
    return payload


# ── Phase 2 ─────────────────────────────────────────────────────────────────

def _phase2_qid(question_id: int) -> int:
    return _Q_PHASE2_BASE + question_id


async def save_phase2_answer(
    session: AsyncSession,
    *,
    pair_session_id: int,
    user_id: int,
    role: str,
    question_id: int,
    answer_value: int,
) -> None:
    if question_id not in PHASE2_QUESTIONS_BY_ID:
        raise ValueError("invalid_question")
    if answer_value not in (1, 2, 3, 4):
        raise ValueError("invalid_answer")
    if not _is_role(role):
        raise ValueError("invalid_role")

    qid = _phase2_qid(question_id)
    await _clear_role_qid_range(
        session,
        pair_test_session_id=pair_session_id,
        role=role,
        min_qid=qid,
        max_qid=qid,
    )
    await _insert_answer(
        session,
        pair_test_session_id=pair_session_id,
        user_id=user_id,
        role=role,
        question_id=qid,
        block_id=2,
        answer_value=answer_value,
    )
    await session.commit()


async def reset_phase2_sync_state(
    session: AsyncSession,
    *,
    pair_session_id: int,
) -> None:
    pair_session = await get_pair_session_by_id_for_update(session, pair_session_id=pair_session_id)
    if pair_session is None:
        return
    pair_session.teen_index = 0
    pair_session.parent_index = 0
    pair_session.teen_completed = False
    pair_session.parent_completed = False
    await session.commit()


async def process_phase2_answer_sync(
    session: AsyncSession,
    *,
    pair_session_id: int,
    user_id: int,
    role: str,
    question_id: int,
    answer_value: int,
) -> dict:
    if role not in (_ROLE_TEEN, _ROLE_PARENT):
        return {"status": "invalid_role"}
    if question_id not in PHASE2_QUESTIONS_BY_ID:
        return {"status": "invalid_question"}
    if answer_value not in (1, 2, 3, 4):
        return {"status": "invalid_answer"}

    pair_session = await get_pair_session_by_id_for_update(session, pair_session_id=pair_session_id)
    if pair_session is None:
        return {"status": "session_not_found"}
    if pair_session.status in ("completed", "cancelled", "expired"):
        return {"status": "session_closed"}

    is_teen = role == _ROLE_TEEN
    actor_user_id = pair_session.teen_user_id if is_teen else pair_session.parent_user_id
    if actor_user_id != user_id:
        return {"status": "forbidden"}

    own_index = pair_session.teen_index if is_teen else pair_session.parent_index
    peer_index = pair_session.parent_index if is_teen else pair_session.teen_index
    own_completed = pair_session.teen_completed if is_teen else pair_session.parent_completed

    expected_qid = own_index + 1
    if question_id != expected_qid:
        return {
            "status": "stale",
            "expected_qid": expected_qid,
            "own_index": own_index,
            "peer_index": peer_index,
        }
    if own_completed:
        return {
            "status": "already_answered",
            "expected_qid": expected_qid,
            "own_index": own_index,
            "peer_index": peer_index,
        }

    qid = _phase2_qid(question_id)
    await _clear_role_qid_range(
        session,
        pair_test_session_id=pair_session_id,
        role=role,
        min_qid=qid,
        max_qid=qid,
    )
    await _insert_answer(
        session,
        pair_test_session_id=pair_session_id,
        user_id=user_id,
        role=role,
        question_id=qid,
        block_id=2,
        answer_value=answer_value,
    )

    if is_teen:
        pair_session.teen_index = own_index + 1
        pair_session.teen_completed = True
    else:
        pair_session.parent_index = own_index + 1
        pair_session.parent_completed = True

    both_answered = bool(pair_session.teen_completed and pair_session.parent_completed)
    if both_answered:
        pair_session.teen_completed = False
        pair_session.parent_completed = False

    synced_index = min(pair_session.teen_index, pair_session.parent_index)
    phase_completed = pair_session.teen_index >= PHASE2_TOTAL_QUESTIONS and pair_session.parent_index >= PHASE2_TOTAL_QUESTIONS
    return {
        "status": "ok",
        "both_answered": both_answered,
        "phase_completed": phase_completed,
        "synced_index": synced_index,
        "next_qid": synced_index + 1,
        "wait_for_role": _ROLE_PARENT if is_teen else _ROLE_TEEN,
    }


async def get_phase2_answers_for_role(
    session: AsyncSession,
    *,
    pair_session_id: int,
    role: str,
) -> dict[int, int]:
    answers = await get_pair_answers_for_session(session, pair_test_session_id=pair_session_id)
    latest = _latest_answers_by_qid(answers, role=role)
    payload: dict[int, int] = {}
    for question in PHASE2_QUESTIONS:
        row = latest.get(_phase2_qid(question["id"]))
        if row is not None:
            payload[question["id"]] = int(row.answer_value)
    return payload


def _calc_phase2_blocks(role_answers: dict[int, int]) -> tuple[dict[int, int], int]:
    block_raw: dict[int, int] = {b["id"]: 0 for b in PHASE2_BLOCKS}
    for question in PHASE2_QUESTIONS:
        qid = question["id"]
        if qid in role_answers:
            block_raw[question["block_id"]] += role_answers[qid]

    block_scores: dict[int, int] = {}
    for block in PHASE2_BLOCKS:
        raw = block_raw[block["id"]]
        if block["direct"]:
            block_scores[block["id"]] = raw
        else:
            block_scores[block["id"]] = 10 - raw

    total = sum(role_answers.values())
    return block_scores, total


def _pair_diff_label(diff: int) -> str:
    if diff <= 1:
        return "совпадение"
    if diff <= 3:
        return "расхождение"
    return "конфликт"


async def get_phase2_role_summary(
    session: AsyncSession,
    *,
    pair_session_id: int,
    role: str,
) -> dict:
    answers = await get_phase2_answers_for_role(session, pair_session_id=pair_session_id, role=role)
    blocks, total = _calc_phase2_blocks(answers)
    return {
        "answers": answers,
        "blocks": blocks,
        "total": total,
        "done": len(answers) >= PHASE2_TOTAL_QUESTIONS,
    }


async def get_phase2_pair_summary(session: AsyncSession, *, pair_session_id: int) -> dict:
    teen = await get_phase2_role_summary(session, pair_session_id=pair_session_id, role=_ROLE_TEEN)
    parent = await get_phase2_role_summary(session, pair_session_id=pair_session_id, role=_ROLE_PARENT)

    block_rows: list[dict] = []
    for block in PHASE2_BLOCKS:
        block_id = block["id"]
        teen_score = int(teen["blocks"].get(block_id, 0))
        parent_score = int(parent["blocks"].get(block_id, 0))
        diff = abs(teen_score - parent_score)
        block_rows.append(
            {
                "block_id": block_id,
                "block_name": block["name"],
                "teen_score": teen_score,
                "parent_score": parent_score,
                "pair_diff": diff,
                "label": _pair_diff_label(diff),
            }
        )

    return {
        "teen": teen,
        "parent": parent,
        "blocks": block_rows,
        "completed": bool(teen["done"] and parent["done"]),
    }


# ── Phase 3 ─────────────────────────────────────────────────────────────────

async def save_phase3_selected_scenarios(
    session: AsyncSession,
    *,
    pair_session_id: int,
    actor_user_id: int,
    scenario_ids: list[int],
) -> None:
    unique_ids: list[int] = []
    for sid in scenario_ids:
        if sid in PHASE3_SCENARIOS_BY_ID and sid not in unique_ids:
            unique_ids.append(sid)
    if len(unique_ids) < PHASE3_MIN_CHOICES or len(unique_ids) > PHASE3_MAX_CHOICES:
        raise ValueError("invalid_scenario_count")

    await _clear_role_qid_range(
        session,
        pair_test_session_id=pair_session_id,
        role="shared",
        min_qid=_Q_PHASE3_SELECTED_BASE,
        max_qid=_Q_PHASE3_SELECTED_MAX,
    )

    for idx, sid in enumerate(unique_ids):
        await _insert_answer(
            session,
            pair_test_session_id=pair_session_id,
            user_id=actor_user_id,
            role="shared",
            question_id=_Q_PHASE3_SELECTED_BASE + idx,
            block_id=3,
            answer_value=sid,
        )
    await session.commit()


async def get_phase3_selected_scenarios(
    session: AsyncSession,
    *,
    pair_session_id: int,
) -> list[int]:
    answers = await get_pair_answers_for_session(session, pair_test_session_id=pair_session_id)
    latest = _latest_answers_by_qid(answers, role="shared")
    selected: list[int] = []
    for qid in range(_Q_PHASE3_SELECTED_BASE, _Q_PHASE3_SELECTED_MAX + 1):
        row = latest.get(qid)
        if row is None:
            continue
        sid = int(row.answer_value)
        if sid in PHASE3_SCENARIOS_BY_ID and sid not in selected:
            selected.append(sid)
    return selected


async def set_phase3_selection_ready(
    session: AsyncSession,
    *,
    pair_session_id: int,
    user_id: int,
    role: str,
    ready: bool,
) -> None:
    qid = _Q_PHASE3_SELECT_READY
    await _clear_role_qid_range(
        session,
        pair_test_session_id=pair_session_id,
        role=role,
        min_qid=qid,
        max_qid=qid,
    )
    await _insert_answer(
        session,
        pair_test_session_id=pair_session_id,
        user_id=user_id,
        role=role,
        question_id=qid,
        block_id=3,
        answer_value=1 if ready else 0,
    )
    await session.commit()


async def is_phase3_selection_ready(
    session: AsyncSession,
    *,
    pair_session_id: int,
    role: str,
) -> bool:
    answers = await get_pair_answers_for_session(session, pair_test_session_id=pair_session_id)
    latest = _latest_answers_by_qid(answers, role=role)
    row = latest.get(_Q_PHASE3_SELECT_READY)
    return bool(row is not None and int(row.answer_value) == 1)


async def save_phase3_answer(
    session: AsyncSession,
    *,
    pair_session_id: int,
    user_id: int,
    role: str,
    scenario_id: int,
    option_index: int,
) -> None:
    if scenario_id not in PHASE3_SCENARIOS_BY_ID:
        raise ValueError("invalid_scenario")
    options = PHASE3_SCENARIOS_BY_ID[scenario_id]["teenager_options" if role == _ROLE_TEEN else "parent_options"]
    if option_index < 1 or option_index > len(options):
        raise ValueError("invalid_option")
    qid = _Q_PHASE3_ANSWER_BASE + scenario_id
    await _clear_role_qid_range(
        session,
        pair_test_session_id=pair_session_id,
        role=role,
        min_qid=qid,
        max_qid=qid,
    )
    await _insert_answer(
        session,
        pair_test_session_id=pair_session_id,
        user_id=user_id,
        role=role,
        question_id=qid,
        block_id=3,
        answer_value=option_index,
    )
    await session.commit()


async def get_phase3_answers_for_role(
    session: AsyncSession,
    *,
    pair_session_id: int,
    role: str,
) -> dict[int, int]:
    selected = await get_phase3_selected_scenarios(session, pair_session_id=pair_session_id)
    answers = await get_pair_answers_for_session(session, pair_test_session_id=pair_session_id)
    latest = _latest_answers_by_qid(answers, role=role)
    result: dict[int, int] = {}
    for sid in selected:
        qid = _Q_PHASE3_ANSWER_BASE + sid
        row = latest.get(qid)
        if row is not None:
            result[sid] = int(row.answer_value)
    return result


async def get_phase3_scenario_result(
    session: AsyncSession,
    *,
    pair_session_id: int,
    scenario_id: int,
) -> dict:
    teen = await get_phase3_answers_for_role(session, pair_session_id=pair_session_id, role=_ROLE_TEEN)
    parent = await get_phase3_answers_for_role(session, pair_session_id=pair_session_id, role=_ROLE_PARENT)
    t = teen.get(scenario_id)
    p = parent.get(scenario_id)
    if t is None or p is None:
        return {"ready": False}
    matched = t == p
    scenario = PHASE3_SCENARIOS_BY_ID[scenario_id]
    return {
        "ready": True,
        "scenario_id": scenario_id,
        "title": scenario["title"],
        "matched": matched,
        "teen_option": t,
        "parent_option": p,
        "discussion_question": scenario["discussion_question"] if not matched else None,
    }


async def get_phase3_summary(session: AsyncSession, *, pair_session_id: int) -> dict:
    selected = await get_phase3_selected_scenarios(session, pair_session_id=pair_session_id)
    teen = await get_phase3_answers_for_role(session, pair_session_id=pair_session_id, role=_ROLE_TEEN)
    parent = await get_phase3_answers_for_role(session, pair_session_id=pair_session_id, role=_ROLE_PARENT)

    rows: list[dict] = []
    matches = 0
    mismatches = 0
    for sid in selected:
        t = teen.get(sid)
        p = parent.get(sid)
        if t is None or p is None:
            continue
        matched = t == p
        if matched:
            matches += 1
        else:
            mismatches += 1
        scenario = PHASE3_SCENARIOS_BY_ID[sid]
        rows.append(
            {
                "scenario_id": sid,
                "title": scenario["title"],
                "matched": matched,
                "discussion_question": scenario["discussion_question"] if not matched else None,
            }
        )

    return {
        "selected_scenarios": selected,
        "rows": rows,
        "matches": matches,
        "mismatches": mismatches,
        "teen_done": len(teen) >= len(selected) and len(selected) >= PHASE3_MIN_CHOICES,
        "parent_done": len(parent) >= len(selected) and len(selected) >= PHASE3_MIN_CHOICES,
        "completed": len(rows) == len(selected) and len(selected) >= PHASE3_MIN_CHOICES,
    }


# ── Phase 4 ─────────────────────────────────────────────────────────────────

async def save_phase4_values(
    session: AsyncSession,
    *,
    pair_session_id: int,
    user_id: int,
    role: str,
    value_ids: list[int],
) -> None:
    normalized: list[int] = []
    for value_id in value_ids:
        if 1 <= value_id <= len(PHASE4_VALUES) and value_id not in normalized:
            normalized.append(value_id)
    if len(normalized) != PHASE4_REQUIRED_COUNT:
        raise ValueError("invalid_values_count")

    await _clear_role_qid_range(
        session,
        pair_test_session_id=pair_session_id,
        role=role,
        min_qid=_Q_PHASE4_SELECTED_BASE,
        max_qid=_Q_PHASE4_DONE,
    )
    for idx, value_id in enumerate(normalized):
        await _insert_answer(
            session,
            pair_test_session_id=pair_session_id,
            user_id=user_id,
            role=role,
            question_id=_Q_PHASE4_SELECTED_BASE + idx,
            block_id=4,
            answer_value=value_id,
        )
    await _insert_answer(
        session,
        pair_test_session_id=pair_session_id,
        user_id=user_id,
        role=role,
        question_id=_Q_PHASE4_DONE,
        block_id=4,
        answer_value=1,
    )
    await session.commit()


async def get_phase4_values_for_role(
    session: AsyncSession,
    *,
    pair_session_id: int,
    role: str,
) -> list[int]:
    answers = await get_pair_answers_for_session(session, pair_test_session_id=pair_session_id)
    latest = _latest_answers_by_qid(answers, role=role)
    values: list[int] = []
    for qid in range(_Q_PHASE4_SELECTED_BASE, _Q_PHASE4_SELECTED_MAX + 1):
        row = latest.get(qid)
        if row is None:
            continue
        value_id = int(row.answer_value)
        if 1 <= value_id <= len(PHASE4_VALUES) and value_id not in values:
            values.append(value_id)
    return values


async def get_phase4_summary(session: AsyncSession, *, pair_session_id: int) -> dict:
    teen_values = await get_phase4_values_for_role(session, pair_session_id=pair_session_id, role=_ROLE_TEEN)
    parent_values = await get_phase4_values_for_role(session, pair_session_id=pair_session_id, role=_ROLE_PARENT)

    overlap_ids = sorted(set(teen_values).intersection(parent_values))
    overlap_labels = [PHASE4_VALUES[i - 1] for i in overlap_ids]
    overlap_count = len(overlap_ids)

    if overlap_count >= 4:
        interpretation = "4-5 общих ценностей: сильная ценностная опора для совместных решений."
    elif overlap_count >= 2:
        interpretation = "2-3 общих ценности: есть общая база, но часть ориентиров различается."
    else:
        interpretation = "0-1 общая ценность: важно отдельно обсудить ожидания и приоритеты."

    return {
        "teen_values": teen_values,
        "parent_values": parent_values,
        "overlap_ids": overlap_ids,
        "overlap_values": overlap_labels,
        "overlap_count": overlap_count,
        "interpretation": interpretation,
        "teen_done": len(teen_values) == PHASE4_REQUIRED_COUNT,
        "parent_done": len(parent_values) == PHASE4_REQUIRED_COUNT,
        "completed": len(teen_values) == PHASE4_REQUIRED_COUNT and len(parent_values) == PHASE4_REQUIRED_COUNT,
    }


# ── Aggregate progress ──────────────────────────────────────────────────────

async def get_dialogue_progress(
    session: AsyncSession,
    *,
    pair_session_id: int,
) -> dict:
    phase1 = await get_phase1_results(session, pair_session_id=pair_session_id)
    phase2 = await get_phase2_pair_summary(session, pair_session_id=pair_session_id)
    phase3 = await get_phase3_summary(session, pair_session_id=pair_session_id)
    phase4 = await get_phase4_summary(session, pair_session_id=pair_session_id)
    return {
        "phase1": phase1,
        "phase2": phase2,
        "phase3": phase3,
        "phase4": phase4,
        "completed": bool(phase1["completed"] and phase2["completed"] and phase3["completed"] and phase4["completed"]),
    }


# ── Stage-1 compatibility API ──────────────────────────────────────────────

async def create_pair_test_session(
    session: AsyncSession,
    *,
    parent_user_id: int,
    family_link_id: int | None = None,
) -> PairTestSession:
    return await create_pair_session(
        session,
        parent_user_id=parent_user_id,
        family_link_id=family_link_id,
    )


async def get_pair_test_by_code(
    session: AsyncSession,
    *,
    code: str,
) -> PairTestSession | None:
    return await get_pair_session_by_code(session, pair_code=code)


async def join_pair_test_by_code(
    session: AsyncSession,
    *,
    code: str,
    teen_user_id: int,
) -> PairTestSession:
    return await join_pair_session(session, pair_code=code, teen_user_id=teen_user_id)


async def get_active_pair_test_for_parent(
    session: AsyncSession,
    *,
    parent_user_id: int,
) -> PairTestSession | None:
    return await get_active_pair_session_for_user(
        session,
        user_id=parent_user_id,
        role=_ROLE_PARENT,
    )


async def get_active_pair_test_for_teen(
    session: AsyncSession,
    *,
    teen_user_id: int,
) -> PairTestSession | None:
    return await get_active_pair_session_for_user(
        session,
        user_id=teen_user_id,
        role=_ROLE_TEEN,
    )


async def cancel_pair_test(
    session: AsyncSession,
    *,
    session_id: int,
    parent_user_id: int,
) -> PairTestSession:
    return await cancel_pair_session(
        session,
        pair_session_id=session_id,
        parent_user_id=parent_user_id,
    )
