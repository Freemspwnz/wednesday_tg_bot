import importlib
import sys
from types import SimpleNamespace
from typing import Callable, Optional
from unittest.mock import AsyncMock

import pytest


class _InMemoryModelsStore:
    """Простое хранилище моделей для тестов без файловой системы."""

    def __init__(self, *args, **kwargs):
        self._gigachat_model: Optional[str] = None
        self._gigachat_available: list[str] = []
        self._kandinsky_model: tuple[Optional[str], Optional[str]] = (None, None)
        self._kandinsky_available: list[str] = []

    # GigaChat
    def set_gigachat_model(self, model_name: str) -> None:
        self._gigachat_model = model_name

    def get_gigachat_model(self) -> Optional[str]:
        return self._gigachat_model

    def set_gigachat_available_models(self, models: list[str]) -> None:
        self._gigachat_available = list(models)

    def get_gigachat_available_models(self) -> list[str]:
        return list(self._gigachat_available)

    # Kandinsky
    def set_kandinsky_model(self, pipeline_id: str, pipeline_name: str) -> None:
        self._kandinsky_model = (pipeline_id, pipeline_name)

    def get_kandinsky_model(self) -> tuple[Optional[str], Optional[str]]:
        return self._kandinsky_model

    def set_kandinsky_available_models(self, models) -> None:
        self._kandinsky_available = list(models)

    def get_kandinsky_available_models(self) -> list[str]:
        return list(self._kandinsky_available)


@pytest.fixture(autouse=True)
def base_env(monkeypatch, tmp_path_factory):
    """Гарантирует наличие обязательных переменных окружения и изолированных хранилищ."""
    storage_dir = tmp_path_factory.mktemp("storage")
    env_defaults = {
        "TELEGRAM_BOT_TOKEN": "test-token",
        "KANDINSKY_API_KEY": "test-api",
        "KANDINSKY_SECRET_KEY": "test-secret",
        "CHAT_ID": "12345",
        "GIGACHAT_AUTHORIZATION_KEY": "ZmFrZS1rZXk=",
        "GIGACHAT_SCOPE": "GIGACHAT_API_PERS",
        "MODELS_STORAGE": str(storage_dir / "models.json"),
        "ADMINS_STORAGE": str(storage_dir / "admins.json"),
    }
    for key, value in env_defaults.items():
        monkeypatch.setenv(key, value)


@pytest.fixture(autouse=True)
def patch_models_store(monkeypatch):
    """Подменяет ModelsStore на простую in-memory реализацию."""
    import utils.models_store as models_store_module
    import utils.admins_store as admins_store_module

    monkeypatch.setattr(models_store_module, "ModelsStore", _InMemoryModelsStore)
    monkeypatch.setattr(admins_store_module, "AdminsStore", lambda *args, **kwargs: SimpleNamespace(
        is_admin=lambda user_id: False,
        list_admins=lambda: [],
    ))
    yield


@pytest.fixture(autouse=True)
def patch_gigachat_client(monkeypatch):
    """Исключает реальные вызовы GigaChat при создании ImageGenerator."""

    class _DummyGigaChatClient:
        def __init__(self, *args, **kwargs):
            self._prompt = "dummy prompt"

        def test_connection(self) -> bool:
            return False

        def generate_prompt_for_kandinsky(self) -> str:
            return self._prompt

    import services.prompt_generator as prompt_module

    monkeypatch.setattr(prompt_module, "GigaChatClient", _DummyGigaChatClient)
    yield


@pytest.fixture
def reload_config():
    """
    Возвращает функцию для повторной загрузки utils.config с актуальными env.
    После теста модуль очищается из sys.modules.
    """

    loaded_modules = []

    def _reload():
        if "utils.config" in sys.modules:
            del sys.modules["utils.config"]
        module = importlib.import_module("utils.config")
        loaded_modules.append(module)
        return module

    try:
        yield _reload
    finally:
        if "utils.config" in sys.modules:
            del sys.modules["utils.config"]
        # пересоздаем модуль для других тестов с дефолтным окружением
        importlib.import_module("utils.config")


@pytest.fixture
def fake_update():
    """Создает простую структуру Update с асинхронным reply_text."""
    reply = AsyncMock()
    message = SimpleNamespace(reply_text=reply)
    user = SimpleNamespace(id=42)
    chat = SimpleNamespace(id=100500)
    return SimpleNamespace(message=message, effective_user=user, effective_chat=chat)


@pytest.fixture
def fake_context():
    """Создает минимальный контекст Telegram с AsyncMock ботом."""
    class _App:
        def __init__(self):
            self.bot_data = {"bot": SimpleNamespace(stop=AsyncMock())}
            self.updater = SimpleNamespace(stop=AsyncMock())

        async def stop(self):
            return None

    class _Context:
        def __init__(self):
            self.args = []
            self.application = _App()
            self.bot = SimpleNamespace(send_document=AsyncMock())

    return _Context()


@pytest.fixture
def async_retry_stub(monkeypatch):
    """Фикстура, подменяющая _retry_on_connect_error на прямой вызов функции."""

    def _apply(target):
        async def _direct(func: Callable, *args, **kwargs):
            return await func(*args, **kwargs)

        monkeypatch.setattr(target, "_retry_on_connect_error", _direct)

    return _apply

