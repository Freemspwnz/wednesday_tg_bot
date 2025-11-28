from typing import Any

import pytest

from utils.admins_store import AdminsStore


@pytest.mark.asyncio
async def test_admins_store_add_admin(cleanup_tables: Any) -> None:
    store = AdminsStore()

    # Добавляем админа
    result = await store.add_admin(12345)
    assert result is True

    # Проверяем, что админ добавлен
    assert await store.is_admin(12345) is True


@pytest.mark.asyncio
async def test_admins_store_add_admin_duplicate(cleanup_tables: Any) -> None:
    store = AdminsStore()

    # Добавляем админа дважды
    result1 = await store.add_admin(12345)
    result2 = await store.add_admin(12345)

    assert result1 is True
    assert result2 is False  # Уже был админом


@pytest.mark.asyncio
async def test_admins_store_remove_admin(cleanup_tables: Any) -> None:
    store = AdminsStore()

    # Добавляем админа
    await store.add_admin(12345)
    assert await store.is_admin(12345) is True

    # Удаляем админа
    result = await store.remove_admin(12345)
    assert result is True
    assert await store.is_admin(12345) is False


@pytest.mark.asyncio
async def test_admins_store_remove_admin_not_exists(cleanup_tables: Any) -> None:
    store = AdminsStore()

    # Пытаемся удалить несуществующего админа
    result = await store.remove_admin(99999)
    assert result is False


@pytest.mark.asyncio
async def test_admins_store_list_admins(cleanup_tables: Any) -> None:
    store = AdminsStore()

    # Добавляем нескольких админов
    await store.add_admin(11111)
    await store.add_admin(22222)
    await store.add_admin(33333)

    # Получаем список
    admins = await store.list_admins()
    assert 11111 in admins  # noqa: PLR2004
    assert 22222 in admins  # noqa: PLR2004
    assert 33333 in admins  # noqa: PLR2004
    assert len(admins) == 3  # noqa: PLR2004


@pytest.mark.asyncio
async def test_admins_store_list_all_admins(cleanup_tables: Any) -> None:
    store = AdminsStore()

    # Добавляем админов
    await store.add_admin(11111)
    await store.add_admin(22222)

    # Получаем полный список (включая главного из config)
    all_admins = await store.list_all_admins()
    assert len(all_admins) >= 2  # noqa: PLR2004
    assert 11111 in all_admins  # noqa: PLR2004
    assert 22222 in all_admins  # noqa: PLR2004
