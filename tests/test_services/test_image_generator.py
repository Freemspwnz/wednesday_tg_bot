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


def test_get_random_caption() -> None:
    generator = ImageGenerator()
    caption = generator.get_random_caption()
    assert caption
    assert isinstance(caption, str)
    assert caption in generator.captions


def test_get_fallback_prompt() -> None:
    from services.image_generator import ImageGenerator

    prompt = ImageGenerator._get_fallback_prompt()
    assert prompt
    assert isinstance(prompt, str)
    assert len(prompt) > 0


def test_get_random_saved_image_no_files(tmp_path: Path) -> None:
    generator = ImageGenerator()
    result = generator.get_random_saved_image(folder=str(tmp_path))
    assert result is None


def test_get_random_saved_image_with_files(tmp_path: Path) -> None:
    generator = ImageGenerator()
    # Создаём тестовые файлы изображений
    (tmp_path / "frog_20251101_120000.png").write_bytes(b"fake image 1")
    (tmp_path / "frog_20251102_120000.png").write_bytes(b"fake image 2")

    result = generator.get_random_saved_image(folder=str(tmp_path))
    assert result is not None
    image_data, caption = result
    assert image_data in {b"fake image 1", b"fake image 2"}
    assert isinstance(caption, str)


@pytest.mark.asyncio
async def test_set_kandinsky_model_success(monkeypatch: Any, cleanup_tables: Any) -> None:
    generator = ImageGenerator()

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

    success, message = await generator.set_kandinsky_model("p1")
    assert success is True
    assert "установлена" in message.lower() or "успешно" in message.lower()


@pytest.mark.asyncio
async def test_set_kandinsky_model_not_found(monkeypatch: Any) -> None:
    generator = ImageGenerator()

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

    success, message = await generator.set_kandinsky_model("nonexistent")
    assert success is False
    assert "не найдена" in message.lower() or "не найдено" in message.lower()


def test_get_auth_headers() -> None:
    generator = ImageGenerator()
    headers = generator._get_auth_headers()
    assert "X-Key" in headers
    assert "X-Secret" in headers
    assert isinstance(headers["X-Key"], str)
    assert isinstance(headers["X-Secret"], str)
