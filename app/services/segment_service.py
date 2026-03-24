from __future__ import annotations

import builtins
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PairTestSession, User, UserActivity, UserBehavior, UserSegment

logger = logging.getLogger(__name__)

SEGMENT_FAST = "fast"
SEGMENT_THINKER = "thinker"
SEGMENT_DROPOUT = "dropout"
SEGMENT_GHOST = "ghost"
SEGMENT_RETURNER = "returner"
SEGMENT_STUCK = "stuck"

ALL_SEGMENTS = {
    SEGMENT_FAST,
    SEGMENT_THINKER,
    SEGMENT_DROPOUT,
    SEGMENT_GHOST,
    SEGMENT_RETURNER,
    SEGMENT_STUCK,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def detect_segment_profile(
    *,
    visit_count: builtins.int,
    answer_count: builtins.int,
    completion_count: builtins.int,
    return_count: builtins.int,
    avg_response_time: builtins.int | None,
    last_seen_at: datetime | None,
    waiting_for_partner: builtins.bool,
    now: datetime,
) -> builtins.str:
    if completion_count > 0:
        if avg_response_time is not None and avg_response_time < 30:
            return SEGMENT_FAST
        return SEGMENT_THINKER

    if return_count > 0 and answer_count > 0:
        return SEGMENT_RETURNER

    if answer_count > 0:
        if waiting_for_partner:
            return SEGMENT_STUCK
        if last_seen_at is not None and now - last_seen_at > timedelta(hours=2):
            return SEGMENT_DROPOUT
        return SEGMENT_THINKER

    if visit_count > 0:
        return SEGMENT_GHOST

    return SEGMENT_GHOST


async def get_or_create_user_behavior(
    session: AsyncSession,
    *,
    user_id: builtins.int,
    now: datetime | None = None,
) -> UserBehavior:
    timestamp = now or _now()
    result = await session.execute(select(UserBehavior).where(UserBehavior.user_id == user_id))
    behavior = result.scalar_one_or_none()
    if behavior is not None:
        return behavior

    behavior = UserBehavior(
        user_id=user_id,
        last_seen_at=timestamp,
        last_answer_at=None,
        avg_response_time=None,
        active_hours_json={builtins.str(timestamp.hour): 1},
        last_notification_at=None,
        notification_count_today=0,
        notification_day=timestamp,
        visit_count=0,
        answer_count=0,
        return_count=0,
        completion_count=0,
    )
    session.add(behavior)
    return behavior


async def get_or_create_user_segment(
    session: AsyncSession,
    *,
    user_id: builtins.int,
) -> UserSegment:
    result = await session.execute(select(UserSegment).where(UserSegment.user_id == user_id))
    segment_row = result.scalar_one_or_none()
    if segment_row is not None:
        return segment_row

    segment_row = UserSegment(user_id=user_id, segment=SEGMENT_GHOST)
    session.add(segment_row)
    return segment_row


async def _user_waiting_for_partner(session: AsyncSession, *, user_id: builtins.int) -> builtins.bool:
    user_result = await session.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user is None or user.role not in {"teen", "parent"}:
        return False

    role_column = PairTestSession.parent_user_id if user.role == "parent" else PairTestSession.teen_user_id
    pair_result = await session.execute(
        select(PairTestSession)
        .where(
            role_column == user_id,
            PairTestSession.status.in_(["active", "parent_done", "teen_done"]),
        )
        .order_by(PairTestSession.id.desc())
    )
    pair = pair_result.scalars().first()
    if pair is None:
        return False

    activity_result = await session.execute(
        select(UserActivity).where(
            UserActivity.user_id == user_id,
            UserActivity.pair_id == pair.id,
        )
    )
    activity = activity_result.scalar_one_or_none()
    if activity is None:
        return False

    if user.role == "parent":
        other_user_id = pair.teen_user_id
    else:
        other_user_id = pair.parent_user_id

    if other_user_id is None:
        return False

    other_activity_result = await session.execute(
        select(UserActivity).where(
            UserActivity.user_id == other_user_id,
            UserActivity.pair_id == pair.id,
        )
    )
    other_activity = other_activity_result.scalar_one_or_none()
    if other_activity is None:
        return False

    return activity.last_action_at <= other_activity.last_action_at


async def update_segment(
    session: AsyncSession,
    *,
    user_id: builtins.int,
    now: datetime | None = None,
) -> builtins.str:
    timestamp = now or _now()
    behavior = await get_or_create_user_behavior(session, user_id=user_id, now=timestamp)
    waiting_for_partner = await _user_waiting_for_partner(session, user_id=user_id)
    segment = detect_segment_profile(
        visit_count=behavior.visit_count,
        answer_count=behavior.answer_count,
        completion_count=behavior.completion_count,
        return_count=behavior.return_count,
        avg_response_time=behavior.avg_response_time,
        last_seen_at=behavior.last_seen_at,
        waiting_for_partner=waiting_for_partner,
        now=timestamp,
    )
    segment_row = await get_or_create_user_segment(session, user_id=user_id)
    segment_row.segment = segment
    segment_row.updated_at = timestamp
    logger.info("SEGMENT: %s -> %s", user_id, segment)
    return segment


async def get_user_segment(
    session: AsyncSession,
    *,
    user_id: builtins.int,
) -> builtins.str:
    result = await session.execute(select(UserSegment.segment).where(UserSegment.user_id == user_id))
    segment = result.scalar_one_or_none()
    if segment in ALL_SEGMENTS:
        return segment
    return SEGMENT_GHOST


async def track_user_event(
    session: AsyncSession,
    *,
    user_id: builtins.int,
    event: builtins.str,
    timestamp: datetime | None = None,
) -> builtins.str:
    now = timestamp or _now()
    behavior = await get_or_create_user_behavior(session, user_id=user_id, now=now)
    behavior.last_seen_at = now

    if event == "visit":
        behavior.visit_count += 1
    elif event == "answer":
        behavior.answer_count += 1
        if behavior.last_answer_at is not None:
            delta = now - behavior.last_answer_at
            if delta >= timedelta(seconds=30):
                bounded_delta = builtins.max(30, builtins.min(builtins.int(delta.total_seconds()), 12 * 60 * 60))
                if behavior.avg_response_time is None:
                    behavior.avg_response_time = bounded_delta
                else:
                    behavior.avg_response_time = builtins.int(behavior.avg_response_time * 0.7 + bounded_delta * 0.3)
        behavior.last_answer_at = now
    elif event == "return":
        behavior.return_count += 1
    elif event == "completed":
        behavior.completion_count += 1

    active_hours = behavior.active_hours_json or {}
    hour_key = builtins.str(now.hour)
    active_hours[hour_key] = builtins.int(active_hours.get(hour_key, 0)) + 1
    behavior.active_hours_json = active_hours

    return await update_segment(session, user_id=user_id, now=now)


def get_segment_delay_minutes(segment: builtins.str) -> builtins.int:
    if segment == SEGMENT_FAST:
        return 5
    if segment == SEGMENT_THINKER:
        return 30
    if segment == SEGMENT_DROPOUT:
        return 60
    if segment == SEGMENT_GHOST:
        return 10
    if segment == SEGMENT_RETURNER:
        return 3
    if segment == SEGMENT_STUCK:
        return 10
    return 15


def get_segment_resume_text(segment: builtins.str) -> builtins.str:
    if segment == SEGMENT_FAST:
        return "Продолжим сразу 👇"
    if segment == SEGMENT_THINKER:
        return "Можно спокойно вернуться и продолжить в своём темпе."
    if segment == SEGMENT_DROPOUT:
        return "Ты не дошёл до результата 👇"
    if segment == SEGMENT_GHOST:
        return "Начнём? Это займёт 2 минуты."
    if segment == SEGMENT_RETURNER:
        return "Круто, что вернулся 👇"
    if segment == SEGMENT_STUCK:
        return "Партнёр ещё не ответил. Можно дождаться или напомнить ему."
    return "Давай продолжим 👇"