from __future__ import annotations

import builtins
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PairTestSession, User, UserActivity, UserBehavior
from app.db.session import AsyncSessionLocal
from app.services.openai_service import generate_retention_nudge
from app.services.segment_service import (
    get_or_create_user_behavior,
    get_segment_delay_minutes,
    get_segment_resume_text,
    get_user_segment,
    track_user_event,
)
from app.services.scheduler_service import cancel_job, schedule_reminder

_MAX_REMINDERS_PER_DAY = 2
_MAX_BEHAVIOR_NOTIFICATIONS_PER_DAY = 2
_MIN_NOTIFICATION_GAP_HOURS = 2
_RECENT_ACTIVITY_MINUTES = 10
_DEFAULT_RESPONSE_SECONDS = 15 * 60
_scheduler_bot = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _inactivity_job_id(*, pair_id: builtins.int, user_id: builtins.int) -> builtins.str:
    return f"reminder:{user_id}:inactivity"


def _same_day(a: datetime | None, b: datetime) -> builtins.bool:
    if a is None:
        return False
    return a.date() == b.date()


def _safe_int(value, default: builtins.int) -> builtins.int:
    try:
        return builtins.int(value)
    except builtins.Exception:
        return default


def _active_hours_map(behavior: UserBehavior | None) -> builtins.dict[builtins.int, builtins.int]:
    if behavior is None or not builtins.isinstance(behavior.active_hours_json, builtins.dict):
        return {}

    payload: builtins.dict[builtins.int, builtins.int] = {}
    for raw_hour, raw_count in behavior.active_hours_json.items():
        hour = _safe_int(raw_hour, -1)
        if 0 <= hour <= 23:
            payload[hour] = builtins.max(0, _safe_int(raw_count, 0))
    return payload


def update_active_hours(behavior: UserBehavior, timestamp: datetime) -> None:
    active_hours = _active_hours_map(behavior)
    active_hours[timestamp.hour] = active_hours.get(timestamp.hour, 0) + 1
    behavior.active_hours_json = {builtins.str(hour): count for hour, count in active_hours.items()}


def update_response_time(behavior: UserBehavior, delta_seconds: builtins.int) -> None:
    bounded_delta = builtins.max(30, builtins.min(delta_seconds, 12 * 60 * 60))
    if behavior.avg_response_time is None:
        behavior.avg_response_time = bounded_delta
        return
    behavior.avg_response_time = builtins.int(behavior.avg_response_time * 0.7 + bounded_delta * 0.3)


def _preferred_active_hours(behavior: UserBehavior | None) -> builtins.list[builtins.int]:
    active_hours = _active_hours_map(behavior)
    ranked = builtins.sorted(active_hours.items(), key=lambda item: (-item[1], item[0]))
    return [hour for hour, count in ranked[:4] if count > 0]


