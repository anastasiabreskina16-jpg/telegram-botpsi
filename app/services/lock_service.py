from __future__ import annotations

import builtins
import uuid

from redis import asyncio as aioredis

from app.config import settings

_REDIS = aioredis.from_url(settings.redis_url or "redis://127.0.0.1:6379/0", decode_responses=True)
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


async def acquire_lock(key: builtins.str, ttl: builtins.int = 60) -> builtins.str | None:
    value = builtins.str(uuid.uuid4())
    result = await _REDIS.set(key, value, ex=ttl, nx=True)
    if result:
        return value
    return None


async def release_lock(key: builtins.str, value: builtins.str) -> None:
    await _REDIS.eval(_RELEASE_SCRIPT, 1, key, value)


async def extend_lock(key: builtins.str, value: builtins.str, ttl: builtins.int = 120) -> builtins.bool:
    script = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
        return redis.call('expire', KEYS[1], ARGV[2])
    else
        return 0
    end
    """
    result = await _REDIS.eval(script, 1, key, value, ttl)
    return builtins.bool(result)
