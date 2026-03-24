from __future__ import annotations

import asyncio
import builtins
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if builtins.str(ROOT) not in sys.path:
    sys.path.insert(0, builtins.str(ROOT))

from app.services.result_service import build_result_text, get_last_result, save_result


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalars(self):
        return self

    def first(self):
        return self._row


class _FakeSession:
    def __init__(self) -> None:
        self.saved: builtins.list = []

    def add(self, obj) -> None:
        self.saved.append(obj)

    async def commit(self) -> None:
        return None

    async def refresh(self, obj) -> None:
        return None

    async def execute(self, stmt):
        user_id = stmt._where_criteria[0].right.value
        filtered = [row for row in self.saved if row.user_id == user_id]
        filtered.sort(key=lambda r: r.created_at, reverse=True)
        return _FakeResult(filtered[0] if filtered else None)


async def _run() -> None:
    session = _FakeSession()
    await save_result(
        session=session,
        user_id=123,
        pair_session_id=10,
        teen_scores={"independence": 8},
        parent_scores={"independence": 6},
        diff={"independence": {"diff": 2, "status": "gap"}},
        ai_report="stub report",
    )

    result = await get_last_result(session=session, user_id=123)
    assert result is not None
    assert result.ai_report == "stub report"


def test_save_result() -> None:
    asyncio.run(_run())


def test_get_last_result() -> None:
    asyncio.run(_run())


def test_build_result_text() -> None:
    class _Result:
        ai_report = "Готовый AI отчёт"

    text = build_result_text(_Result())
    assert "📊 Твой последний результат" in text
    assert "Готовый AI отчёт" in text
