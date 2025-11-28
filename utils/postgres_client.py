"""
Асинхронный клиент PostgreSQL с пулом подключений для всего приложения.

Дизайн:
- Используем единый пул `asyncpg.Pool` на всё время жизни процесса.
- Инициализация выполняется один раз через `init_postgres_pool(...)` (обычно при старте в `main.py`).
- Остальной код получает пул через `get_postgres_pool()` и не создает собственные подключения.

Поведение при ошибках:
- При неудачной инициализации логируем подробную ошибку и пробрасываем её дальше —
  запуск приложения должен явно решать, считать ли Postgres критичным.
"""

from __future__ import annotations

import asyncio

import asyncpg

from utils.config import config
from utils.logger import get_logger

logger = get_logger(__name__)

_pool: asyncpg.Pool | None = None
_pool_loop: asyncio.AbstractEventLoop | None = None


async def init_postgres_pool(
    *,
    min_size: int = 1,
    max_size: int = 10,
    **connect_kwargs: object,
) -> asyncpg.Pool:
    """
    Инициализирует глобальный пул подключений к PostgreSQL.

    Параметры подключения берутся из переменных окружения:
    - POSTGRES_USER
    - POSTGRES_PASSWORD
    - POSTGRES_DB
    - POSTGRES_HOST
    - POSTGRES_PORT

    Args:
        min_size: минимальное количество подключений в пуле
        max_size: максимальное количество подключений в пуле
        **connect_kwargs: дополнительные параметры для asyncpg.create_pool

    Returns:
        Инициализированный пул подключений.

    Raises:
        Exception: при ошибке подключения или проверки соединения.
    """
    global _pool, _pool_loop  # noqa: PLW0603

    # Проверяем, был ли пул создан в другом event loop
    current_loop = asyncio.get_running_loop()
    if _pool is not None and _pool_loop is not None and _pool_loop is not current_loop:
        # Пул был создан в другом loop, закрываем его и создаём новый
        logger.warning("Пул Postgres был создан в другом event loop, пересоздаём пул")
        try:
            await _pool.close()
        except Exception:
            pass
        _pool = None
        _pool_loop = None

    if _pool is not None:
        return _pool

    user = config.postgres_user
    password = config.postgres_password
    database = config.postgres_db
    host = config.postgres_host
    port = config.postgres_port

    dsn = f"postgresql://{user}:{password}@{host}:{port}/{database}"

    logger.info(
        f"Инициализация пула Postgres (host={host}, port={port}, db={database}, "
        f"min_size={min_size}, max_size={max_size})",
    )

    try:
        _pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=min_size,
            max_size=max_size,
            **connect_kwargs,
        )

        # Быстрая проверка соединения
        async with _pool.acquire() as conn:
            await conn.execute("SELECT 1;")

        # Сохраняем ссылку на event loop, в котором был создан пул
        _pool_loop = current_loop

        logger.info("Пул подключений Postgres успешно инициализирован")
        return _pool
    except Exception as exc:  # pragma: no cover - защитное логирование
        logger.error(f"Не удалось инициализировать пул Postgres: {exc}")
        # На всякий случай обнуляем пул, чтобы не оставить битое состояние
        _pool = None
        raise


def get_postgres_pool() -> asyncpg.Pool:
    """
    Возвращает инициализированный пул подключений к PostgreSQL.

    Raises:
        RuntimeError: если пул ещё не инициализирован.
    """
    if _pool is None:
        raise RuntimeError(
            "Postgres pool не инициализирован. Вызовите init_postgres_pool() на этапе старта приложения.",
        )
    return _pool


async def close_postgres_pool() -> None:
    """
    Закрывает пул подключений к PostgreSQL, если он был инициализирован.
    """
    global _pool, _pool_loop  # noqa: PLW0603

    if _pool is not None:
        try:
            await _pool.close()
            logger.info("Пул Postgres успешно закрыт")
        except Exception as exc:  # pragma: no cover - защитное логирование
            logger.error(f"Ошибка при закрытии пула Postgres: {exc}")
        finally:
            _pool = None
            _pool_loop = None
