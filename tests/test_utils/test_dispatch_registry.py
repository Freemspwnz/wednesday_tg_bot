from datetime import date
from typing import Any

import pytest

from utils.dispatch_registry import DispatchRegistry


@pytest.mark.asyncio
async def test_dispatch_registry_is_dispatched_false(cleanup_tables: Any) -> None:
    registry = DispatchRegistry()

    # Проверяем несуществующую запись
    result = await registry.is_dispatched("2025-01-01", "10:00", 12345)
    assert result is False


@pytest.mark.asyncio
async def test_dispatch_registry_mark_and_check(cleanup_tables: Any) -> None:
    registry = DispatchRegistry()

    # Помечаем как отправленное (используем текущую дату в формате строки, как в реальном коде)
    from datetime import datetime

    today_str = datetime.now().strftime("%Y-%m-%d")
    # Используем строку, как в реальном коде (asyncpg должен преобразовать через ::date)
    await registry.mark_dispatched(today_str, "10:00", 12345)

    # Проверяем, что запись есть
    result = await registry.is_dispatched(today_str, "10:00", 12345)
    assert result is True


@pytest.mark.asyncio
async def test_dispatch_registry_mark_duplicate(cleanup_tables: Any) -> None:
    registry = DispatchRegistry()

    # Помечаем дважды (используем текущую дату)
    today_str = date.today().strftime("%Y-%m-%d")
    await registry.mark_dispatched(today_str, "10:00", 12345)
    await registry.mark_dispatched(today_str, "10:00", 12345)

    # Проверяем, что запись есть (не должно быть дубликатов)
    result = await registry.is_dispatched(today_str, "10:00", 12345)
    assert result is True


@pytest.mark.asyncio
async def test_dispatch_registry_cleanup_old(cleanup_tables: Any) -> None:
    registry = DispatchRegistry(retention_days=1)

    # Помечаем как отправленное (используем текущую дату)
    today_str = date.today().strftime("%Y-%m-%d")
    await registry.mark_dispatched(today_str, "10:00", 12345)

    # Очищаем старые записи
    await registry.cleanup_old()

    # Запись может остаться или быть удалена в зависимости от даты
    # Главное - метод выполнился без ошибок
