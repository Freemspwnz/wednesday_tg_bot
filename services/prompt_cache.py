"""
Сервис кэширования промптов в Redis.

Основные задачи:
- Хранить недавно сгенерированные промпты (например, для Kandinsky) с TTL.
- Давать быстрый доступ к последним успешным промптам без повторного обращения к GigaChat.
- Работать поверх Redis, но автоматически деградировать в in‑memory режим при недоступности Redis.

Дизайн:
- Ключи в Redis формируются как `<prefix><key>`, где prefix по умолчанию `"prompt:"`.
- Значения сохраняются в виде JSON‑строк, чтобы поддерживать как строки, так и словари.
- TTL задаётся на уровне SET/SETEX; если ttl не указан, используется default_ttl.
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


class PromptCache:
    """
    Кэш промптов на базе Redis с автоматическим fallback в память.
    """

    def __init__(
        self,
        redis_client: RedisBackend | None = None,
        *,
        prefix: str = "prompt:",
        default_ttl: int = 3600,
    ) -> None:
        """
        Args:
            redis_client: Экземпляр redis.asyncio.Redis или совместимого клиента.
                Если None — будет использован глобальный клиент через `get_redis()`.
            prefix: Префикс для всех ключей этого кэша.
            default_ttl: Время жизни записей по умолчанию (в секундах).
        """
        backend = redis_client or get_redis()
        self._redis: RedisBackend = backend
        self._prefix = prefix
        self._default_ttl = default_ttl
        # Локальный fallback-кэш на случай ошибок Redis.
        self._fallback: _InMemoryRedis = _InMemoryRedis()

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    async def set(self, key: str, prompt: dict | str, ttl: int | None = None) -> None:
        """
        Сохраняет промпт с TTL.

        Использует:
        - SET с параметром EX в Redis;
        - in‑memory fallback при RedisError.
        """
        full_key = self._key(key)
        payload = json.dumps(prompt, ensure_ascii=False)
        ttl_value = ttl if ttl is not None else self._default_ttl

        try:
            await self._redis.set(full_key, payload, ex=ttl_value)
        except RedisError as exc:
            logger.warning(
                f"Redis error в PromptCache.set ({full_key}) — используем fallback in‑memory, ttl={ttl_value}: {exc!s}",
            )
            await self._fallback.set(full_key, payload, ex=ttl_value)

    async def get(self, key: str) -> dict | str | None:
        """
        Возвращает сохранённый промпт или None.
        """
        full_key = self._key(key)

        try:
            raw = await self._redis.get(full_key)
        except RedisError as exc:
            logger.warning(
                f"Redis error в PromptCache.get ({full_key}) — пробуем fallback in‑memory: {exc!s}",
            )
            raw = await self._fallback.get(full_key)

        if raw is None:
            return None

        try:
            loaded: Any = json.loads(raw)
        except json.JSONDecodeError:
            # В редких случаях можем получить "сырой" текст.
            return raw

        # В этом сервисе мы ожидаем либо словарь (JSON‑объект), либо строку.
        if isinstance(loaded, dict):
            return loaded
        if isinstance(loaded, str):
            return loaded
        return str(loaded)

    async def delete(self, key: str) -> None:
        """
        Удаляет запись из кэша.
        """
        full_key = self._key(key)
        try:
            await self._redis.delete(full_key)
        except RedisError as exc:
            logger.warning(
                f"Redis error в PromptCache.delete ({full_key}) — удаляем только из fallback: {exc!s}",
            )
        await self._fallback.delete(full_key)

    async def exists(self, key: str) -> bool:
        """
        Проверяет наличие ключа в кэше.
        """
        full_key = self._key(key)
        try:
            exists_val = await self._redis.exists(full_key)
        except RedisError as exc:
            logger.warning(
                f"Redis error в PromptCache.exists ({full_key}) — проверяем только fallback: {exc!s}",
            )
            exists_val = await self._fallback.exists(full_key)
        return bool(exists_val)

    async def keys(self, pattern: str = "*") -> list[str]:
        """
        Возвращает список ключей (без префикса) по шаблону.

        Важно:
        - Это вспомогательный метод и не должен использоваться в "горячем" пути,
          так как операция KEYS в Redis — потенциально тяжёлая.
        """
        prefixed_pattern = f"{self._prefix}{pattern}"
        try:
            raw_keys = await self._redis.keys(prefixed_pattern)
        except RedisError as exc:
            logger.warning(
                f"Redis error в PromptCache.keys ({prefixed_pattern}) — используем только fallback: {exc!s}",
            )
            raw_keys = await self._fallback.keys(prefixed_pattern)

        # Снимаем префикс, чтобы вернуть "логические" ключи.
        return [k[len(self._prefix) :] for k in raw_keys if k.startswith(self._prefix)]
