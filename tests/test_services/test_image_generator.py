import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from services.image_generator import ImageGenerator


@pytest.mark.asyncio
async def test_check_api_status_dry_run(monkeypatch):
    """Dry-run: проверяем, что возвращается ожидаемый статус без настоящих запросов."""

    class DummyResponse:
        def __init__(self, status=200, payload=None):
            self.status = status
            self._payload = payload or [{"id": "p1", "name": "Model One"}]

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return False

        async def json(self):
            return self._payload

    class DummySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return False

        def get(self, *args, **kwargs):
            return DummyResponse()

    monkeypatch.setattr(aiohttp, "ClientSession", lambda *args, **kwargs: DummySession())

    generator = ImageGenerator()
    ok, message, models, current = await generator.check_api_status()

    assert ok is True
    assert "доступен" in message
    assert models
    assert current == (None, None)


def test_save_image_locally_success(tmp_path):
    generator = ImageGenerator()
    data = b"fake-image"

    saved = generator.save_image_locally(data, folder=str(tmp_path), prefix="frog", max_files=1)

    assert saved
    saved_path = Path(saved)
    assert saved_path.exists()
    assert saved_path.read_bytes() == data


def test_save_image_locally_handles_error(monkeypatch):
    generator = ImageGenerator()
    target_folder = "/tmp/forbidden"

    def fail_write_bytes(self, data):
        raise OSError("write error")

    monkeypatch.setattr("services.image_generator.Path.write_bytes", fail_write_bytes, raising=False)

    assert generator.save_image_locally(b"data", folder=target_folder) == ""


@pytest.mark.asyncio
async def test_generate_frog_image_success(monkeypatch):
    generator = ImageGenerator()
    generator.gigachat_enabled = False

    async def fake_generate_prompt():
        return "frog prompt"

    async def fake_generate_image(prompt):
        return b"img"

    generator._generate_prompt = AsyncMock(side_effect=fake_generate_prompt)  # type: ignore
    generator._get_fallback_prompt = MagicMock(return_value="fallback prompt")  # type: ignore
    generator._generate_image = AsyncMock(side_effect=fake_generate_image)  # type: ignore

    result = await generator.generate_frog_image()

    assert result is not None
    image, caption = result
    assert image == b"img"
    assert caption in generator.captions


@pytest.mark.asyncio
async def test_generate_frog_image_network_error(monkeypatch):
    generator = ImageGenerator()
    generator.gigachat_enabled = False

    generator._generate_prompt = AsyncMock(return_value="frog prompt")  # type: ignore
    generator._generate_image = AsyncMock(side_effect=Exception("network"))  # type: ignore
    generator.max_retries = 1

    result = await generator.generate_frog_image()

    assert result is None

