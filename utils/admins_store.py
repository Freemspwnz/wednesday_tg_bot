"""
Хранилище администраторов на базе PostgreSQL.

Ранее состояние хранилось в JSON-файле `data/admins.json`, теперь все данные
перенесены в таблицу `admins` (см. `utils.postgres_schema`).
"""

from __future__ import annotations

from utils.config import config
from utils.logger import get_logger, log_all_methods
from utils.postgres_client import get_postgres_pool


@log_all_methods()
class AdminsStore:
    """
    Репозиторий для управления списком администраторов.

    Главный админ по-прежнему задаётся через переменную окружения ADMIN_CHAT_ID
    и всегда имеет права независимо от содержимого таблицы.
    """

    def __init__(self, storage_path: str | None = None) -> None:
        # storage_path оставлен для обратной совместимости и игнорируется.
        self.logger = get_logger(__name__)

    async def is_admin(self, user_id: int) -> bool:
        """Проверяет, является ли пользователь администратором."""
        # Главный админ из .env всегда имеет права
        main_admin = config.admin_chat_id
        if main_admin and int(main_admin) == user_id:
            return True

        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            try:
                row = await conn.fetchrow("SELECT 1 FROM admins WHERE user_id = $1;", int(user_id))
            except Exception as exc:
                self.logger.error(f"Ошибка при проверке прав админа {user_id} в Postgres: {exc}")
                raise
        return row is not None

    async def add_admin(self, user_id: int) -> bool:
        """Добавляет администратора. Возвращает True если добавлен, False если уже был."""
        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            try:
                result = await conn.execute(
                    """
                    INSERT INTO admins (user_id)
                    VALUES ($1)
                    ON CONFLICT (user_id) DO NOTHING;
                    """,
                    int(user_id),
                )
                # asyncpg возвращает строку вида "INSERT 0 1" / "INSERT 0 0"
                inserted = str(result).endswith("1")
                if inserted:
                    self.logger.info(f"Добавлен администратор {user_id} в Postgres")
                else:
                    self.logger.info(f"Администратор {user_id} уже существует в Postgres")
                return inserted
            except Exception as exc:
                self.logger.error(f"Ошибка при добавлении админа {user_id} в Postgres: {exc}")
                raise

    async def remove_admin(self, user_id: int) -> bool:
        """Удаляет администратора. Возвращает True если удален, False если не был админом."""
        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            try:
                result = await conn.execute("DELETE FROM admins WHERE user_id = $1;", int(user_id))
                deleted = str(result).endswith("1")
                if deleted:
                    self.logger.info(f"Администратор {user_id} удалён из Postgres")
                else:
                    self.logger.info(f"Администратор {user_id} не найден в Postgres")
                return deleted
            except Exception as exc:
                self.logger.error(f"Ошибка при удалении админа {user_id} из Postgres: {exc}")
                raise

    async def list_admins(self) -> list[int]:
        """Возвращает список всех админов (исключая главного админа из .env)."""
        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            try:
                rows = await conn.fetch("SELECT user_id FROM admins ORDER BY user_id;")
                return [int(row["user_id"]) for row in rows]
            except Exception as exc:
                self.logger.error(f"Ошибка при получении списка админов из Postgres: {exc}")
                raise

    async def list_all_admins(self) -> list[int]:
        """Возвращает список всех админов, включая главного из .env."""
        admin_ids = await self.list_admins()
        main_admin = config.admin_chat_id
        if main_admin:
            main_id = int(main_admin)
            if main_id not in admin_ids:
                admin_ids.insert(0, main_id)
        return admin_ids
