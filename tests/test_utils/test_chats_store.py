from typing import Any

import pytest

from utils.chats_store import ChatsStore


@pytest.mark.asyncio
async def test_chats_store_add_chat(cleanup_tables: Any) -> None:
    store = ChatsStore()

    await store.add_chat(12345, "Test Chat")

    chat_ids = await store.list_chat_ids()
    assert 12345 in chat_ids  # noqa: PLR2004  # noqa: PLR2004


@pytest.mark.asyncio
async def test_chats_store_remove_chat(cleanup_tables: Any) -> None:
    store = ChatsStore()

    await store.add_chat(12345, "Test Chat")
    await store.remove_chat(12345)

    chat_ids = await store.list_chat_ids()
    assert 12345 not in chat_ids  # noqa: PLR2004  # noqa: PLR2004


@pytest.mark.asyncio
async def test_chats_store_list_chat_ids(cleanup_tables: Any) -> None:
    store = ChatsStore()

    await store.add_chat(11111, "Chat 1")
    await store.add_chat(22222, "Chat 2")
    await store.add_chat(33333, "Chat 3")

    chat_ids = await store.list_chat_ids()
    assert len(chat_ids) == 3  # noqa: PLR2004
    assert 11111 in chat_ids  # noqa: PLR2004
    assert 22222 in chat_ids  # noqa: PLR2004
    assert 33333 in chat_ids  # noqa: PLR2004


@pytest.mark.asyncio
async def test_chats_store_list_chat_ids_empty(cleanup_tables: Any) -> None:
    store = ChatsStore()

    chat_ids = await store.list_chat_ids()
    assert chat_ids == []
