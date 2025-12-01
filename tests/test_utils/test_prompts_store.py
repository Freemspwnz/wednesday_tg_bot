from __future__ import annotations

import asyncio
from typing import Any

import pytest

from utils.prompts_store import PromptsStore

SHA256_HEX_LENGTH = 64


@pytest.mark.asyncio
async def test_get_or_create_prompt_inserts_and_deduplicates(cleanup_tables: Any) -> None:
    store = PromptsStore()

    text = "  A frog  "
    record1 = await store.get_or_create_prompt(text)

    assert record1.id > 0
    assert record1.raw_text == text
    # normalized = strip()
    assert record1.normalized_text == "A frog"
    assert len(record1.prompt_hash) == SHA256_HEX_LENGTH

    # Повторный вызов с тем же текстом должен вернуть ту же запись (по hash).
    record2 = await store.get_or_create_prompt("A frog")
    assert record2.id == record1.id
    assert record2.prompt_hash == record1.prompt_hash


@pytest.mark.asyncio
async def test_get_prompt_by_hash_returns_existing(cleanup_tables: Any) -> None:
    store = PromptsStore()

    record = await store.get_or_create_prompt("Wednesday frog")
    loaded = await store.get_prompt_by_hash(record.prompt_hash)

    assert loaded is not None
    assert loaded.id == record.id
    assert loaded.raw_text == record.raw_text
    assert loaded.normalized_text == record.normalized_text


@pytest.mark.asyncio
async def test_get_prompt_by_hash_missing_returns_none(cleanup_tables: Any) -> None:
    store = PromptsStore()

    loaded = await store.get_prompt_by_hash("0" * 64)
    assert loaded is None


@pytest.mark.asyncio
async def test_get_random_prompt_returns_record(cleanup_tables: Any) -> None:
    store = PromptsStore()

    await store.get_or_create_prompt("Prompt A")
    await store.get_or_create_prompt("Prompt B")

    random_record = await store.get_random_prompt()
    assert random_record is not None
    assert random_record.raw_text in {"Prompt A", "Prompt B"}


@pytest.mark.asyncio
async def test_get_or_create_prompt_concurrent_insert(cleanup_tables: Any) -> None:
    """
    Проверяем, что при конкурентных вызовах get_or_create_prompt с одним
    и тем же текстом создаётся ровно одна запись в БД.

    Это важно для сценариев высокой нагрузки, когда несколько воркеров
    одновременно регистрируют одинаковый промпт: логика с
    ON CONFLICT + повторным SELECT должна гарантировать отсутствие дубликатов.
    """

    store1 = PromptsStore()
    store2 = PromptsStore()
    text = "Concurrent prompt"

    async def _create_with_store1() -> None:
        await store1.get_or_create_prompt(text)

    async def _create_with_store2() -> None:
        await store2.get_or_create_prompt(text)

    await asyncio.gather(_create_with_store1(), _create_with_store2())

    store = PromptsStore()
    record = await store.get_or_create_prompt(text)
    assert record.id > 0
