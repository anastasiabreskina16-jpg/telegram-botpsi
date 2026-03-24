from __future__ import annotations

import asyncio
import os

import pytest
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import settings
from main import _build_storage


def test_storage_builder_returns_storage() -> None:
    previous_app_env = os.environ.get("APP_ENV")
    os.environ["APP_ENV"] = "development"
    try:
        storage = asyncio.run(_build_storage())
        assert storage is not None
        assert isinstance(storage, MemoryStorage) or storage.__class__.__name__ == "RedisStorage"
    finally:
        if previous_app_env is None:
            os.environ.pop("APP_ENV", None)
        else:
            os.environ["APP_ENV"] = previous_app_env


def test_storage_builder_raises_in_production_without_redis() -> None:
    previous_app_env = os.environ.get("APP_ENV")
    original_redis_url = settings.redis_url
    os.environ["APP_ENV"] = "production"
    try:
        object.__setattr__(settings, "redis_url", "redis://127.0.0.1:6399/0")
        with pytest.raises(RuntimeError):
            asyncio.run(_build_storage())
    finally:
        object.__setattr__(settings, "redis_url", original_redis_url)
        if previous_app_env is None:
            os.environ.pop("APP_ENV", None)
        else:
            os.environ["APP_ENV"] = previous_app_env