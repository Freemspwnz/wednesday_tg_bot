"""
Единый асинхронный клиент Redis для всего приложения.

Дизайн:
- Используем один экземпляр клиента `redis.asyncio.Redis` на всё время жизни приложения.
- Инициализация выполняется один раз через `init_redis_pool(...)` (обычно при старте в `main.py`).
- Остальной код импортирует и использует `get_redis()`, не создавая собственных подключений.
- При недоступности Redis используется лёгкий in‑memory fallback c поддержкой TTL.

Почему один клиент:
- Клиент `redis.asyncio.Redis` сам управляет пулом подключений.
- Создание клиента на каждый запрос приводит к лишним TCP‑подключениям и утечкам ресурсов.
- Единый клиент упрощает конфигурацию и позволяет централизованно отслеживать доступность Redis.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, cast

import redis.asyncio as redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


class _InMemoryRedis:
    """
    Минимальный in‑memory аналог части API `redis.asyncio.Redis`.

    Используется как:
    - стартовый backend до инициализации реального Redis;
    - fallback, если Redis недоступен.

    Поддерживаем только те операции, которые реально используются сервисами:
    - get / set / delete / exists / keys
    - expire
    - incr / hincrby
    - hset / hgetall

    Все методы асинхронные для совместимости с `redis.asyncio`.
    TTL реализован лениво: ключи очищаются при доступе.
    """

    def __init__(self) -> None:
        # string -> (value, expire_ts | None)
        self._data: dict[str, tuple[str, float | None]] = {}
        # string -> (field_map, expire_ts | None)
        self._hashes: dict[str, tuple[dict[str, str], float | None]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _is_expired(expire_at: float | None) -> bool:
        return expire_at is not None and expire_at <= time.time()

    async def _purge_if_expired(self, key: str) -> None:
        # строки
        if key in self._data:
            _, exp = self._data[key]
            if self._is_expired(exp):
                self._data.pop(key, None)
        # хэши
        if key in self._hashes:
            _, exp = self._hashes[key]
            if self._is_expired(exp):
                self._hashes.pop(key, None)

    async def get(self, name: str) -> str | None:
        async with self._lock:
            await self._purge_if_expired(name)
            entry = self._data.get(name)
            return entry[0] if entry is not None else None

    async def set(self, name: str, value: object, ex: int | None = None) -> bool:
        # Приводим к строке, имитируя decode_responses=True
        val_str = str(value)
        expire_at = time.time() + ex if ex is not None else None
        async with self._lock:
            self._data[name] = (val_str, expire_at)
        return True

    async def delete(self, name: str) -> int:
        async with self._lock:
            await self._purge_if_expired(name)
            existed = name in self._data or name in self._hashes
            self._data.pop(name, None)
            self._hashes.pop(name, None)
        return int(existed)

    async def exists(self, name: str) -> int:
        async with self._lock:
            await self._purge_if_expired(name)
            return int(name in self._data or name in self._hashes)

    async def keys(self, pattern: str = "*") -> list[str]:
        # Для простоты игнорируем сложные шаблоны и возвращаем все ключи.
        async with self._lock:
            # Чистим протухшие ключи
            for k in list(self._data.keys()):
                await self._purge_if_expired(k)
            for k in list(self._hashes.keys()):
                await self._purge_if_expired(k)
            return list(set(self._data.keys()) | set(self._hashes.keys()))

    async def expire(self, name: str, time_seconds: int) -> bool:
        expire_at = time.time() + time_seconds
        async with self._lock:
            if name in self._data:
                value, _ = self._data[name]
                self._data[name] = (value, expire_at)
                return True
            if name in self._hashes:
                fields, _ = self._hashes[name]
                self._hashes[name] = (fields, expire_at)
                return True
        return False

    async def incr(self, name: str) -> int:
        async with self._lock:
            await self._purge_if_expired(name)
            current = 0
            if name in self._data:
                raw, _exp = self._data[name]
                try:
                    current = int(raw)
                except (TypeError, ValueError):
                    current = 0
            current += 1
            self._data[name] = (str(current), None)
            return current

    async def hset(self, name: str, mapping: dict[str, Any]) -> int:
        async with self._lock:
            await self._purge_if_expired(name)
            if name in self._hashes:
                fields, exp = self._hashes[name]
            else:
                fields, exp = {}, None
            changed = 0
            for k, v in mapping.items():
                v_str = str(v)
                if fields.get(k) != v_str:
                    changed += 1
                fields[k] = v_str
            self._hashes[name] = (fields, exp)
            return changed

    async def hgetall(self, name: str) -> dict[str, str]:
        async with self._lock:
            await self._purge_if_expired(name)
            entry = self._hashes.get(name)
            if not entry:
                return {}
            fields, _ = entry
            # Возвращаем копию, чтобы не дать внешнему коду мутировать внутреннее состояние.
            return dict(fields)

    async def hincrby(self, name: str, key: str, amount: int = 1) -> int:
        async with self._lock:
            await self._purge_if_expired(name)
            if name in self._hashes:
                fields, exp = self._hashes[name]
            else:
                fields, exp = {}, None
            current = 0
            if key in fields:
                try:
                    current = int(fields[key])
                except (TypeError, ValueError):
                    current = 0
            current += int(amount)
            fields[key] = str(current)
            self._hashes[name] = (fields, exp)
            return current

    @staticmethod
    async def close() -> None:  # совместимость с `redis.Redis.close()`
        # Для in‑memory варианта ничего закрывать не нужно.
        return


_redis: redis.Redis | _InMemoryRedis = _InMemoryRedis()
_redis_lock = asyncio.Lock()
_redis_is_real: bool = False


async def init_redis_pool(
    url: str | None = None,
    *,
    host: str = "localhost",
    port: int = 6379,
    db: int = 0,
    password: str | None = None,
    **kwargs: object,
) -> redis.Redis:
    """
    Инициализирует глобальный Redis‑клиент (один на всё приложение).

    Предпочтительный способ создания:
    - Использовать `REDIS_URL` (например: redis://localhost:6379/0).
    - При отсутствии `url` используются параметры `host/port/db/password`.

    При успешной инициализации выполняется `PING`, чтобы убедиться в доступности сервиса.
    В случае ошибки логируем исключение и пробрасываем его дальше — вызывающий код
    решает, считать ли Redis критичным или перейти в режим fallback.
    """
    global _redis, _redis_is_real  # noqa: PLW0603

    async with _redis_lock:
        # Если уже инициализирован реальный клиент — просто возвращаем его.
        if isinstance(_redis, redis.Redis) and _redis_is_real:
            return _redis

        try:
            if url:
                client = cast(redis.Redis, redis.from_url(url, decode_responses=True, **kwargs))
            else:
                client = redis.Redis(
                    host=host,
                    port=port,
                    db=db,
                    password=password,
                    decode_responses=True,
                    **cast(dict[str, Any], kwargs),
                )

            await client.ping()
            _redis = client
            _redis_is_real = True
            logger.info(
                f"Подключение к Redis установлено (url={url!r}, host={host!r}, port={port!r}, db={db!r})",
            )
            return client
        except Exception as exc:
            # ВАЖНО: не обнуляем `_redis`, чтобы сохранить in‑memory fallback.
            logger.exception(f"Не удалось инициализировать Redis‑клиент: {exc!s}")
            _redis_is_real = False
            raise


def get_redis() -> redis.Redis | _InMemoryRedis:
    """
    Возвращает инициализированный Redis‑клиент.

    Поведение:
    - Если `init_redis_pool()` был успешно вызван — возвращается реальный клиент Redis.
    - Если инициализация не выполнялась или не удалась — возвращается in‑memory fallback.

    Такое поведение гарантирует, что остальной код может всегда вызывать `get_redis()`
    без дополнительной проверки на `None`, а доступность настоящего Redis можно
    узнать через `redis_available()`.
    """
    return _redis


async def close_redis() -> None:
    """
    Закрывает подключение к Redis, если оно было установлено.
    Для in‑memory fallback делать ничего не нужно.
    """
    global _redis_is_real  # noqa: PLW0603

    if isinstance(_redis, redis.Redis):
        try:
            await _redis.close()
            logger.info("Соединение с Redis закрыто")
        except Exception:
            logger.exception("Ошибка при закрытии соединения с Redis")
    _redis_is_real = False
    # Не обнуляем `_redis`: оставляем in‑memory fallback.


def redis_available() -> bool:
    """
    Возвращает True, если в данный момент используется реальный Redis‑клиент.

    Этот флаг можно использовать в метриках/логах, чтобы понимать,
    работает ли приложение в "боевом" режиме Redis или в деградированном in‑memory режиме.
    """
    return _redis_is_real


async def safe_redis_call(func_name: str, *args: object, **kwargs: object) -> object:
    """
    Вспомогательная обёртка для безопасного вызова операций Redis.

    Используется в сервисах, где важно:
    - корретно залогировать ошибку Redis;
    - НЕ падать при недоступности Redis (деградация до in‑memory поведения).

    Параметр `func_name` — имя метода Redis (например, "set", "get", "incr").
    Остальные аргументы передаются как есть в метод клиента.
    """
    client = get_redis()
    method = getattr(client, func_name, None)
    if method is None:
        raise AttributeError(f"Redis backend не поддерживает метод {func_name!r}")

    try:
        return await method(*args, **kwargs)
    except RedisError as exc:
        logger.warning(
            "RedisError в safe_redis_call "
            f"({func_name}) — backend={type(client).__name__}, переходим к in‑memory режиму: {exc!s}",
        )
        # При ошибке реального Redis переключаемся на in‑memory backend.
        global _redis, _redis_is_real  # noqa: PLW0603
        if isinstance(_redis, redis.Redis):
            _redis = _InMemoryRedis()
            _redis_is_real = False
        # Повторяем операцию уже на in‑memory backend (ошибки пробрасываем).
        fallback = get_redis()
        fallback_method = getattr(fallback, func_name, None)
        if fallback_method is None:
            raise
        return await fallback_method(*args, **kwargs)
