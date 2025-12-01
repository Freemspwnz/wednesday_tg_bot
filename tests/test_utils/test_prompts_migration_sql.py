from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from utils.postgres_client import get_postgres_pool

SQL_DIR = Path("docs/sql")


@pytest.mark.asyncio
async def test_prompts_migration_up_and_down_applies_successfully(cleanup_tables: Any) -> None:
    """
    Проверяем, что SQL-миграции для таблицы prompts применяются и откатываются без ошибок.
    """

    up_path = SQL_DIR / "001_add_prompts_table.sql"
    down_path = SQL_DIR / "001_add_prompts_table_down.sql"

    assert up_path.exists(), "Файл миграции 001_add_prompts_table.sql должен существовать"
    assert down_path.exists(), "Файл отката 001_add_prompts_table_down.sql должен существовать"

    up_sql = up_path.read_text(encoding="utf-8")
    down_sql = down_path.read_text(encoding="utf-8")

    pool = get_postgres_pool()
    async with pool.acquire() as conn:
        # Начинаем с чистого состояния: удаляем таблицу, если она уже есть.
        await conn.execute("DROP TABLE IF EXISTS prompts CASCADE;")

        # Применяем миграцию (up)
        await conn.execute(up_sql)

        # Проверяем, что таблица существует
        exists_row = await conn.fetchrow(
            "SELECT to_regclass('public.prompts') IS NOT NULL AS exists_flag;",
        )
        assert exists_row is not None
        assert bool(exists_row["exists_flag"]) is True

        # Пробуем сделать простую вставку
        await conn.execute(
            """
            INSERT INTO prompts (raw_text, normalized_text, prompt_hash)
            VALUES ($1, $2, $3)
            ON CONFLICT (prompt_hash) DO NOTHING;
            """,
            "raw text",
            "raw text",
            "0" * 64,
        )

        # Откатываем миграцию (down)
        await conn.execute(down_sql)

        # Проверяем, что таблица удалена
        exists_row_after = await conn.fetchrow(
            "SELECT to_regclass('public.prompts') IS NOT NULL AS exists_flag;",
        )
        # to_regclass возвращает NULL, поэтому exists_flag должен быть False/NULL
        assert exists_row_after is not None
        assert bool(exists_row_after["exists_flag"]) is False
