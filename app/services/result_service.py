from __future__ import annotations

import builtins

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserResult

_PROGRESS_LABELS: builtins.dict[builtins.str, builtins.str] = {
    "independence": "самостоятельность",
    "anxiety": "тревога и барьеры",
    "control": "локус контроля",
    "perfectionism": "перфекционизм",
    "pressure": "социальное давление",
    "identity": "идентичность",
}


async def save_result(
    session: AsyncSession,
    user_id: builtins.int,
    pair_session_id: builtins.int | None,
    teen_scores: builtins.dict,
    parent_scores: builtins.dict,
    diff: builtins.dict,
    ai_report: builtins.str,
) -> UserResult:
    result = UserResult(
        user_id=user_id,
        pair_session_id=pair_session_id,
        teen_scores=teen_scores,
        parent_scores=parent_scores,
        diff=diff,
        ai_report=ai_report,
    )

    session.add(result)
    await session.commit()
    await session.refresh(result)
    return result


async def get_last_result(session: AsyncSession, user_id: builtins.int) -> UserResult | None:
    result = await session.execute(
        select(UserResult)
        .where(UserResult.user_id == user_id)
        .order_by(UserResult.created_at.desc())
        .limit(1)
    )
    return result.scalars().first()


async def get_previous_result(session: AsyncSession, user_id: builtins.int) -> UserResult | None:
    result = await session.execute(
        select(UserResult)
        .where(UserResult.user_id == user_id)
        .order_by(UserResult.created_at.desc())
        .offset(1)
        .limit(1)
    )
    return result.scalars().first()


def _extract_metric_value(value: builtins.object) -> builtins.int:
    if isinstance(value, dict):
        raw = value.get("diff", 0)
        return int(raw) if isinstance(raw, (int, float)) else 0
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def compare_results(
    current: builtins.dict | None,
    previous: builtins.dict | None,
) -> builtins.dict[builtins.str, builtins.int] | None:
    """Compare current diff metrics with previous diff metrics and return per-key delta."""
    if not previous:
        return None
    if not current:
        return None

    delta: builtins.dict[builtins.str, builtins.int] = {}
    for key in current:
        curr_val = _extract_metric_value(current.get(key, 0))
        prev_val = _extract_metric_value(previous.get(key, 0))
        delta[str(key)] = curr_val - prev_val

    return delta


def build_progress_text(delta: builtins.dict[builtins.str, builtins.int] | None) -> builtins.str:
    if not delta:
        return "📈 Это твой первый результат. Динамика появится после повторного прохождения."

    text = "📈 Твоя динамика:\n\n"
    for key, value in delta.items():
        label = _PROGRESS_LABELS.get(key, key)
        if value > 0:
            text += f"🔼 {label}: +{value}\n"
        elif value < 0:
            text += f"🔽 {label}: {value}\n"
        else:
            text += f"➖ {label}: без изменений\n"

    return text.strip()


def build_result_text(result: UserResult) -> builtins.str:
    text = "📊 Твой последний результат:\n\n"

    if result.ai_report:
        text += result.ai_report
    else:
        text += "Результат пока без интерпретации"

    return text
