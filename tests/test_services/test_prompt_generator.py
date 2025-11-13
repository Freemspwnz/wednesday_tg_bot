from unittest.mock import MagicMock

import pytest
import requests

from services.prompt_generator import GigaChatClient


@pytest.fixture
def client(monkeypatch):
    # Ускоряем генерацию uuid и времени
    monkeypatch.setattr("uuid.uuid4", lambda: "uuid")
    client = GigaChatClient()
    return client


def test_get_access_token_success(client):
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


def test_get_access_token_bad_status(client):
    response = MagicMock(status_code=500, text="error")
    client.session.post = MagicMock(return_value=response)

    assert client.get_access_token() is None


def test_get_access_token_timeout(client):
    client.session.post = MagicMock(side_effect=requests.exceptions.Timeout("boom"))

    assert client.get_access_token() is None


def test_generate_prompt_success(client, monkeypatch):
    client.get_access_token = MagicMock(return_value="token")
    payload = {
        "choices": [
            {"message": {"content": '```Prompt: "A frog"```'}}
        ]
    }
    response = MagicMock(status_code=200)
    response.json.return_value = payload
    client.session.post = MagicMock(return_value=response)

    prompt = client.generate_prompt_for_kandinsky()

    assert prompt.strip('"') == "A frog"
    client.session.post.assert_called_once()


def test_generate_prompt_error_response(client):
    client.get_access_token = MagicMock(return_value="token")
    response = MagicMock(status_code=503, text="fail")
    client.session.post = MagicMock(return_value=response)

    assert client.generate_prompt_for_kandinsky() is None


def test_generate_prompt_timeout(client):
    client.get_access_token = MagicMock(return_value="token")
    client.session.post = MagicMock(side_effect=requests.exceptions.ConnectionError("down"))

    assert client.generate_prompt_for_kandinsky() is None


def test_clean_prompt(client):
    raw = '```Prompt:"  hello   world  "```'
    cleaned = client._clean_prompt(raw)
    assert cleaned == "hello world"


def test_get_fallback_models(monkeypatch):
    class DummyStore:
        def __init__(self, *args, **kwargs):
            self.called = True

        def get_gigachat_model(self):
            return None

        def get_gigachat_available_models(self):
            return []

        def set_gigachat_model(self, model_name: str):
            self.called_model = model_name

    monkeypatch.setattr("utils.models_store.ModelsStore", DummyStore)
    client = GigaChatClient()

    models = client._get_fallback_models()

    assert "GigaChat" in models
    assert len(models) > 0

