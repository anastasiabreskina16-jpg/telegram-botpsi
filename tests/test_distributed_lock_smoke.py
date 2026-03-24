import asyncio

from app.jobs import reminders


def test_send_inactivity_reminder_safe_skips_without_lock(monkeypatch) -> None:
    called = {"job": False}

    async def _acquire_lock(_key: str, ttl: int = 60):
        return None

    async def _send_job(_user_id: int, _pair_id: int):
        called["job"] = True

    monkeypatch.setattr(reminders, "acquire_lock", _acquire_lock)
    monkeypatch.setattr(reminders, "send_inactivity_reminder_job", _send_job)

    asyncio.run(reminders.send_inactivity_reminder_safe(101, 202))

    assert called["job"] is False


def test_send_inactivity_reminder_safe_executes_and_releases(monkeypatch) -> None:
    state = {"job": False, "released": False}

    async def _acquire_lock(_key: str, ttl: int = 60):
        return "token-1"

    async def _release_lock(_key: str, _value: str):
        state["released"] = True

    async def _send_job(_user_id: int, _pair_id: int):
        state["job"] = True

    monkeypatch.setattr(reminders, "acquire_lock", _acquire_lock)
    monkeypatch.setattr(reminders, "release_lock", _release_lock)
    monkeypatch.setattr(reminders, "send_inactivity_reminder_job", _send_job)

    asyncio.run(reminders.send_inactivity_reminder_safe(101, 202))

    assert state["job"] is True
    assert state["released"] is True
