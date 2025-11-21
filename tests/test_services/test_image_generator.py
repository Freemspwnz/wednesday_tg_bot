from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from services.image_generator import ImageGenerator


@pytest.mark.asyncio
async def test_check_api_status_dry_run(monkeypatch: Any) -> None:
    """Dry-run: проверяем, что возвращается ожидаемый статус без настоящих запросов."""

    class DummyResponse:
        def __init__(self, status: int = 200, payload: Any = None) -> None:
            self.status = status
            self._payload: Any = payload or [{"id": "p1", "name": "Model One"}]

        async def __aenter__(self) -> "DummyResponse":
            return self

        async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
            return False

        async def json(self) -> Any:
            return self._payload

    class DummySession:
        async def __aenter__(self) -> "DummySession":
            return self

        async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
            return False

        def get(self, *args: Any, **kwargs: Any) -> DummyResponse:
            return DummyResponse()

    monkeypatch.setattr(aiohttp, "ClientSession", lambda *args, **kwargs: DummySession())

    generator = ImageGenerator()
    ok, message, models, current = await generator.check_api_status()

    assert ok is True
    assert "доступен" in message
    assert models
    assert current == (None, None)


def test_save_image_locally_success(tmp_path: Path) -> None:
    generator = ImageGenerator()
    data = b"fake-image"

    saved = generator.save_image_locally(data, folder=str(tmp_path), prefix="frog", max_files=1)

    assert saved
    saved_path = Path(saved)
    assert saved_path.exists()
    assert saved_path.read_bytes() == data


def test_save_image_locally_handles_error(monkeypatch: Any) -> None:
    generator = ImageGenerator()
    target_folder = "/tmp/forbidden"

    def fail_write_bytes(self: Any, data: bytes) -> None:
        raise OSError("write error")

    monkeypatch.setattr("services.image_generator.Path.write_bytes", fail_write_bytes, raising=False)

    assert generator.save_image_locally(b"data", folder=target_folder) == ""


@pytest.mark.asyncio
async def test_generate_frog_image_success(monkeypatch: Any) -> None:
    generator = ImageGenerator()
    generator.gigachat_enabled = False

    def fake_generate_prompt() -> str:
        return "frog prompt"

    def fake_generate_image(prompt: str) -> bytes:
        return b"img"

    monkeypatch.setattr(generator, "_generate_prompt", AsyncMock(side_effect=fake_generate_prompt))
    monkeypatch.setattr(generator, "_get_fallback_prompt", MagicMock(return_value="fallback prompt"))
    monkeypatch.setattr(generator, "_generate_image", AsyncMock(side_effect=fake_generate_image))

    result = await generator.generate_frog_image()

    assert result is not None
    image, caption = result
    assert image == b"img"
    assert caption in generator.captions


@pytest.mark.asyncio
async def test_generate_frog_image_network_error(monkeypatch: Any) -> None:
    generator = ImageGenerator()
    generator.gigachat_enabled = False

    monkeypatch.setattr(generator, "_generate_prompt", AsyncMock(return_value="frog prompt"))
    monkeypatch.setattr(generator, "_generate_image", AsyncMock(side_effect=Exception("network")))

    result = await generator.generate_frog_image()

    assert result is None
