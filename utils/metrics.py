"""
Система метрик для отслеживания производительности на базе PostgreSQL.

Ранее данные хранились в JSON-файле `data/metrics.json`, теперь используется
таблица `metrics` (см. `utils.postgres_schema`).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from utils.logger import get_logger, log_all_methods
from utils.postgres_client import get_postgres_pool
from utils.redis_client import safe_redis_call

_logger = get_logger(__name__)


@runtime_checkable
class _SupportsExecute(Protocol):
    async def execute(self, query: str, *args: object) -> object:  # pragma: no cover - протокол
        ...


async def record_metric(  # noqa: PLR0913
    db: _SupportsExecute | None = None,
    *,
    event_type: str,
    user_id: str | None = None,
    prompt_hash: str | None = None,
    image_hash: str | None = None,
    latency_ms: int | None = None,
    status: str | None = None,
) -> None:
    """
    Публикует единичное событие метрики в очередь (Redis Stream).

    Параметры:
        db: Необязательный объект с методом execute (asyncpg.Connection или пул).
            Если не указан, может использоваться как fallback для прямой
            записи в Postgres при недоступности очереди.
        event_type: Тип события ('error', 'generation', 'cache_hit', 'cache_miss' и т.п.).
        user_id: Идентификатор пользователя (например, Telegram user_id).
        prompt_hash: Хэш промпта (sha256, 64-символьное hex-представление).
        image_hash: Хэш изображения (sha256, 64-символьное hex-представление).
        latency_ms: Латентность в миллисекундах.
        status: Статус события ('ok', 'error', 'cached', 'started' и т.п.).

    Примечание по производительности:
        В текущей реализации событие публикуется в Redis Stream
        `metrics:events` с помощью быстрой команды XADD, что минимально
        влияет на горячий путь. При необходимости дальнейшего масштабирования
        можно добавить отдельного воркера, который будет читать события из
        стрима и агрегировать их в Postgres или внешние системы мониторинга.
    """

    # Защита от пустого event_type.
    if not event_type:
        _logger.warning("record_metric: пропущена запись события из-за пустого event_type")
        return

    try:
        # Публикуем событие в Redis Stream `metrics:events`.
        fields: dict[str, Any] = {
            "event_type": event_type,
            "user_id": user_id or "",
            "prompt_hash": prompt_hash or "",
            "image_hash": image_hash or "",
            "latency_ms": latency_ms if latency_ms is not None else "",
            "status": status or "",
        }
        await safe_redis_call("xadd", "metrics:events", fields)

        # Дополнительно стараемся синхронно зафиксировать событие в таблице Postgres.
        # Это делает события наблюдаемыми через SQL (в том числе в тестах и админских
        # diagnostics), при этом ошибка записи в БД не должна влиять на горячий путь.
        try:
            pool = get_postgres_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO metrics_events (
                        event_type,
                        user_id,
                        prompt_hash,
                        image_hash,
                        latency_ms,
                        status
                    )
                    VALUES ($1, $2, $3, $4, $5, $6);
                    """,
                    event_type,
                    user_id,
                    prompt_hash,
                    image_hash,
                    latency_ms,
                    status,
                )
        except Exception as db_exc:  # pragma: no cover - best-effort запись в БД
            _logger.warning(
                f"record_metric: не удалось синхронно сохранить событие метрики в Postgres: {db_exc}",
            )

        _logger.info(
            "Событие метрики записано: "
            f"type={event_type} prompt={prompt_hash} user={user_id} image={image_hash} "
            f"latency_ms={latency_ms} status={status}",
        )
    except Exception as exc:  # pragma: no cover - защитное логирование и fallback
        _logger.error(
            f"record_metric: не удалось опубликовать событие метрики в Redis Stream: {exc}",
            exc_info=True,
        )
        # Fallback: при недоступности очереди можем (опционально) писать напрямую в Postgres.
        try:
            pool = get_postgres_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO metrics_events (
                        event_type,
                        user_id,
                        prompt_hash,
                        image_hash,
                        latency_ms,
                        status
                    )
                    VALUES ($1, $2, $3, $4, $5, $6);
                    """,
                    event_type,
                    user_id,
                    prompt_hash,
                    image_hash,
                    latency_ms,
                    status,
                )
            _logger.info("Событие метрики сохранено напрямую в Postgres (fall back, Redis недоступен)")
        except Exception as db_exc:  # pragma: no cover - двойной защитный контур
            _logger.error(
                f"record_metric: не удалось сохранить событие метрики даже в Postgres: {db_exc}",
                exc_info=True,
            )


@log_all_methods()
class Metrics:
    """
    Репозиторий метрик производительности.

    Все значения агрегируются в одной строке с id=1, что достаточно для
    текущих сценариев мониторинга.
    """

    def __init__(self, storage_path: str | None = None) -> None:
        self.logger = get_logger(__name__)

    @staticmethod
    async def _ensure_row() -> None:
        """
        Гарантирует наличие базовой строки метрик (id=1).
        """
        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO metrics (id)
                VALUES (1)
                ON CONFLICT (id) DO NOTHING;
                """,
            )

    async def increment_generation_success(self) -> None:
        await self._ensure_row()
        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE metrics SET generations_success = generations_success + 1 WHERE id = 1;",
            )

    async def increment_generation_failed(self) -> None:
        await self._ensure_row()
        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE metrics SET generations_failed = generations_failed + 1 WHERE id = 1;",
            )

    async def increment_generation_retry(self) -> None:
        await self._ensure_row()
        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE metrics SET generations_retries = generations_retries + 1 WHERE id = 1;",
            )

    async def add_generation_time(self, seconds: float) -> None:
        await self._ensure_row()
        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE metrics SET generations_total_time = generations_total_time + $1 WHERE id = 1;",
                float(seconds),
            )

    async def increment_dispatch_success(self) -> None:
        await self._ensure_row()
        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE metrics SET dispatch_success = dispatch_success + 1 WHERE id = 1;",
            )

    async def increment_dispatch_failed(self) -> None:
        await self._ensure_row()
        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE metrics SET dispatch_failed = dispatch_failed + 1 WHERE id = 1;",
            )

    async def increment_circuit_breaker_trip(self) -> None:
        await self._ensure_row()
        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE metrics SET circuit_breaker_trips = circuit_breaker_trips + 1 WHERE id = 1;",
            )

    async def get_summary(self) -> dict[str, Any]:
        await self._ensure_row()
        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    generations_success,
                    generations_failed,
                    generations_retries,
                    generations_total_time,
                    dispatch_success,
                    dispatch_failed,
                    circuit_breaker_trips
                FROM metrics
                WHERE id = 1;
                """,
            )

        if row is None:  # pragma: no cover - защитный фоллбек
            return {
                "generations_total": 0,
                "generations_success": 0,
                "generations_failed": 0,
                "generations_retries": 0,
                "average_generation_time": "0.00s",
                "dispatches_success": 0,
                "dispatches_failed": 0,
                "circuit_breaker_trips": 0,
            }

        gen_success = int(row["generations_success"])
        gen_failed = int(row["generations_failed"])
        gen_retries = int(row["generations_retries"])
        total_time = float(row["generations_total_time"])
        disp_success = int(row["dispatch_success"])
        disp_failed = int(row["dispatch_failed"])
        trips = int(row["circuit_breaker_trips"])

        total_gen = gen_success + gen_failed
        avg_time = total_time / total_gen if total_gen else 0.0

        return {
            "generations_total": total_gen,
            "generations_success": gen_success,
            "generations_failed": gen_failed,
            "generations_retries": gen_retries,
            "average_generation_time": f"{avg_time:.2f}s",
            "dispatches_success": disp_success,
            "dispatches_failed": disp_failed,
            "circuit_breaker_trips": trips,
        }


async def get_daily_generation_stats(days: int = 7) -> list[dict[str, Any]]:
    """
    Возвращает агрегированную статистику генераций по дням за последние N дней.

    Для каждого дня рассчитываются:
    - количество успешных генераций;
    - средняя латентность (ms) по успешным генерациям.
    """
    pool = get_postgres_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                date_trunc('day', timestamp) AS day,
                COUNT(*) FILTER (
                    WHERE event_type = 'generation' AND status = 'ok'
                ) AS generations_ok,
                AVG(latency_ms) FILTER (
                    WHERE event_type = 'generation'
                      AND status = 'ok'
                      AND latency_ms IS NOT NULL
                ) AS avg_latency_ms
            FROM metrics_events
            WHERE timestamp >= NOW() - ($1 || ' days')::interval
            GROUP BY date_trunc('day', timestamp)
            ORDER BY day DESC;
            """,
            str(days),
        )

    result: list[dict[str, Any]] = []
    for row in rows:
        result.append(
            {
                "day": row["day"],
                "generations_ok": int(row["generations_ok"] or 0),
                "avg_latency_ms": float(row["avg_latency_ms"]) if row["avg_latency_ms"] is not None else None,
            },
        )
    return result


async def get_top_prompts(limit: int = 10) -> list[dict[str, Any]]:
    """
    Возвращает топ промптов по количеству успешных генераций.

    Args:
        limit: Максимальное количество строк в выдаче.
    """
    pool = get_postgres_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                prompt_hash,
                COUNT(*) FILTER (
                    WHERE event_type = 'generation' AND status = 'ok'
                ) AS generations_ok,
                AVG(latency_ms) FILTER (
                    WHERE event_type = 'generation'
                      AND status = 'ok'
                      AND latency_ms IS NOT NULL
                ) AS avg_latency_ms
            FROM metrics_events
            WHERE prompt_hash IS NOT NULL
            GROUP BY prompt_hash
            ORDER BY generations_ok DESC
            LIMIT $1;
            """,
            int(limit),
        )

    result: list[dict[str, Any]] = []
    for row in rows:
        result.append(
            {
                "prompt_hash": row["prompt_hash"],
                "generations_ok": int(row["generations_ok"] or 0),
                "avg_latency_ms": float(row["avg_latency_ms"]) if row["avg_latency_ms"] is not None else None,
            },
        )
    return result
