from __future__ import annotations

import builtins
import logging
from datetime import datetime
from typing import Any, Awaitable, Callable

from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def init_scheduler() -> AsyncIOScheduler:
    global _scheduler

    if _scheduler:
        return _scheduler

    jobstores = {
        "default": RedisJobStore(
            host="127.0.0.1",
            port=6379,
            db=2,
            jobs_key="apscheduler.jobs",
            run_times_key="apscheduler.running",
        )
    }

    _scheduler = AsyncIOScheduler(
        jobstores=jobstores,
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 3600,
        },
    )
    _scheduler.start()
    logger.info("Scheduler started with RedisJobStore")
    return _scheduler


def get_scheduler() -> AsyncIOScheduler:
    if not _scheduler:
        return init_scheduler()
    return _scheduler


def schedule_reminder(
    job_id: builtins.str,
    run_at: datetime,
    func: Callable[..., Awaitable[Any]] | Callable[..., Any] | builtins.str,
    *args: Any,
) -> builtins.bool:
    scheduler = get_scheduler()
    scheduler.add_job(
        func,
        trigger="date",
        run_date=run_at,
        args=args,
        id=job_id,
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
        jobstore="default",
    )
    logger.info("[SCHEDULER] job=%s run_at=%s", job_id, run_at.isoformat())
    return True


def cancel_job(job_id: builtins.str) -> None:
    scheduler = get_scheduler()
    try:
        scheduler.remove_job(job_id, jobstore="default")
    except builtins.Exception:
        logger.warning("Failed to cancel scheduler job: %s", job_id, exc_info=True)


def scheduler_probe(tag: builtins.str) -> None:
    logger.info("SCHEDULER_PROBE: %s", tag)


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return

    try:
        _scheduler.shutdown(wait=False)
    except builtins.Exception:
        logger.warning("Scheduler shutdown failed", exc_info=True)
    finally:
        _scheduler = None
