import importlib
import os
import sys
from collections.abc import Callable, Generator
from types import SimpleNamespace
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from pytest import MonkeyPatch

_session_monkeypatch = MonkeyPatch()
_session_env_defaults = {
    "TELEGRAM_BOT_TOKEN": "session-test-token",
    "KANDINSKY_API_KEY": "session-test-api",
    "KANDINSKY_SECRET_KEY": "session-test-secret",
    "CHAT_ID": "999999",
    "ADMIN_CHAT_ID": "999998",
}

for key, value in _session_env_defaults.items():
    if not os.getenv(key):
        _session_monkeypatch.setenv(key, value)


@pytest.fixture(scope="session", autouse=True)
def session_env_defaults() -> Generator[None, None, None]:
    """Устанавливает обязательные переменные окружения до импорта модулей проекта."""
    yield
    _session_monkeypatch.undo()


class _InMemoryModelsStore:
    """Простое хранилище моделей для тестов без файловой системы."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._gigachat_model: str | None = None
        self._gigachat_available: list[str] = []
        self._kandinsky_model: tuple[str | None, str | None] = (None, None)
        self._kandinsky_available: list[str] = []

    # GigaChat
    def set_gigachat_model(self, model_name: str) -> None:
        self._gigachat_model = model_name

    def get_gigachat_model(self) -> str | None:
        return self._gigachat_model

    def set_gigachat_available_models(self, models: list[str]) -> None:
        self._gigachat_available = list(models)

    def get_gigachat_available_models(self) -> list[str]:
        return list(self._gigachat_available)

    # Kandinsky
    def set_kandinsky_model(self, pipeline_id: str, pipeline_name: str) -> None:
        self._kandinsky_model = (pipeline_id, pipeline_name)

    def get_kandinsky_model(self) -> tuple[str | None, str | None]:
        return self._kandinsky_model

    def set_kandinsky_available_models(self, models: list[Any] | list[str]) -> None:
        self._kandinsky_available = list(models) if models else []

    def get_kandinsky_available_models(self) -> list[str]:
        return list(self._kandinsky_available)


@pytest.fixture(autouse=True)
def base_env(monkeypatch: Any, tmp_path_factory: Any) -> Generator[None, None, None]:
    """Гарантирует наличие обязательных переменных окружения и изолированных хранилищ."""
    env_defaults = {
        "TELEGRAM_BOT_TOKEN": "test-token",
        "KANDINSKY_API_KEY": "test-api",
        "KANDINSKY_SECRET_KEY": "test-secret",
        "CHAT_ID": "12345",
        "ADMIN_CHAT_ID": "54321",
        "GIGACHAT_AUTHORIZATION_KEY": "ZmFrZS1rZXk=",
        "GIGACHAT_SCOPE": "GIGACHAT_API_PERS",
        # Параметры подключения к тестовой Postgres-БД
        "POSTGRES_USER": os.getenv("POSTGRES_USER", "wednesday"),
        "POSTGRES_PASSWORD": os.getenv("POSTGRES_PASSWORD", "wednesday3380!"),
        "POSTGRES_DB": os.getenv("POSTGRES_DB", "wednesdaydb_test"),
        "POSTGRES_HOST": os.getenv("POSTGRES_HOST", "localhost"),
        "POSTGRES_PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
    for key, value in env_defaults.items():
        monkeypatch.setenv(key, value)
    yield


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _setup_test_postgres() -> AsyncIterator[None]:
    """
    Инициализирует тестовый пул Postgres и схему БД для async‑репозиториев.

    Фикстура запускается один раз за сессию тестов и:
    - создаёт пул подключений через init_postgres_pool;
    - гарантирует наличие схемы через ensure_schema;
    - очищает данные в основных таблицах перед запуском тестов.

    Ожидается, что тестовая БД (`POSTGRES_DB`) уже создана во внешнем окружении.
    """
    from utils.postgres_client import close_postgres_pool, get_postgres_pool, init_postgres_pool
    from utils.postgres_schema import ensure_schema

    await init_postgres_pool(min_size=1, max_size=2)
    await ensure_schema()

    pool = get_postgres_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            TRUNCATE TABLE
                dispatch_registry,
                chats,
                admins,
                usage_stats,
                usage_settings,
                metrics,
                models_kandinsky,
                models_gigachat
            RESTART IDENTITY;
            """,
        )

    try:
        yield
    finally:
        await close_postgres_pool()


