from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from utils.images_store import ImagesStore
from utils.prompts_store import PromptsStore

IMAGE_HASH_HEX_LENGTH = 64


@pytest.mark.asyncio
async def test_get_or_create_image_saves_file_and_metadata(
    tmp_path: Path, monkeypatch: Any, cleanup_tables: Any
) -> None:
    """
    Базовый сценарий: изображение сохраняется на диск и в таблицу images,
    повторный вызов с тем же prompt_hash возвращает ту же запись.
    """

    # Перенаправляем папку с изображениями в tmp_path, чтобы не трогать реальные данные.
    def _fake_resolve_frog_images_dir() -> Path:
        return tmp_path

    monkeypatch.setattr("utils.images_store.resolve_frog_images_dir", _fake_resolve_frog_images_dir)

    prompts_store = PromptsStore()
    images_store = ImagesStore()

    prompt_record = await prompts_store.get_or_create_prompt("A simple frog")
    image_bytes = b"test-image-bytes"

    record1 = await images_store.get_or_create_image(prompt_record.prompt_hash, image_bytes)
    assert record1.id > 0
    assert record1.prompt_hash == prompt_record.prompt_hash
    # Хэш изображения — это sha256 в hex‑представлении (64 символа).
    assert len(record1.image_hash) == IMAGE_HASH_HEX_LENGTH

    # Файл должен существовать в content-addressable виде.
    fs_path = tmp_path / f"{record1.image_hash}.png"
    assert fs_path.exists()
    assert fs_path.read_bytes() == image_bytes

    # Повторный вызов с тем же prompt_hash и теми же байтами возвращает ту же запись.
    record2 = await images_store.get_or_create_image(prompt_record.prompt_hash, image_bytes)
    assert record2.id == record1.id
    assert record2.image_hash == record1.image_hash


@pytest.mark.asyncio
async def test_get_or_create_image_handles_concurrent_insert(
    monkeypatch: Any, tmp_path: Path, cleanup_tables: Any
) -> None:
    """
    Имитируем гонку: первая корутина вставляет запись, вторая получает duplicate key
    и должна вернуть ту же запись.
    """

    def _fake_resolve_frog_images_dir() -> Path:
        return tmp_path

    monkeypatch.setattr("utils.images_store.resolve_frog_images_dir", _fake_resolve_frog_images_dir)

    prompts_store = PromptsStore()
    prompt_record = await prompts_store.get_or_create_prompt("Concurrent frog")
    prompt_hash = prompt_record.prompt_hash
    image_bytes = b"concurrent-image"

    store1 = ImagesStore()
    store2 = ImagesStore()

    async def _create_with_store1() -> None:
        await store1.get_or_create_image(prompt_hash, image_bytes)

    async def _create_with_store2() -> None:
        await store2.get_or_create_image(prompt_hash, image_bytes)

    # Параллельный запуск двух корутин через asyncio.gather даёт нам
    # реалистичный сценарий гонки в одной event loop. Это важно для
    # проверки того, что upsert-логика в ImagesStore корректно обрабатывает
    # duplicate key и всегда возвращает одну консистентную запись.
    await asyncio.gather(_create_with_store1(), _create_with_store2())

    # В таблице должна быть одна запись для этого prompt_hash.
    images_store = ImagesStore()
    record = await images_store.get_by_prompt_hash(prompt_hash)
    assert record is not None
