from __future__ import annotations

import builtins
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.models import UserActivity
from app.db.session import AsyncSessionLocal
from app.services.lock_service import acquire_lock, release_lock
from app.services.retention_service import send_inactivity_reminder
from app.services.scheduler_service import schedule_reminder

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _job_id(user_id: builtins.int, phase: builtins.str) -> builtins.str:
    return f"reminder:{user_id}:{phase}"


async def send_inactivity_reminder_job(user_id: builtins.int, pair_id: builtins.int) -> None:
    async with AsyncSessionLocal() as session:
        row_result = await session.execute(
            select(UserActivity).where(
                UserActivity.user_id == user_id,
                UserActivity.pair_id == pair_id,
            )
        )
        activity = row_result.scalar_one_or_none()
        if activity is None or activity.is_finished:
            return

    try:
        await send_inactivity_reminder(user_id, pair_id)
    except builtins.Exception as exc:
        logger.error("REMINDER FAILED: %s", exc, exc_info=True)
        schedule_reminder(
            _job_id(user_id, "inactivity"),
            _now() + timedelta(minutes=5),
            "app.jobs.reminders:send_inactivity_reminder_safe",
            user_id,
            pair_id,
        )


async def send_inactivity_reminder_safe(user_id: builtins.int, pair_id: builtins.int) -> None:
    lock_key = f"lock:reminder:{user_id}:inactivity"
    try:
        lock_value = await acquire_lock(lock_key, ttl=120)
    except builtins.Exception as exc:
        logger.warning("LOCK ACQUIRE FAILED: %s (%s)", lock_key, exc, exc_info=True)
        return

    if not lock_value:
        logger.debug("LOCK SKIP: %s", lock_key)
        return

    try:
        await send_inactivity_reminder_job(user_id, pair_id)
    finally:
        try:
            await release_lock(lock_key, lock_value)
        except builtins.Exception:
            logger.warning("Failed to release lock: %s", lock_key, exc_info=True)