@pytest.fixture(autouse=True)
def patch_models_store(monkeypatch: Any) -> Generator[None, None, None]:
    """Подменяет ModelsStore на простую in-memory реализацию."""
    import utils.admins_store as admins_store_module
    import utils.models_store as models_store_module

    monkeypatch.setattr(models_store_module, "ModelsStore", _InMemoryModelsStore)
    # Создаём совместимый с AdminsStore объект для тестов

    class _TestAdminsStore:
        def is_admin(self, user_id: int) -> bool:
            return False

        def list_admins(self) -> list[int]:
            return []

        def list_all_admins(self) -> list[int]:
            return []

    monkeypatch.setattr(admins_store_module, "AdminsStore", lambda *args, **kwargs: _TestAdminsStore())
    yield


@pytest.fixture(autouse=True)
def patch_gigachat_client(monkeypatch: Any) -> Generator[None, None, None]:
    """Исключает реальные вызовы GigaChat при создании ImageGenerator."""

    class _DummyGigaChatClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._prompt: str = "dummy prompt"

        @staticmethod
        def _clean_prompt(prompt: str | None = None) -> str:
            if not prompt:
                return "Wednesday Frog prompt"
            cleaned = prompt.replace("```", "")
            cleaned = cleaned.replace("Prompt:", "").replace("prompt:", "").replace("Промпт:", "")
            cleaned = cleaned.strip("\"'")
            return ' '.join(cleaned.split()).strip()

        def test_connection(self) -> bool:
            return False

        def generate_prompt_for_kandinsky(self) -> str:
            return self._prompt

    import services.prompt_generator as prompt_module

    monkeypatch.setattr(prompt_module, "GigaChatClient", _DummyGigaChatClient)
    yield


@pytest.fixture
def reload_config() -> Generator[Callable[[], Any], None, None]:
    """
    Возвращает функцию для повторной загрузки utils.config с актуальными env.
    После теста модуль очищается из sys.modules.
    """

    loaded_modules: list[Any] = []

    def _reload() -> Any:
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
def fake_update() -> Any:
    """Создает простую структуру Update с асинхронным reply_text."""
    status_message = SimpleNamespace(delete=AsyncMock())
    reply_text = AsyncMock(return_value=status_message)
    reply_photo = AsyncMock(return_value=SimpleNamespace(delete=AsyncMock()))
    message = SimpleNamespace(
        reply_text=reply_text,
        reply_photo=reply_photo,
    )
    user = SimpleNamespace(id=42)
    chat = SimpleNamespace(id=100500)
    return SimpleNamespace(message=message, effective_user=user, effective_chat=chat)


@pytest.fixture
def fake_context() -> Any:
    """Создает минимальный контекст Telegram с AsyncMock ботом."""
    class _App:
        def __init__(self) -> None:
            self.bot_data: dict[str, Any] = {"bot": SimpleNamespace(stop=AsyncMock())}
            self.updater = SimpleNamespace(stop=AsyncMock())

        async def stop(self) -> None:
            return None

    class _Context:
        def __init__(self) -> None:
            self.args: list[str] = []
            self.application = _App()
            self.bot = SimpleNamespace(
                send_document=AsyncMock(),
                send_message=AsyncMock(),
                send_photo=AsyncMock(),
            )

    return _Context()


@pytest.fixture
def async_retry_stub(monkeypatch: Any) -> Callable[[Any], None]:
    """Фикстура, подменяющая _retry_on_connect_error на прямой вызов функции."""

    def _apply(target: Any) -> None:
        async def _direct(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)

        monkeypatch.setattr(target, "_retry_on_connect_error", _direct)

    return _apply
