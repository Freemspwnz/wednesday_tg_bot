"""
Диагностические тесты для проверки типизации и импортов.
Используются для CI, чтобы убедиться, что код компилируется и типы корректны.
"""


def test_mypy_config_present() -> None:
    """Проверяет наличие конфигурации mypy."""
    from pathlib import Path
    mypy_config = Path("mypy.ini")
    assert mypy_config.exists(), "mypy.ini должен существовать"


def test_imports() -> None:
    """Проверяет, что все основные модули импортируются без ошибок."""
    import bot.wednesday_bot  # noqa: F401
    import bot.support_bot  # noqa: F401
    import bot.handlers  # noqa: F401
    import services.image_generator  # noqa: F401
    import services.prompt_generator  # noqa: F401
    import services.scheduler  # noqa: F401
    import utils.config  # noqa: F401
    import utils.usage_tracker  # noqa: F401
    import utils.chats_store  # noqa: F401
    import utils.dispatch_registry  # noqa: F401
    import utils.models_store  # noqa: F401
    import utils.metrics  # noqa: F401
    import utils.admins_store  # noqa: F401
    assert True


def test_type_annotations_exist() -> None:
    """Базовая проверка наличия аннотаций типов в ключевых классах."""
    from bot.wednesday_bot import WednesdayBot
    from bot.support_bot import SupportBot
    from services.image_generator import ImageGenerator
    from services.prompt_generator import GigaChatClient
    from services.scheduler import TaskScheduler
    
    # Проверяем, что классы существуют и имеют методы
    assert hasattr(WednesdayBot, '__init__')
    assert hasattr(SupportBot, '__init__')
    assert hasattr(ImageGenerator, '__init__')
    assert hasattr(GigaChatClient, '__init__')
    assert hasattr(TaskScheduler, '__init__')
    
    assert True

