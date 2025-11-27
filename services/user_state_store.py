"""
Хранилище временного состояния пользователя на базе Redis.

Назначение:
- Сохранять ephemeral‑состояние пользователя (шаги диалога, последние действия и т.п.).
- Поддерживать TTL для автоматической очистки "зависших" состояний.

Дизайн:
- Для гибкости используется JSON‑blob в виде SET/GET, а не HSET/HGETALL.
  Это упрощает эволюцию структуры состояния без миграций схемы.
- TTL реализуется через EXPIRE на ключе.
"""

from __future__ import annotations

import json
import logging
from typing import Any, TypeAlias

import redis.asyncio as redis
from redis.exceptions import RedisError

from utils.redis_client import _InMemoryRedis, get_redis

logger = logging.getLogger(__name__)


RedisBackend: TypeAlias = redis.Redis | _InMemoryRedis


class UserStateStore:
    """
    Хранилище временного состояния пользователя.
    """

    def __init__(
        self,
        redis_client: RedisBackend | None = None,
        *,
        prefix: str = "user_state:",
    ) -> None:
        """
        Args:
            redis_client: Экземпляр redis.asyncio.Redis или совместимого клиента.
                Если None — будет использован глобальный клиент через `get_redis()`.
            prefix: Префикс ключей для хранения состояний.
        """
        backend = redis_client or get_redis()
        self._redis: RedisBackend = backend
        self._prefix = prefix
        self._fallback: _InMemoryRedis = _InMemoryRedis()

    def _key(self, user_id: int) -> str:
        return f"{self._prefix}{user_id}"

    async def set_state(self, user_id: int, state: dict[str, Any], ttl: int | None = None) -> None:
        """
        Сохраняет состояние пользователя как JSON‑blob.

        TTL:
        - Если указан ttl — применяется через EXPIRE к ключу.
        - Если ttl не указан — состояние живёт до явного сброса.
        """
        key = self._key(user_id)
        payload = json.dumps(state, ensure_ascii=False)
        try:
            if ttl is not None:
                await self._redis.set(key, payload, ex=ttl)
            else:
                await self._redis.set(key, payload)
        except RedisError as exc:
            logger.warning(
                f"Redis error в UserStateStore.set_state ({key}) — используем fallback in‑memory: {exc!s}",
            )
            if ttl is not None:
                await self._fallback.set(key, payload, ex=ttl)
            else:
                await self._fallback.set(key, payload)

    async def get_state(self, user_id: int) -> dict[str, Any] | None:
        """
        Возвращает состояние пользователя или None.
        """
        key = self._key(user_id)
        try:
            raw = await self._redis.get(key)
        except RedisError as exc:
            logger.warning(
                f"Redis error в UserStateStore.get_state ({key}) — пробуем fallback in‑memory: {exc!s}",
            )
            raw = await self._fallback.get(key)

        if raw is None:
            return None

        try:
            value: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(
                f"Не удалось декодировать состояние пользователя {user_id} как JSON, состояние сброшено",
            )
            return None
        return value

    async def clear_state(self, user_id: int) -> None:
        """
        Полностью очищает состояние пользователя.
        """
        key = self._key(user_id)
        try:
            await self._redis.delete(key)
        except RedisError as exc:
            logger.warning(
                f"Redis error в UserStateStore.clear_state ({key}) — удаляем только из fallback: {exc!s}",
            )
        await self._fallback.delete(key)
