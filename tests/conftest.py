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
    "SCHEDULER_SEND_TIMES": "09:00,12:00,18:00",
    "SCHEDULER_WEDNESDAY_DAY": "2",
    "SCHEDULER_TZ": "Europe/Moscow",
    # Параметры подключения к тестовой Postgres-БД (принудительно устанавливаем тестовые значения)
    "POSTGRES_USER": "test_user",
    "POSTGRES_PASSWORD": "test_password_ci_2024",
    "POSTGRES_DB": "wednesdaydb_test",
    "POSTGRES_HOST": "localhost",
    "POSTGRES_PORT": "5432",
}

for key, value in _session_env_defaults.items():
    # Принудительно устанавливаем тестовые значения, игнорируя существующие переменные окружения
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

    # GigaChat (async совместимый интерфейс)
    async def set_gigachat_model(self, model_name: str) -> None:
        self._gigachat_model = model_name

    async def get_gigachat_model(self) -> str | None:
        return self._gigachat_model

    async def set_gigachat_available_models(self, models: list[str]) -> None:
        self._gigachat_available = list(models)

    async def get_gigachat_available_models(self) -> list[str]:
        return list(self._gigachat_available)

    # Kandinsky (async совместимый интерфейс)
    async def set_kandinsky_model(self, pipeline_id: str, pipeline_name: str) -> None:
        self._kandinsky_model = (pipeline_id, pipeline_name)

    async def get_kandinsky_model(self) -> tuple[str | None, str | None]:
        return self._kandinsky_model

    async def set_kandinsky_available_models(self, models: list[Any] | list[str]) -> None:
        self._kandinsky_available = list(models) if models else []

    async def get_kandinsky_available_models(self) -> list[str]:
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
        "POSTGRES_USER": "test_user",
        "POSTGRES_PASSWORD": "test_password_ci_2024",
        "POSTGRES_DB": "wednesdaydb_test",
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5432",
        # Переменные планировщика для избежания вызовов load_dotenv() при инициализации SchedulerConfig
        "SCHEDULER_SEND_TIMES": "09:00,12:00,18:00",
        "SCHEDULER_WEDNESDAY_DAY": "2",
        "SCHEDULER_TZ": "Europe/Moscow",
    }
    for key, value in env_defaults.items():
        monkeypatch.setenv(key, value)
    yield


@pytest_asyncio.fixture(scope="function", autouse=True)
async def _setup_test_postgres() -> AsyncIterator[None]:
    """
    Инициализирует тестовый пул Postgres и схему БД для async‑репозиториев.

    Фикстура запускается перед каждым тестом и:
    - создаёт пул подключений через init_postgres_pool (пересоздаёт, если был создан в другом loop);
    - гарантирует наличие схемы через ensure_schema;
    - очищает данные в основных таблицах перед запуском теста.

    Ожидается, что тестовая БД (`POSTGRES_DB`) уже создана во внешнем окружении.
    """
    from utils.postgres_client import close_postgres_pool, get_postgres_pool, init_postgres_pool
    from utils.postgres_schema import ensure_schema

    # Закрываем пул, если он был создан в другом loop
    try:
        from utils import postgres_client
        if postgres_client._pool is not None:
            try:
                await close_postgres_pool()
            except Exception:
                pass
    except Exception:
        pass

    await init_postgres_pool(min_size=1, max_size=2)
    await ensure_schema()

    pool = get_postgres_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            TRUNCATE TABLE
                images,
                dispatch_registry,
                prompts,
                metrics_events,
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
        # Не закрываем пул здесь, чтобы он был доступен для других тестов
        # Пул будет пересоздан в следующем тесте, если loop изменится
        pass


@pytest_asyncio.fixture(scope="function")
async def cleanup_tables() -> AsyncIterator[None]:
    """
    Очищает таблицы между тестами для обеспечения изоляции.

    Используйте эту фикстуру в тестах, которые работают с PostgreSQL.
    Фикстура очищает все таблицы перед тестом, чтобы гарантировать изоляцию.

    Пример использования:
        @pytest.mark.asyncio
        async def test_something(cleanup_tables):
            # тест использует БД
    """
    from utils import postgres_client

    # Очистка выполняется в начале (setup) - только если пул инициализирован
    try:
        # Проверяем, инициализирован ли пул, без вызова get_postgres_pool()
        # чтобы избежать RuntimeError для тестов, которые не используют БД
        if postgres_client._pool is not None:
            pool = postgres_client._pool
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    TRUNCATE TABLE
                        images,
                        dispatch_registry,
                        prompts,
                        metrics_events,
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
    except Exception:
        # Игнорируем все ошибки (пул не инициализирован, проблемы с подключением и т.д.)
        pass

    yield


@pytest.fixture(autouse=True)
def patch_models_store(monkeypatch: Any, request: Any) -> Generator[None, None, None]:
    """
    Подменяет ModelsStore на простую in-memory реализацию.

    Исключает тесты из test_utils/test_models_store.py и интеграционные тесты,
    которые должны использовать реальный ModelsStore с Postgres.
    """
    import utils.admins_store as admins_store_module
    import utils.models_store as models_store_module

    # Не подменяем ModelsStore для тестов, которые явно тестируют его или используют реальные хранилища
    test_file = request.node.fspath.strpath if hasattr(request.node, "fspath") else ""
    test_name = request.node.name if hasattr(request.node, "name") else ""

    # Исключаем тесты, которые используют реальный ModelsStore
    should_skip_patch = (
        "test_models_store.py" in test_file
        or "integration_with_postgres_stores" in test_name
    )

    if not should_skip_patch:
        monkeypatch.setattr(models_store_module, "ModelsStore", _InMemoryModelsStore)

    # Создаём совместимый с AdminsStore объект для тестов

    class _TestAdminsStore:
        async def is_admin(self, user_id: int) -> bool:  # pragma: no cover - простая заглушка
            return False

        async def list_admins(self) -> list[int]:  # pragma: no cover - простая заглушка
            return []

        async def list_all_admins(self) -> list[int]:  # pragma: no cover - простая заглушка
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
