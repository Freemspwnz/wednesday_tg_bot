"""
Реестр отправленных сообщений по тайм-слотам и чатам на базе PostgreSQL.

Ранее данные хранились в JSON-файле `data/dispatch_registry.json`, теперь
используется таблица `dispatch_registry`.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from utils.logger import get_logger, log_all_methods
from utils.postgres_client import get_postgres_pool


@log_all_methods()
class DispatchRegistry:
    def __init__(self, storage_path: str | None = None, retention_days: int = 7) -> None:
        self.logger = get_logger(__name__)
        self.retention_days = retention_days

    @staticmethod
    def _key(slot_date: str, slot_time: str, chat_id: int) -> str:
        return f"{slot_date}_{slot_time}:{chat_id}"

    async def is_dispatched(self, slot_date: str, slot_time: str, chat_id: int) -> bool:
        """
        Проверяет, было ли уже отправлено сообщение в указанный слот и чат.
        """
        pool = get_postgres_pool()
        key = self._key(slot_date, slot_time, chat_id)
        async with pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    "SELECT 1 FROM dispatch_registry WHERE key = $1;",
                    key,
                )
                return row is not None
            except Exception as exc:
                self.logger.error(
                    f"Ошибка при проверке dispatch_registry (key={key}) в Postgres: {exc}",
                )
                raise

    async def mark_dispatched(self, slot_date: str, slot_time: str, chat_id: int) -> None:
        """
        Помечает сочетание (дата, время, чат) как уже отправленное.
        """
        pool = get_postgres_pool()
        key = self._key(slot_date, slot_time, chat_id)
        async with pool.acquire() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO dispatch_registry (key, slot_date, slot_time, chat_id, created_at)
                    VALUES ($1, $2::date, $3, $4, NOW())
                    ON CONFLICT (key) DO NOTHING;
                    """,
                    key,
                    slot_date,
                    slot_time,
                    int(chat_id),
                )
            except Exception as exc:
                self.logger.error(
                    f"Ошибка при записи dispatch_registry (key={key}) в Postgres: {exc}",
                )
                raise

    async def cleanup_old(self) -> None:
        """
        Удаляет старые записи реестра старше `retention_days`.
        """
        cutoff_dt = datetime.utcnow() - timedelta(days=self.retention_days)
        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            try:
                await conn.execute(
                    "DELETE FROM dispatch_registry WHERE created_at < $1;",
                    cutoff_dt,
                )
                message = (
                    "Очистка dispatch_registry старше "
                    f"{self.retention_days} дней выполнена "
                    f"(cutoff={cutoff_dt.isoformat()})"
                )
                self.logger.info(message)
            except Exception as exc:
                self.logger.error(f"Ошибка при очистке dispatch_registry в Postgres: {exc}")
                raise