def next_active_hour(behavior: UserBehavior | None, *, now: datetime) -> datetime:
    active_hours = _preferred_active_hours(behavior)
    if not active_hours:
        response_seconds = _DEFAULT_RESPONSE_SECONDS
        if behavior is not None and behavior.avg_response_time is not None:
            response_seconds = behavior.avg_response_time
        return now + timedelta(seconds=builtins.max(10 * 60, builtins.min(response_seconds, 60 * 60)))

    current_hour = now.hour
    for offset in builtins.range(24):
        hour = (current_hour + offset) % 24
        if hour not in active_hours:
            continue
        candidate = now.replace(hour=hour, minute=5, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    return now + timedelta(minutes=30)


def get_best_send_time(
    behavior: UserBehavior | None,
    *,
    now: datetime | None = None,
    segment: builtins.str | None = None,
) -> datetime:
    current_time = now or _now()
    recent_cutoff = timedelta(minutes=_RECENT_ACTIVITY_MINUTES)
    response_seconds = _DEFAULT_RESPONSE_SECONDS
    if behavior is not None and behavior.avg_response_time is not None:
        response_seconds = behavior.avg_response_time

    adaptive_delay = builtins.max(2 * 60, builtins.min(builtins.int(response_seconds * 1.3), 30 * 60))
    if segment is not None:
        adaptive_delay = get_segment_delay_minutes(segment) * 60
    active_hours = _preferred_active_hours(behavior)

    if behavior is not None and behavior.last_seen_at is not None:
        if current_time - behavior.last_seen_at <= recent_cutoff:
            return current_time + timedelta(minutes=5)

    if current_time.hour in active_hours:
        return current_time + timedelta(seconds=adaptive_delay)

    return next_active_hour(behavior, now=current_time)


def _reset_behavior_notification_day(behavior: UserBehavior, now: datetime) -> None:
    if not _same_day(behavior.notification_day, now):
        behavior.notification_day = now
        behavior.notification_count_today = 0


def should_send_now(behavior: UserBehavior | None, *, now: datetime | None = None) -> builtins.bool:
    current_time = now or _now()
    if behavior is None:
        return True

    _reset_behavior_notification_day(behavior, current_time)

    if behavior.notification_count_today >= _MAX_BEHAVIOR_NOTIFICATIONS_PER_DAY:
        return False

    if behavior.last_notification_at is not None:
        if current_time - behavior.last_notification_at < timedelta(hours=_MIN_NOTIFICATION_GAP_HOURS):
            return False

    if behavior.last_seen_at is not None and current_time - behavior.last_seen_at <= timedelta(minutes=_RECENT_ACTIVITY_MINUTES):
        return True

    return current_time.hour in _preferred_active_hours(behavior)


def _mark_notification_sent(behavior: UserBehavior | None, *, now: datetime) -> None:
    if behavior is None:
        return
    _reset_behavior_notification_day(behavior, now)
    behavior.last_notification_at = now
    behavior.notification_count_today += 1


def _delivery_probability(*, reminder_kind: builtins.str, progress_percent: builtins.int) -> builtins.float:
    if reminder_kind == "waiting":
        return 0.9
    if progress_percent >= 70:
        return 0.85
    if reminder_kind == "daily":
        return 0.6
    if reminder_kind == "abandon":
        return 0.7
    return 0.75


def _should_deliver(*, reminder_kind: builtins.str, progress_percent: builtins.int) -> builtins.bool:
    return random.random() < _delivery_probability(reminder_kind=reminder_kind, progress_percent=progress_percent)

def set_scheduler_bot(bot) -> None:
    global _scheduler_bot
    _scheduler_bot = bot


def _user_role_for_pair(pair: PairTestSession, *, user_id: builtins.int) -> builtins.str | None:
    if pair.parent_user_id == user_id:
        return "parent"
    if pair.teen_user_id == user_id:
        return "teen"
    return None


async def _build_user_state_snapshot(
    session: AsyncSession,
    *,
    pair: PairTestSession,
    user_id: builtins.int,
) -> builtins.dict:
    from app.services.dialogue_test_data import PHASE2_TOTAL_QUESTIONS, PHASE4_REQUIRED_COUNT
    from app.services.pair_test_service import get_dialogue_progress, get_phase3_answers_for_role

    role = _user_role_for_pair(pair, user_id=user_id)
    other_role = "teen" if role == "parent" else "parent"
    if role is None:
        return {
            "phase": None,
            "progress_percent": 0,
            "mismatch_hint": False,
            "waiting_for_partner": False,
            "partner_waiting": False,
        }

    progress = await get_dialogue_progress(session, pair_session_id=pair.id)

    if not progress["phase1"]["completed"]:
        my_payload = progress["phase1"][role]
        other_payload = progress["phase1"][other_role]
        partial = 0
        if my_payload.get("score") is not None:
            partial += 1
        if my_payload.get("word"):
            partial += 1
        current_phase_percent = builtins.int(partial / 2 * 100)
        return {
            "phase": 1,
            "progress_percent": builtins.int(current_phase_percent * 0.25),
            "mismatch_hint": progress["phase1"].get("diff") not in (None, 0, 1),
            "waiting_for_partner": builtins.bool(my_payload.get("done") and not other_payload.get("done")),
            "partner_waiting": builtins.bool(other_payload.get("done") and not my_payload.get("done")),
        }

    if not progress["phase2"]["completed"]:
        my_answers = progress["phase2"][role]["answers"]
        other_done = builtins.bool(progress["phase2"][other_role]["done"])
        current_phase_percent = builtins.int(builtins.len(my_answers) / PHASE2_TOTAL_QUESTIONS * 100)
        mismatch_hint = builtins.any(row.get("label") != "совпадение" for row in progress["phase2"]["blocks"])
        return {
            "phase": 2,
            "progress_percent": 25 + builtins.int(current_phase_percent * 0.25),
            "mismatch_hint": mismatch_hint,
            "waiting_for_partner": builtins.bool(progress["phase2"][role]["done"] and not other_done),
            "partner_waiting": builtins.bool(other_done and not progress["phase2"][role]["done"]),
        }

    if not progress["phase3"]["completed"]:
        selected_count = builtins.max(1, builtins.len(progress["phase3"].get("selected_scenarios", [])))
        my_answers = await get_phase3_answers_for_role(session, pair_session_id=pair.id, role=role)
        my_answer_count = builtins.len(my_answers)
        current_phase_percent = builtins.int(my_answer_count / selected_count * 100)
        return {
            "phase": 3,
            "progress_percent": 50 + builtins.int(current_phase_percent * 0.25),
            "mismatch_hint": builtins.int(progress["phase3"].get("mismatches", 0)) > 0,
            "waiting_for_partner": builtins.bool(progress["phase3"][f"{role}_done"] and not progress["phase3"][f"{other_role}_done"]),
            "partner_waiting": builtins.bool(progress["phase3"][f"{other_role}_done"] and not progress["phase3"][f"{role}_done"]),
        }

    if not progress["phase4"]["completed"]:
        my_values = progress["phase4"][f"{role}_values"]
        other_done = builtins.bool(progress["phase4"][f"{other_role}_done"])
        current_phase_percent = builtins.int(builtins.len(my_values) / PHASE4_REQUIRED_COUNT * 100)
        return {
            "phase": 4,
            "progress_percent": 75 + builtins.int(current_phase_percent * 0.25),
            "mismatch_hint": builtins.int(progress["phase4"].get("overlap_count", 0)) <= 1,
            "waiting_for_partner": builtins.bool(progress["phase4"][f"{role}_done"] and not other_done),
            "partner_waiting": builtins.bool(other_done and not progress["phase4"][f"{role}_done"]),
        }

    return {
        "phase": 4,
        "progress_percent": 100,
        "mismatch_hint": False,
        "waiting_for_partner": False,
        "partner_waiting": False,
    }


async def _build_smart_reminder_text(
    *,
    segment: builtins.str,
    reminder_kind: builtins.str,
    phase: builtins.int | None,
    progress_percent: builtins.int,
    mismatch_hint: builtins.bool,
) -> builtins.str:
    ai_text = await generate_retention_nudge(
        segment=segment,
        reminder_kind=reminder_kind,
        phase=phase,
        progress_percent=progress_percent,
        mismatch_hint=mismatch_hint,
    )
    if ai_text:
        return ai_text

    segment_text = get_segment_resume_text(segment)

    if reminder_kind == "waiting":
        return segment_text
    if progress_percent >= 70:
        return "Осталось немного 👇\nСейчас уже близко к результату."
    if mismatch_hint and phase in (2, 3):
        return "Вы немного по-разному видите ситуацию 👀\nИнтересно, что будет дальше."
    if phase == 2:
        return "Давай продолжим 👇"
    if phase == 3:
        return "Самое интересное впереди 👀"
    if phase == 4:
        return "Сейчас будет важный момент"
    if reminder_kind == "abandon":
        return "Ты не дошёл до результата 😔\nХочешь увидеть, что получится?"
    if reminder_kind == "daily":
        return "👇 продолжим с того же места"
    return segment_text


async def send_inactivity_reminder(user_id: builtins.int, pair_id: builtins.int) -> None:
    # Scheduler job runs independently from handlers, so use shared bot + DB lookup.
    if _scheduler_bot is None:
        return

    async with AsyncSessionLocal() as session:
        pair = await session.get(PairTestSession, pair_id)
        if pair is None or pair.status in ("completed", "cancelled", "expired"):
            cancel_job(_inactivity_job_id(pair_id=pair_id, user_id=user_id))
            return

        activity_result = await session.execute(
            select(UserActivity).where(
                UserActivity.user_id == user_id,
                UserActivity.pair_id == pair_id,
            )
        )
        activity = activity_result.scalar_one_or_none()
        if activity is None or activity.is_finished:
            cancel_job(_inactivity_job_id(pair_id=pair_id, user_id=user_id))
            return

        behavior = await get_or_create_user_behavior(session, user_id=user_id, now=_now())
        segment = await get_user_segment(session, user_id=user_id)
        snapshot = await _build_user_state_snapshot(session, pair=pair, user_id=user_id)

        if not should_send_now(behavior, now=_now()):
            run_at = get_best_send_time(behavior, now=_now(), segment=segment)
            schedule_reminder(
                _inactivity_job_id(pair_id=pair_id, user_id=user_id),
                run_at,
                "app.jobs.reminders:send_inactivity_reminder_safe",
                user_id,
                pair_id,
            )
            return

        if not _should_deliver(
            reminder_kind="inactivity",
            progress_percent=builtins.int(snapshot.get("progress_percent", 0)),
        ):
            cancel_job(_inactivity_job_id(pair_id=pair_id, user_id=user_id))
            return

        telegram_id = await _get_telegram_id(session, user_id=user_id)
        if telegram_id is None:
            return

        from app.keyboards.pair_test import resume_flow_keyboard

        message_text = await _build_smart_reminder_text(
            segment=segment,
            reminder_kind="inactivity",
            phase=snapshot.get("phase"),
            progress_percent=builtins.int(snapshot.get("progress_percent", 0)),
            mismatch_hint=builtins.bool(snapshot.get("mismatch_hint", False)),
        )

        await _scheduler_bot.send_message(
            telegram_id,
            message_text,
            reply_markup=resume_flow_keyboard(),
        )

        activity.reminder_stage = builtins.max(activity.reminder_stage, 4)
        current_time = _now()
        _inc_daily_counter(activity, current_time)
        _mark_notification_sent(behavior, now=current_time)
        await session.commit()

        cancel_job(_inactivity_job_id(pair_id=pair_id, user_id=user_id))


def schedule_inactivity_reminder(
    *,
    pair_id: builtins.int,
    user_id: builtins.int,
    behavior: UserBehavior | None,
    segment: builtins.str,
) -> None:
    run_at = get_best_send_time(behavior, now=_now(), segment=segment)
    schedule_reminder(
        _inactivity_job_id(pair_id=pair_id, user_id=user_id),
        run_at,
        "app.jobs.reminders:send_inactivity_reminder_safe",
        user_id,
        pair_id,
    )


async def touch_user_activity(
    session: AsyncSession,
    *,
    user_id: builtins.int,
    pair_id: builtins.int,
    question_id: builtins.int | None,
) -> None:
    now = _now()
    segment = await track_user_event(
        session,
        user_id=user_id,
        event="answer",
        timestamp=now,
    )
    behavior = await get_or_create_user_behavior(session, user_id=user_id, now=now)
    result = await session.execute(
        select(UserActivity).where(
            UserActivity.user_id == user_id,
            UserActivity.pair_id == pair_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = UserActivity(
            user_id=user_id,
            pair_id=pair_id,
            last_action_at=now,
            last_question_at=question_id,
            reminder_stage=0,
            is_finished=False,
            reminders_sent_today=0,
            reminder_day=now,
        )
        session.add(row)
    else:
        row.last_action_at = now
        row.last_question_at = question_id
        row.is_finished = False

    cancel_job(_inactivity_job_id(pair_id=pair_id, user_id=user_id))
    schedule_inactivity_reminder(pair_id=pair_id, user_id=user_id, behavior=behavior, segment=segment)


async def mark_pair_finished(session: AsyncSession, *, pair_id: builtins.int) -> None:
    result = await session.execute(
        select(UserActivity).where(UserActivity.pair_id == pair_id)
    )
    rows = builtins.list(result.scalars().all())
    for row in rows:
        row.is_finished = True
        cancel_job(_inactivity_job_id(pair_id=pair_id, user_id=row.user_id))
        await track_user_event(session, user_id=row.user_id, event="completed", timestamp=_now())


async def _get_telegram_id(session: AsyncSession, *, user_id: builtins.int | None) -> builtins.int | None:
    if user_id is None:
        return None
    result = await session.execute(select(User.telegram_id).where(User.id == user_id))
    return result.scalar_one_or_none()


async def _get_pair_users(
    session: AsyncSession,
    *,
    pair_id: builtins.int,
) -> builtins.tuple[PairTestSession | None, builtins.int | None, builtins.int | None]:
    pair = await session.get(PairTestSession, pair_id)
    if pair is None:
        return None, None, None
    teen_tg = await _get_telegram_id(session, user_id=pair.teen_user_id)
    parent_tg = await _get_telegram_id(session, user_id=pair.parent_user_id)
    return pair, teen_tg, parent_tg


def _can_send_today(activity: UserActivity, now: datetime) -> builtins.bool:
    if not _same_day(activity.reminder_day, now):
        activity.reminder_day = now
        activity.reminders_sent_today = 0
    return activity.reminders_sent_today < _MAX_REMINDERS_PER_DAY


def _inc_daily_counter(activity: UserActivity, now: datetime) -> None:
    if not _same_day(activity.reminder_day, now):
        activity.reminder_day = now
        activity.reminders_sent_today = 0
    activity.reminders_sent_today += 1


async def ping_partner(bot, session: AsyncSession, *, pair_id: builtins.int, from_user_id: builtins.int) -> builtins.bool:
    pair = await session.get(PairTestSession, pair_id)
    if pair is None:
        return False

    target_user_id: builtins.int | None = None
    if pair.parent_user_id == from_user_id:
        target_user_id = pair.teen_user_id
    elif pair.teen_user_id == from_user_id:
        target_user_id = pair.parent_user_id
    if target_user_id is None:
        return False

    target_tg = await _get_telegram_id(session, user_id=target_user_id)
    if target_tg is None:
        return False

    await bot.send_message(
        target_tg,
        "👀 Тебя ждут в тесте\n\nДавай продолжим 👇",
    )
    return True


async def _get_user_behavior_for_send(
    session: AsyncSession,
    *,
    user_id: builtins.int,
    now: datetime,
) -> UserBehavior:
    return await get_or_create_user_behavior(session, user_id=user_id, now=now)


async def _send_smart_reminder(
    bot,
    session: AsyncSession,
    *,
    activity: UserActivity,
    pair: PairTestSession,
    telegram_id: builtins.int,
    reminder_kind: builtins.str,
    reminder_stage: builtins.int,
) -> None:
    from app.keyboards.pair_test import resume_flow_keyboard

    now = _now()
    behavior = await _get_user_behavior_for_send(session, user_id=activity.user_id, now=now)
    segment = await get_user_segment(session, user_id=activity.user_id)
    if not should_send_now(behavior, now=now):
        return

    snapshot = await _build_user_state_snapshot(session, pair=pair, user_id=activity.user_id)
    progress_percent = builtins.int(snapshot.get("progress_percent", 0))
    if not _should_deliver(reminder_kind=reminder_kind, progress_percent=progress_percent):
        return

    message_text = await _build_smart_reminder_text(
        segment=segment,
        reminder_kind=reminder_kind,
        phase=snapshot.get("phase"),
        progress_percent=progress_percent,
        mismatch_hint=builtins.bool(snapshot.get("mismatch_hint", False)),
    )
    await bot.send_message(
        telegram_id,
        message_text,
        reply_markup=resume_flow_keyboard(),
    )

    activity.reminder_stage = reminder_stage
    _inc_daily_counter(activity, now)
    _mark_notification_sent(behavior, now=now)


async def process_retention_reminders(bot, session: AsyncSession) -> None:
    now = _now()
    result = await session.execute(
        select(UserActivity)
        .where(UserActivity.is_finished.is_(False))
        .order_by(UserActivity.last_action_at.asc())
    )
    activities = builtins.list(result.scalars().all())

    for activity in activities:
        if not _can_send_today(activity, now):
            continue

        elapsed = now - activity.last_action_at

        pair, teen_tg, parent_tg = await _get_pair_users(session, pair_id=activity.pair_id)
        if pair is None:
            activity.is_finished = True
            continue
        if pair.status in ("completed", "cancelled", "expired"):
            activity.is_finished = True
            continue

        role = _user_role_for_pair(pair, user_id=activity.user_id)
        if role is None:
            activity.is_finished = True
            continue

        target = teen_tg if pair.teen_user_id == activity.user_id else parent_tg
        if target is None:
            continue

        snapshot = await _build_user_state_snapshot(session, pair=pair, user_id=activity.user_id)
        partner_waiting = builtins.bool(snapshot.get("partner_waiting", False))

        # Waiting reminders: nudge the silent user when the other side is already waiting.
        if partner_waiting and elapsed >= timedelta(hours=6) and activity.reminder_stage < 3:
            await _send_smart_reminder(
                bot,
                session,
                activity=activity,
                pair=pair,
                telegram_id=target,
                reminder_kind="waiting",
                reminder_stage=3,
            )
            continue

        if partner_waiting and elapsed >= timedelta(hours=1) and activity.reminder_stage < 2:
            await _send_smart_reminder(
                bot,
                session,
                activity=activity,
                pair=pair,
                telegram_id=target,
                reminder_kind="waiting",
                reminder_stage=2,
            )
            continue

        if partner_waiting and elapsed >= timedelta(minutes=10) and activity.reminder_stage < 1:
            await _send_smart_reminder(
                bot,
                session,
                activity=activity,
                pair=pair,
                telegram_id=target,
                reminder_kind="waiting",
                reminder_stage=1,
            )
            continue

        # Abandon recovery: T+3h and T+24h
        if elapsed >= timedelta(hours=24) and activity.reminder_stage < 6:
            await _send_smart_reminder(
                bot,
                session,
                activity=activity,
                pair=pair,
                telegram_id=target,
                reminder_kind="abandon",
                reminder_stage=6,
            )
            continue

        if elapsed >= timedelta(hours=3) and activity.reminder_stage < 5:
            await _send_smart_reminder(
                bot,
                session,
                activity=activity,
                pair=pair,
                telegram_id=target,
                reminder_kind="abandon",
                reminder_stage=5,
            )
            continue

        # Daily nudge at 48h+
        if elapsed >= timedelta(hours=48) and activity.reminder_stage < 7:
            await _send_smart_reminder(
                bot,
                session,
                activity=activity,
                pair=pair,
                telegram_id=target,
                reminder_kind="daily",
                reminder_stage=7,
            )

    await session.commit()
