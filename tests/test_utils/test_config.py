from typing import Any

import dotenv
import pytest


def test_config_loads_required_env(monkeypatch: Any, reload_config: Any) -> None:
    custom_env = {
        "TELEGRAM_BOT_TOKEN": "custom-token",
        "KANDINSKY_API_KEY": "custom-api",
        "KANDINSKY_SECRET_KEY": "custom-secret",
        "CHAT_ID": "999",
        "GIGACHAT_API_URL": "https://example.com/chat",
    }
    for key, value in custom_env.items():
        monkeypatch.setenv(key, value)

    config_module = reload_config()

    assert config_module.config.telegram_token == "custom-token"
    assert config_module.config.kandinsky_api_key == "custom-api"
    assert config_module.config.chat_id == "999"
    assert config_module.config.gigachat_api_url == "https://example.com/chat"


def test_config_missing_required_env(monkeypatch: Any, reload_config: Any) -> None:
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)

    required_vars = [
        "TELEGRAM_BOT_TOKEN",
        "KANDINSKY_API_KEY",
        "KANDINSKY_SECRET_KEY",
        "CHAT_ID",
    ]
    for key in required_vars:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValueError) as exc_info:
        reload_config()

    assert "TELEGRAM_BOT_TOKEN" in str(exc_info.value)

    # Восстанавливаем окружение до финализации фикстур
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "restored-token")
    monkeypatch.setenv("KANDINSKY_API_KEY", "restored-api")
    monkeypatch.setenv("KANDINSKY_SECRET_KEY", "restored-secret")
    monkeypatch.setenv("CHAT_ID", "12345")
