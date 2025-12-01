from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from services.prompt_generator import GigaChatClient, PromptStorage


@pytest.fixture
def client(monkeypatch: Any) -> GigaChatClient:
    # Ускоряем генерацию uuid и времени
    monkeypatch.setattr("uuid.uuid4", lambda: "uuid")
    client = GigaChatClient()
    return client


def test_get_access_token_success(client: GigaChatClient, monkeypatch: Any) -> None:
    response = MagicMock(status_code=200)
    response.json.return_value = {"access_token": "abc123", "expires_in": 1800}
    mock_post = MagicMock(return_value=response)
    monkeypatch.setattr(client.session, "post", mock_post)

    token = client.get_access_token()

    assert token == "abc123"
    mock_post.assert_called_once()

    # Проверяем, что повторный вызов использует кэш
    mock_post.reset_mock()
    cached = client.get_access_token()
    assert cached == "abc123"
    # После reset_mock нужно проверить, что метод не был вызван снова
    # Но так как используется кэш, post не должен вызываться
    assert mock_post.call_count == 0


def test_get_access_token_bad_status(client: GigaChatClient, monkeypatch: Any) -> None:
    response = MagicMock(status_code=500, text="error")
    mock_post = MagicMock(return_value=response)
    monkeypatch.setattr(client.session, "post", mock_post)

    assert client.get_access_token() is None


def test_get_access_token_timeout(client: GigaChatClient, monkeypatch: Any) -> None:
    mock_post = MagicMock(side_effect=requests.exceptions.Timeout("boom"))
    monkeypatch.setattr(client.session, "post", mock_post)

    assert client.get_access_token() is None


def test_generate_prompt_success(client: GigaChatClient, monkeypatch: Any) -> None:
    monkeypatch.setattr(client, "get_access_token", MagicMock(return_value="token"))
    payload = {
        "choices": [
            {"message": {"content": '```Prompt: "A frog"```'}},
        ],
    }
    response = MagicMock(status_code=200)
    response.json.return_value = payload
    mock_post = MagicMock(return_value=response)
    monkeypatch.setattr(client.session, "post", mock_post)

    prompt = client.generate_prompt_for_kandinsky()

    assert prompt is not None
    assert prompt.strip('"') == "A frog"
    mock_post.assert_called_once()


def test_generate_prompt_error_response(client: GigaChatClient, monkeypatch: Any) -> None:
    monkeypatch.setattr(client, "get_access_token", MagicMock(return_value="token"))
    response = MagicMock(status_code=503, text="fail")
    monkeypatch.setattr(client.session, "post", MagicMock(return_value=response))

    assert client.generate_prompt_for_kandinsky() is None


def test_generate_prompt_timeout(client: GigaChatClient, monkeypatch: Any) -> None:
    monkeypatch.setattr(client, "get_access_token", MagicMock(return_value="token"))
    monkeypatch.setattr(client.session, "post", MagicMock(side_effect=requests.exceptions.ConnectionError("down")))

    assert client.generate_prompt_for_kandinsky() is None


def test_clean_prompt(client: GigaChatClient) -> None:
    raw = '```Prompt:"  hello   world  "```'
    cleaned = client._clean_prompt(raw)
    assert cleaned == "hello world"


def test_get_fallback_models(monkeypatch: Any) -> None:
    class DummyStore:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.called: bool = True

        def get_gigachat_model(self) -> None:
            return None

        def get_gigachat_available_models(self) -> list[str]:
            return []

        def set_gigachat_model(self, model_name: str) -> None:
            self.called_model: str = model_name

    monkeypatch.setattr("utils.models_store.ModelsStore", DummyStore)
    client = GigaChatClient()

    models = client._get_fallback_models()

    assert "GigaChat" in models
    assert len(models) > 0


def test_prompt_storage_writes_normalized_prompt_without_extra_quotes(tmp_path: Path, monkeypatch: Any) -> None:
    """
    Проверяем, что в файл записывается реальное содержимое промпта без лишних кавычек
    и ведущих/замыкающих пробелов.
    """

    # Подменяем логгер, чтобы не писать в реальные логи во время теста.
    fake_logger = MagicMock()
    monkeypatch.setattr("services.prompt_generator.get_logger", lambda *_args, **_kwargs: fake_logger)

    storage = PromptStorage(base_dir=tmp_path)

    # Промпт с кавычками и пробелами по краям.
    path_str = storage.save_prompt('   "A frog"   ', source="test")
    assert path_str is not None

    file_path = Path(path_str)
    assert file_path.is_file()
    content = file_path.read_text(encoding="utf-8")

    # Кавычки, пришедшие в теле промпта, сохраняются как есть,
    # но не добавляются новые и не дублируются.
    assert content == '"A frog"'


def test_prompt_storage_preserves_multiline_prompt_without_outer_spaces(tmp_path: Path, monkeypatch: Any) -> None:
    """
    Многострочные промпты сохраняются как есть, но без ведущих/замыкающих пробелов.
    Внутренняя структура (переводы строк и пробелы внутри строк) должна сохраниться.
    """

    fake_logger = MagicMock()
    monkeypatch.setattr("services.prompt_generator.get_logger", lambda *_args, **_kwargs: fake_logger)

    storage = PromptStorage(base_dir=tmp_path)

    multiline_prompt = "   line 1 \nsecond line\n\n  third line  "
    path_str = storage.save_prompt(multiline_prompt, source="multiline")
    assert path_str is not None

    file_path = Path(path_str)
    assert file_path.is_file()
    content = file_path.read_text(encoding="utf-8")

    # Ведущие/замыкающие пробелы по всему промпту удалены,
    # переводы строк внутри и пробелы в середине строк остаются.
    assert content == "line 1 \nsecond line\n\n  third line"


def test_prompt_storage_empty_prompt_raises_and_logs_warning(tmp_path: Path, monkeypatch: Any) -> None:
    """
    Пустой промпт после нормализации должен:
    - приводить к ValueError;
    - логироваться как предупреждение (гибкая ошибка, без падения сервиса выше по стеку).
    """

    fake_logger = MagicMock()
    monkeypatch.setattr("services.prompt_generator.get_logger", lambda *_args, **_kwargs: fake_logger)

    storage = PromptStorage(base_dir=tmp_path)

    with pytest.raises(ValueError):
        storage.save_prompt("   ", source="empty")

    fake_logger.warning.assert_called_once()


def test_prompt_storage_works_with_tmpfs_like_volume(tmp_path: Path, monkeypatch: Any) -> None:
    """
    Эмулируем запись в директорию, которая ведёт себя как tmpfs‑volume (быстрое, эфемерное хранилище).
    Это позволяет в CI отловить регрессии, связанные с правами/созданием директории и записью.
    """

    fake_logger = MagicMock()
    monkeypatch.setattr("services.prompt_generator.get_logger", lambda *_args, **_kwargs: fake_logger)

    # Эмулируем отдельный "volume" внутри временной директории pytest.
    volume_dir = tmp_path / "prompt_volume"
    storage = PromptStorage(base_dir=volume_dir)

    path_str = storage.save_prompt("A frog from tmpfs", source="tmpfs")
    assert path_str is not None

    file_path = Path(path_str)
    assert file_path.is_file()
    assert file_path.read_text(encoding="utf-8") == "A frog from tmpfs"
