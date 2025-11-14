from unittest.mock import MagicMock
from typing import Any

import pytest
import requests

from services.prompt_generator import GigaChatClient


@pytest.fixture
def client(monkeypatch: Any) -> GigaChatClient:
    # Ускоряем генерацию uuid и времени
    monkeypatch.setattr("uuid.uuid4", lambda: "uuid")
    client = GigaChatClient()
    return client


def test_get_access_token_success(client: GigaChatClient) -> None:
    response = MagicMock(status_code=200)
    response.json.return_value = {"access_token": "abc123", "expires_in": 1800}
    client.session.post = MagicMock(return_value=response)

    token = client.get_access_token()

    assert token == "abc123"
    client.session.post.assert_called_once()

    # Проверяем, что повторный вызов использует кэш
    client.session.post.reset_mock()
    cached = client.get_access_token()
    assert cached == "abc123"
    client.session.post.assert_not_called()


def test_get_access_token_bad_status(client: GigaChatClient) -> None:
    response = MagicMock(status_code=500, text="error")
    client.session.post = MagicMock(return_value=response)

    assert client.get_access_token() is None


def test_get_access_token_timeout(client: GigaChatClient) -> None:
    client.session.post = MagicMock(side_effect=requests.exceptions.Timeout("boom"))

    assert client.get_access_token() is None


def test_generate_prompt_success(client: GigaChatClient, monkeypatch: Any) -> None:
    monkeypatch.setattr(client, "get_access_token", MagicMock(return_value="token"))
    payload = {
        "choices": [
            {"message": {"content": '```Prompt: "A frog"```'}}
        ]
    }
    response = MagicMock(status_code=200)
    response.json.return_value = payload
    monkeypatch.setattr(client.session, "post", MagicMock(return_value=response))

    prompt = client.generate_prompt_for_kandinsky()

    assert prompt is not None
    assert prompt.strip('"') == "A frog"
    client.session.post.assert_called_once()


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

