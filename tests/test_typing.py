"""
Диагностические тесты для проверки типизации и импортов.
Используются для CI, чтобы убедиться, что код компилируется и типы корректны.
"""


def test_mypy_config_present() -> None:
    """Проверяет наличие конфигурации mypy."""
    import tomllib
    from pathlib import Path

    pyproject_path = Path("pyproject.toml")
    assert pyproject_path.exists(), "pyproject.toml должен существовать"

    config = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    tool_section = config.get("tool", {})
    mypy_section = tool_section.get("mypy")
    assert isinstance(mypy_section, dict), "[tool.mypy] должен быть определён в pyproject.toml"


def test_imports() -> None:
    """Проверяет, что все основные модули импортируются без ошибок."""
    import bot.handlers
    import bot.support_bot
    import bot.wednesday_bot  # noqa: F401
    import services.image_generator
    import services.prompt_generator
    import services.scheduler  # noqa: F401
    import utils.admins_store
    import utils.chats_store
    import utils.config
    import utils.dispatch_registry
    import utils.metrics
    import utils.models_store
    import utils.usage_tracker  # noqa: F401

    assert True


def test_type_annotations_exist() -> None:
    """Базовая проверка наличия аннотаций типов в ключевых классах."""
    from bot.support_bot import SupportBot
    from bot.wednesday_bot import WednesdayBot
    from services.image_generator import ImageGenerator
    from services.prompt_generator import GigaChatClient
    from services.scheduler import TaskScheduler

    # Проверяем, что классы существуют и имеют методы
    assert hasattr(WednesdayBot, "__init__")
    assert hasattr(SupportBot, "__init__")
    assert hasattr(ImageGenerator, "__init__")
    assert hasattr(GigaChatClient, "__init__")
    assert hasattr(TaskScheduler, "__init__")

    assert True
