from __future__ import annotations

import builtins
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PairTestSession, User, UserBehavior, UserScore


SCORE_DROPOUT = "dropout"
SCORE_RISK = "risk"
SCORE_NORMAL = "normal"
SCORE_POWER = "power"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_int(value, default: builtins.int = 0) -> builtins.int:
    try:
        return builtins.int(value)
    except builtins.Exception:
        return default


def score_bucket(score: builtins.int) -> builtins.str:
    if score < 30:
        return SCORE_DROPOUT
    if score < 60:
        return SCORE_RISK
    if score < 80:
        return SCORE_NORMAL
    return SCORE_POWER


def get_score_delay_minutes(score: builtins.int) -> builtins.int:
    if score < 30:
        return 10
    if score < 60:
        return 30
    return 120


def score_personalized_text(score: builtins.int) -> builtins.str:
    if score < 30:
        return "Давай попробуем ещё раз 👇"
    if score < 60:
        return "Осталось немного 👇"
    if score > 80:
        return "Идёшь отлично, продолжим в быстром темпе 👇"
    return "Давай продолжим 👇"


def build_score_components(
    *,
    actions_count: builtins.int,
    completion_ratio: builtins.float,
    returned: builtins.bool,
    consistent: builtins.bool,
) -> builtins.dict[builtins.str, builtins.int]:
    # engagement capped at 30 to preserve weight for completion/return/consistency
    engagement_score = builtins.min(30, builtins.max(0, actions_count * 2))
    completion_score = builtins.int(builtins.max(0.0, builtins.min(completion_ratio, 1.0)) * 30)
    return_score = 20 if returned else 0
    consistency_score = 20 if consistent else 5
    score = builtins.min(100, engagement_score + completion_score + return_score + consistency_score)

    return {
        "score": score,
        "engagement_score": engagement_score,
        "completion_score": completion_score,
        "return_score": return_score,
        "consistency_score": consistency_score,
    }


async def _get_or_create_user_score(session: AsyncSession, *, user_id: builtins.int) -> UserScore:
    result = await session.execute(select(UserScore).where(UserScore.user_id == user_id))
    row = result.scalar_one_or_none()
    if row is not None:
        return row

    row = UserScore(user_id=user_id)
    session.add(row)
    return row


async def _estimate_completion_ratio(session: AsyncSession, *, user_id: builtins.int) -> builtins.float:
    user_result = await session.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user is None or user.role not in {"teen", "parent"}:
        return 0.0

    role_column = PairTestSession.parent_user_id if user.role == "parent" else PairTestSession.teen_user_id
    pair_result = await session.execute(
        select(PairTestSession)
        .where(role_column == user_id, PairTestSession.status.in_(["pending", "active", "parent_done", "teen_done"]))
        .order_by(PairTestSession.id.desc())
    )
    pair = pair_result.scalars().first()
    if pair is None:
        return 1.0

    from app.services.pair_test_service import get_dialogue_progress

    progress = await get_dialogue_progress(session, pair_session_id=pair.id)
    role = user.role

    if not progress["phase1"]["completed"]:
        partial = 0
        if progress["phase1"][role].get("score") is not None:
            partial += 1
        if progress["phase1"][role].get("word"):
            partial += 1
        return (partial / 2.0) * 0.25

    if not progress["phase2"]["completed"]:
        answered = builtins.len(progress["phase2"][role]["answers"])
        return 0.25 + (answered / 5.0) * 0.25

    if not progress["phase3"]["completed"]:
        selected = builtins.max(1, builtins.len(progress["phase3"].get("selected_scenarios", [])))
        from app.services.pair_test_service import get_phase3_answers_for_role

        my_answers = await get_phase3_answers_for_role(session, pair_session_id=pair.id, role=role)
        return 0.5 + (builtins.len(my_answers) / selected) * 0.25

    if not progress["phase4"]["completed"]:
        values = progress["phase4"][f"{role}_values"]
        return 0.75 + (builtins.len(values) / 5.0) * 0.25

    return 1.0


async def calculate_user_score(session: AsyncSession, *, user_id: builtins.int) -> builtins.dict[builtins.str, builtins.int]:
    behavior_result = await session.execute(select(UserBehavior).where(UserBehavior.user_id == user_id))
    behavior = behavior_result.scalar_one_or_none()

    if behavior is None:
        return {
            "score": 0,
            "engagement_score": 0,
            "completion_score": 0,
            "return_score": 0,
            "consistency_score": 5,
        }

    actions_count = behavior.visit_count + behavior.answer_count + behavior.return_count + behavior.completion_count
    completion_ratio = await _estimate_completion_ratio(session, user_id=user_id)
    returned = behavior.return_count > 0
    consistent = behavior.avg_response_time is not None and behavior.avg_response_time <= 120

    return build_score_components(
        actions_count=actions_count,
        completion_ratio=completion_ratio,
        returned=returned,
        consistent=consistent,
    )


async def update_user_score(session: AsyncSession, *, user_id: builtins.int) -> UserScore:
    payload = await calculate_user_score(session, user_id=user_id)
    row = await _get_or_create_user_score(session, user_id=user_id)

    row.score = _safe_int(payload.get("score"), 0)
    row.engagement_score = _safe_int(payload.get("engagement_score"), 0)
    row.completion_score = _safe_int(payload.get("completion_score"), 0)
    row.return_score = _safe_int(payload.get("return_score"), 0)
    row.consistency_score = _safe_int(payload.get("consistency_score"), 5)
    row.last_calculated_at = _now()
    return row


async def get_user_score_profile(session: AsyncSession, *, user_id: builtins.int) -> builtins.dict:
    result = await session.execute(select(UserScore).where(UserScore.user_id == user_id))
    row = result.scalar_one_or_none()
    if row is None:
        return {
            "score": 0,
            "bucket": SCORE_DROPOUT,
            "engagement_score": 0,
            "completion_score": 0,
            "return_score": 0,
            "consistency_score": 5,
        }

    return {
        "score": row.score,
        "bucket": score_bucket(row.score),
        "engagement_score": row.engagement_score,
        "completion_score": row.completion_score,
        "return_score": row.return_score,
        "consistency_score": row.consistency_score,
    }
