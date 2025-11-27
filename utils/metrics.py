"""
Система метрик для отслеживания производительности на базе PostgreSQL.

Ранее данные хранились в JSON-файле `data/metrics.json`, теперь используется
таблица `metrics` (см. `utils.postgres_schema`).
"""

from __future__ import annotations

from typing import Any

from utils.logger import get_logger, log_all_methods
from utils.postgres_client import get_postgres_pool


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
