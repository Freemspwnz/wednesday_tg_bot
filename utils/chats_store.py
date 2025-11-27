"""
Хранилище чатов на базе PostgreSQL.

Ранее состояние хранилось в JSON-файле `data/chats.json`, теперь все данные
перенесены в таблицу `chats` (см. `utils.postgres_schema`).
"""

from __future__ import annotations

from typing import Any

from utils.logger import get_logger, log_all_methods
from utils.postgres_client import get_postgres_pool


@log_all_methods()
class ChatsStore:
    """
    Репозиторий для работы со списком чатов рассылки.

    Интерфейс совместим с предыдущей реализацией, но все операции выполняются
    через Postgres и являются асинхронными.
    """

    def __init__(self, storage_path: str | None = None) -> None:
        # Параметр storage_path оставлен для обратной совместимости и игнорируется.
        self.logger = get_logger(__name__)

    async def add_chat(self, chat_id: int, title: str | None = None) -> None:
        """
        Добавляет или обновляет чат в списке рассылки.
        """
        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO chats (chat_id, title)
                    VALUES ($1, COALESCE($2, ''))
                    ON CONFLICT (chat_id) DO UPDATE
                    SET title = EXCLUDED.title;
                    """,
                    int(chat_id),
                    title,
                )
                self.logger.info(f"Сохранён чат {chat_id} в Postgres")
            except Exception as exc:
                self.logger.error(f"Ошибка при добавлении чата {chat_id} в Postgres: {exc}")
                raise

    async def remove_chat(self, chat_id: int) -> None:
        """
        Удаляет чат из списка рассылки.
        """
        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            try:
                await conn.execute("DELETE FROM chats WHERE chat_id = $1;", int(chat_id))
                self.logger.info(f"Удалён чат {chat_id} из Postgres")
            except Exception as exc:
                self.logger.error(f"Ошибка при удалении чата {chat_id} из Postgres: {exc}")
                raise

    async def list_chat_ids(self) -> list[int]:
        """
        Возвращает список ID всех зарегистрированных чатов.
        """
        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            try:
                rows: list[tuple[Any]] = await conn.fetch("SELECT chat_id FROM chats ORDER BY chat_id;")
                return [int(row[0]) for row in rows]
            except Exception as exc:
                self.logger.error(f"Ошибка при чтении списка чатов из Postgres: {exc}")
                raise
