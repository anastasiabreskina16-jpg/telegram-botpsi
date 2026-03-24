import asyncio
import atexit
import contextlib
import logging
import os
from pathlib import Path
import subprocess

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis

from app.config import settings
from app.db.session import init_db
from app.handlers import menu_router, observation_router, pair_test_router, start_router
from app.services.retention_service import process_retention_reminders, set_scheduler_bot
from app.services.scheduler_service import init_scheduler, shutdown_scheduler
from app.services.timeout_service import handle_timeout, send_waiting_reminder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s: %(message)s",
)
log = logging.getLogger(__name__)
LOCK_FILE = Path("bot.lock")


def _is_production() -> bool:
    env = (os.getenv("APP_ENV") or os.getenv("ENV") or "").strip().lower()
    return env in {"prod", "production"}


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False

    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        output = (result.stdout or "")
        if "No tasks are running" in output:
            return False
        return str(pid) in output

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we may not have permission to signal it.
        return True
    return True


def _acquire_lock() -> None:
    if LOCK_FILE.exists():
        try:
            existing_pid = int((LOCK_FILE.read_text(encoding="utf-8").strip() or "0"))
        except Exception:
            existing_pid = 0

        if existing_pid > 0 and _pid_is_running(existing_pid):
            raise RuntimeError("Bot already running")
        # Stale lock from dead process
        LOCK_FILE.unlink(missing_ok=True)

    LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")


def _release_lock() -> None:
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        log.warning("Failed to remove lock file", exc_info=True)


async def _build_storage():
    if not settings.redis_url:
        if _is_production():
            raise RuntimeError("REDIS_URL is not configured")
        log.warning("REDIS_URL is not configured, using MemoryStorage in non-production mode")
        return MemoryStorage()

    redis = Redis.from_url(settings.redis_url)
    try:
        await redis.ping()
    except Exception as exc:
        await redis.aclose()
        if _is_production():
            raise RuntimeError("Redis is not available") from exc
        log.warning("Redis is not available, using MemoryStorage in non-production mode")
        return MemoryStorage()

    log.info("✅ Redis connected")
    return RedisStorage(redis=redis, state_ttl=3600, data_ttl=3600)


async def timeout_loop(bot: Bot, sessionmaker) -> None:
    while True:
        try:
            async with sessionmaker() as session:
                await send_waiting_reminder(bot, session)
                await handle_timeout(bot, session)
                await process_retention_reminders(bot, session)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("timeout_loop iteration failed")

        await asyncio.sleep(60)


async def main() -> None:
    _acquire_lock()
    atexit.register(_release_lock)

    await init_db()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    scheduler = None
    try:
        scheduler = init_scheduler()
        if scheduler is not None:
            log.info("Scheduler enabled")
            set_scheduler_bot(bot)
            for job in scheduler.get_jobs(jobstore="default"):
                log.info("RESTORED JOB: %s -> %s", job.id, job.next_run_time)
        else:
            log.warning("Scheduler disabled: APScheduler is unavailable")
    except Exception as exc:
        scheduler = None
        log.warning("Scheduler disabled: %s", exc)

    timeout_task: asyncio.Task | None = None
    try:
        storage = await _build_storage()
        dp = Dispatcher(storage=storage, events_isolation=SimpleEventIsolation())
        dp.include_router(start_router)
        dp.include_router(observation_router)
        dp.include_router(pair_test_router)
        dp.include_router(menu_router)

        from app.db.session import AsyncSessionLocal

        timeout_task = asyncio.create_task(timeout_loop(bot, AsyncSessionLocal))

        # Clean startup: drop stale webhook and pending updates before polling.
        await bot.delete_webhook(drop_pending_updates=True)

        log.info("🚀 Bot started")
        log.info("⚡ Polling active")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        if timeout_task is not None:
            timeout_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await timeout_task
        if scheduler is not None:
            shutdown_scheduler()
        _release_lock()


if __name__ == "__main__":
    asyncio.run(main())
