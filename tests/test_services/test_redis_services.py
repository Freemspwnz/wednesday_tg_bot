from __future__ import annotations

from typing import Any

import pytest

from services.prompt_cache import PromptCache
from services.rate_limiter import CircuitBreaker, RateLimiter
from services.user_state_store import UserStateStore
from utils.redis_client import _InMemoryRedis


@pytest.mark.asyncio
async def test_prompt_cache_set_get_delete() -> None:
    backend = _InMemoryRedis()
    cache = PromptCache(redis_client=backend, prefix="test:prompt:", default_ttl=10)

    key = "k1"
    payload: dict[str, Any] = {"text": "hello", "n": 1}

    assert await cache.get(key) is None

    await cache.set(key, payload)
    loaded = await cache.get(key)

    assert isinstance(loaded, dict)
    assert loaded == payload
    assert await cache.exists(key) is True

    await cache.delete(key)
    assert await cache.get(key) is None


@pytest.mark.asyncio
async def test_user_state_store_roundtrip() -> None:
    backend = _InMemoryRedis()
    store = UserStateStore(redis_client=backend, prefix="test:user:")

    uid = 123
    state: dict[str, Any] = {"step": "intro", "flag": True}

    assert await store.get_state(uid) is None

    await store.set_state(uid, state)
    loaded = await store.get_state(uid)

    assert isinstance(loaded, dict)
    assert loaded == state

    await store.clear_state(uid)
    assert await store.get_state(uid) is None


@pytest.mark.asyncio
async def test_rate_limiter_allows_until_limit() -> None:
    backend = _InMemoryRedis()
    limiter = RateLimiter(redis_client=backend, prefix="test:rate:", window=60, limit=3)

    key = "user-1"
    assert await limiter.is_allowed(key) is True
    assert await limiter.is_allowed(key) is True
    assert await limiter.is_allowed(key) is True
    # Четвёртый вызов в том же окне должен быть заблокирован.
    assert await limiter.is_allowed(key) is False

    await limiter.reset(key)
    assert await limiter.is_allowed(key) is True


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_threshold() -> None:
    backend = _InMemoryRedis()
    breaker = CircuitBreaker(redis_client=backend, key="test:cb", threshold=2, window=60, cooldown=60)

    assert await breaker.is_open() is False

    await breaker.record_failure()
    assert await breaker.is_open() is False

    await breaker.record_failure()
    # После двух ошибок подряд circuit должен открыться.
    assert await breaker.is_open() is True

    await breaker.reset()
    assert await breaker.is_open() is False
