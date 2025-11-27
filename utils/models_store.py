"""
Хранилище текущих моделей на базе PostgreSQL.

Ранее состояние хранилось в JSON-файле `data/models.json`, теперь используется
пара таблиц `models_kandinsky` и `models_gigachat`.
"""

from __future__ import annotations

from typing import Any

from utils.logger import get_logger, log_all_methods
from utils.postgres_client import get_postgres_pool


@log_all_methods()
class ModelsStore:
    """
    Репозиторий настроек моделей Kandinsky и GigaChat.

    Все методы асинхронные и используют Postgres в качестве единственного источника истины.
    """

    def __init__(self, storage_path: str | None = None) -> None:
        self.logger = get_logger(__name__)

    @staticmethod
    async def _ensure_rows() -> None:
        """
        Гарантирует наличие базовых строк (id=1) в таблицах моделей.
        """
        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO models_kandinsky (id) VALUES (1) ON CONFLICT (id) DO NOTHING;",
            )
            await conn.execute(
                "INSERT INTO models_gigachat (id) VALUES (1) ON CONFLICT (id) DO NOTHING;",
            )

    async def set_kandinsky_model(self, pipeline_id: str, pipeline_name: str) -> None:
        """Устанавливает текущую модель Kandinsky."""
        await self._ensure_rows()
        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE models_kandinsky
                SET current_pipeline_id = $1,
                    current_pipeline_name = $2
                WHERE id = 1;
                """,
                pipeline_id,
                pipeline_name,
            )

    async def get_kandinsky_model(self) -> tuple[str | None, str | None]:
        """Возвращает текущую модель Kandinsky (pipeline_id, pipeline_name)."""
        await self._ensure_rows()
        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT current_pipeline_id, current_pipeline_name
                FROM models_kandinsky
                WHERE id = 1;
                """,
            )
        if row is None:  # pragma: no cover - защитный фоллбек
            return None, None
        return row["current_pipeline_id"], row["current_pipeline_name"]

    async def set_gigachat_model(self, model_name: str) -> None:
        """Устанавливает текущую модель GigaChat."""
        await self._ensure_rows()
        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE models_gigachat SET current_model = $1 WHERE id = 1;",
                model_name,
            )

    async def get_gigachat_model(self) -> str | None:
        """Возвращает текущую модель GigaChat."""
        await self._ensure_rows()
        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT current_model FROM models_gigachat WHERE id = 1;",
            )
        model = row["current_model"] if row is not None else None
        return str(model) if isinstance(model, str) else None

    async def set_kandinsky_available_models(self, models: list[dict[str, Any]] | list[str]) -> None:
        """
        Сохраняет список доступных моделей Kandinsky.

        Args:
            models: Список моделей (словари с полями 'id' и 'name' или строки)
        """
        await self._ensure_rows()
        # Сохраняем модели как список строк в формате "Name (ID: xxx)" для совместимости
        formatted_models: list[str] = []
        for model in models:
            if isinstance(model, dict):
                model_id: str = str(model.get("id", ""))
                model_name: str = str(model.get("name", "Unknown"))
                formatted_models.append(f"{model_name} (ID: {model_id})")
            elif isinstance(model, str):
                formatted_models.append(model)

        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE models_kandinsky SET available_models = $1::text[] WHERE id = 1;",
                formatted_models,
            )
        try:
            self.logger.info(f"Сохранено {len(formatted_models)} моделей Kandinsky в Postgres")
        except Exception:  # pragma: no cover - логирование не критично
            pass

    async def get_kandinsky_available_models(self) -> list[str]:
        """
        Возвращает список доступных моделей Kandinsky.

        Returns:
            Список строк моделей в формате "Name (ID: xxx)"
        """
        await self._ensure_rows()
        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT available_models FROM models_kandinsky WHERE id = 1;",
            )
        if row is None:
            return []
        models = row["available_models"] or []
        return list(models)

    async def set_gigachat_available_models(self, models: list[str]) -> None:
        """
        Сохраняет список доступных моделей GigaChat.

        Args:
            models: Список названий моделей
        """
        await self._ensure_rows()
        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE models_gigachat SET available_models = $1::text[] WHERE id = 1;",
                models,
            )
        try:
            self.logger.info(f"Сохранено {len(models)} моделей GigaChat в Postgres")
        except Exception:  # pragma: no cover
            pass

    async def get_gigachat_available_models(self) -> list[str]:
        """
        Возвращает список доступных моделей GigaChat.

        Returns:
            Список названий моделей
        """
        await self._ensure_rows()
        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT available_models FROM models_gigachat WHERE id = 1;",
            )
        if row is None:
            return []
        models = row["available_models"] or []
        return list(models)
