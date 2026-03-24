from __future__ import annotations

import builtins
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PairTestAnswer, PairTestSession, User
from app.keyboards.pair_test import resume_pair_test_keyboard
from app.services.pair_test_service import get_dialogue_progress

_REMINDER_AFTER_MINUTES = 10
_TIMEOUT_AFTER_MINUTES = 30

_ACTIVE_PAIR_STATUSES = {"active", "parent_done", "teen_done"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _get_pair_telegram_ids(
    session: AsyncSession,
    *,
    pair_session: PairTestSession,
) -> builtins.tuple[builtins.int | None, builtins.int | None]:
    teen_tg: builtins.int | None = None
    parent_tg: builtins.int | None = None

    if pair_session.teen_user_id is not None:
        teen_row = await session.execute(
            select(User.telegram_id).where(User.id == pair_session.teen_user_id)
        )
        teen_tg = teen_row.scalar_one_or_none()

    if pair_session.parent_user_id is not None:
        parent_row = await session.execute(
            select(User.telegram_id).where(User.id == pair_session.parent_user_id)
        )
        parent_tg = parent_row.scalar_one_or_none()

    return teen_tg, parent_tg


async def _get_latest_answers_by_phase_role(
    session: AsyncSession,
) -> builtins.list[PairTestAnswer]:
    latest_subquery = (
        select(
            PairTestAnswer.pair_test_session_id.label("pair_test_session_id"),
            PairTestAnswer.block_id.label("block_id"),
            PairTestAnswer.role.label("role"),
            func.max(PairTestAnswer.updated_at).label("max_updated_at"),
        )
        .where(
            PairTestAnswer.block_id.in_((1, 2, 3, 4)),
            PairTestAnswer.role.in_(("teen", "parent")),
        )
        .group_by(
            PairTestAnswer.pair_test_session_id,
            PairTestAnswer.block_id,
            PairTestAnswer.role,
        )
        .subquery()
    )

    result = await session.execute(
        select(PairTestAnswer)
        .join(
            latest_subquery,
            and_(
                PairTestAnswer.pair_test_session_id == latest_subquery.c.pair_test_session_id,
                PairTestAnswer.block_id == latest_subquery.c.block_id,
                PairTestAnswer.role == latest_subquery.c.role,
                PairTestAnswer.updated_at == latest_subquery.c.max_updated_at,
            ),
        )
    )
    return builtins.list(result.scalars().all())


def _phase_waiting_role(progress: builtins.dict, phase: builtins.int) -> builtins.str | None:
    if phase == 1:
        teen_done = builtins.bool(progress["phase1"]["teen"].get("done"))
        parent_done = builtins.bool(progress["phase1"]["parent"].get("done"))
    elif phase == 2:
        teen_done = builtins.bool(progress["phase2"]["teen"].get("done"))
        parent_done = builtins.bool(progress["phase2"]["parent"].get("done"))
    elif phase == 3:
        teen_done = builtins.bool(progress["phase3"].get("teen_done"))
        parent_done = builtins.bool(progress["phase3"].get("parent_done"))
    elif phase == 4:
        teen_done = builtins.bool(progress["phase4"].get("teen_done"))
        parent_done = builtins.bool(progress["phase4"].get("parent_done"))
    else:
        return None

    if teen_done and not parent_done:
        return "parent"
    if parent_done and not teen_done:
        return "teen"
    return None


async def get_stuck_answers(
    session: AsyncSession,
    *,
    minutes: builtins.int = _REMINDER_AFTER_MINUTES,
) -> builtins.list[PairTestAnswer]:
    cutoff = _now() - timedelta(minutes=minutes)
    latest_rows = await _get_latest_answers_by_phase_role(session)

    stuck: builtins.list[PairTestAnswer] = []
    for answer in latest_rows:
        if answer.updated_at >= cutoff:
            continue

        pair_session = await session.get(PairTestSession, answer.pair_test_session_id)
        if pair_session is None or pair_session.status not in _ACTIVE_PAIR_STATUSES:
            continue

        progress = await get_dialogue_progress(session, pair_session_id=pair_session.id)
        waiting_role = _phase_waiting_role(progress, answer.block_id)
        if waiting_role is None:
            continue
        if waiting_role == answer.role:
            # Responder is still completing own side; this is not "waiting for second" state.
            continue

        stuck.append(answer)

    return stuck


async def send_waiting_reminder(bot, session: AsyncSession) -> None:
    answers = await get_stuck_answers(session, minutes=_REMINDER_AFTER_MINUTES)

    for answer in answers:
        if answer.reminder_sent:
            continue

        pair_session = await session.get(PairTestSession, answer.pair_test_session_id)
        if pair_session is None:
            continue

        teen_tg, parent_tg = await _get_pair_telegram_ids(session, pair_session=pair_session)
        target = parent_tg if answer.role == "teen" else teen_tg
        if target is None:
            continue

        await bot.send_message(
            target,
            "⏳ Вас ждёт второй участник. Ответьте, чтобы продолжить.",
        )
        answer.status = "partial"
        answer.reminder_sent = True

    await session.commit()


async def handle_timeout(bot, session: AsyncSession) -> None:
    answers = await get_stuck_answers(session, minutes=_TIMEOUT_AFTER_MINUTES)

    for answer in answers:
        if answer.timeout_triggered:
            continue

        pair_session = await session.get(PairTestSession, answer.pair_test_session_id)
        if pair_session is None:
            continue

        teen_tg, parent_tg = await _get_pair_telegram_ids(session, pair_session=pair_session)
        for target in (teen_tg, parent_tg):
            if target is None:
                continue
            await bot.send_message(
                target,
                "⚠️ Второй участник не ответил.\nВы можете продолжить позже.",
                reply_markup=resume_pair_test_keyboard(),
            )

        answer.status = "timeout"
        answer.timeout_triggered = True

    await session.commit()
