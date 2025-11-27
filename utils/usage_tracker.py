"""
Трекер использования генераций изображений по месяцам на базе PostgreSQL.

Ранее статистика хранилась в JSON-файле `data/usage_stats.json`. Теперь:
- помесячные значения лежат в таблице `usage_stats`;
- настройки квот — в таблице `usage_settings` (единая строка id=1).
"""

from __future__ import annotations

from datetime import datetime

from utils.logger import get_logger, log_all_methods
from utils.postgres_client import get_postgres_pool


@log_all_methods()
class UsageTracker:
    """
    Учет количества генераций изображений по месяцам.

    Вся статистика хранится в Postgres и доступна через асинхронные методы.
    """

    def __init__(
        self,
        storage_path: str | None = None,
        monthly_quota: int = 100,
        frog_threshold: int = 70,
    ) -> None:
        self.logger = get_logger(__name__)
        self.monthly_quota = int(monthly_quota)
        self.frog_threshold = int(frog_threshold)

    @staticmethod
    def _month_key(dt: datetime) -> str:
        return dt.strftime("%Y-%m")

    async def _ensure_settings_row(self) -> None:
        """
        Гарантирует наличие строки настроек (id=1) с актуальными значениями квот.
        """
        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO usage_settings (id, monthly_quota, frog_threshold)
                VALUES (1, $1, $2)
                ON CONFLICT (id) DO UPDATE
                SET monthly_quota = EXCLUDED.monthly_quota,
                    frog_threshold = EXCLUDED.frog_threshold;
                """,
                int(self.monthly_quota),
                int(self.frog_threshold),
            )

    async def increment(self, count: int = 1, when: datetime | None = None) -> int:
        """
        Увеличивает счётчик генераций за месяц и возвращает новое значение.
        """
        await self._ensure_settings_row()
        dt = when or datetime.utcnow()
        key = self._month_key(dt)
        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT count FROM usage_stats WHERE month = $1;",
                key,
            )
            current = int(row["count"]) if row is not None else 0
            new_value = current + int(count)
            await conn.execute(
                """
                INSERT INTO usage_stats (month, count)
                VALUES ($1, $2)
                ON CONFLICT (month) DO UPDATE
                SET count = EXCLUDED.count;
                """,
                key,
                new_value,
            )
        return new_value

    async def get_month_total(self, when: datetime | None = None) -> int:
        """
        Возвращает общее количество генераций за месяц.
        """
        await self._ensure_settings_row()
        dt = when or datetime.utcnow()
        key = self._month_key(dt)
        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT count FROM usage_stats WHERE month = $1;",
                key,
            )
        return int(row["count"]) if row is not None else 0

    async def _load_settings(self) -> None:
        """
        Обновляет значения квот из таблицы `usage_settings`.
        """
        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT monthly_quota, frog_threshold FROM usage_settings WHERE id = 1;",
            )
        if row is not None:
            self.monthly_quota = int(row["monthly_quota"])
            self.frog_threshold = int(row["frog_threshold"])

    async def can_use_frog(self, when: datetime | None = None) -> bool:
        """
        Проверяет, не превышен ли порог ручных /frog для месяца.
        """
        await self._ensure_settings_row()
        await self._load_settings()
        total = await self.get_month_total(when)
        return total < self.frog_threshold

    async def get_limits_info(self, when: datetime | None = None) -> tuple[int, int, int]:
        """
        Возвращает кортеж (total, frog_threshold, monthly_quota) для текущего месяца.
        """
        await self._ensure_settings_row()
        await self._load_settings()
        total = await self.get_month_total(when)
        return total, self.frog_threshold, self.monthly_quota

    async def set_month_total(self, total: int, when: datetime | None = None) -> int:
        """
        Устанавливает текущее значение использования за месяц в абсолютном виде.
        Возвращает установленное значение.
        """
        await self._ensure_settings_row()
        dt = when or datetime.utcnow()
        key = self._month_key(dt)
        value = int(total)
        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO usage_stats (month, count)
                VALUES ($1, $2)
                ON CONFLICT (month) DO UPDATE
                SET count = EXCLUDED.count;
                """,
                key,
                value,
            )
        return value

    async def set_frog_threshold(self, threshold: int) -> int:
        """
        Устанавливает порог ручных генераций (/frog) на текущий месяц.
        Порог ограничивается диапазоном [0, monthly_quota]. Возвращает установленное значение.
        """
        await self._ensure_settings_row()
        threshold = max(int(threshold), 0)
        threshold = min(threshold, self.monthly_quota)
        self.frog_threshold = threshold

        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE usage_settings SET frog_threshold = $1 WHERE id = 1;",
                int(self.frog_threshold),
            )
        return self.frog_threshold
