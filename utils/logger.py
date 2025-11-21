"""
Модуль настройки логирования для приложения.
Использует библиотеку loguru для удобного и красивого логирования.
"""

import inspect
import sys
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar, cast

from loguru import logger

if TYPE_CHECKING:
    from loguru import Logger as LoggerType

from utils.config import config


def setup_logger() -> None:
    """
    Настраивает систему логирования для приложения.

    Конфигурирует:
    - Уровень логирования из конфигурации
    - Формат сообщений с временными метками
    - Вывод в консоль и файл
    - Ротацию логов по размеру и времени
    """

    # Удаляем стандартный обработчик loguru
    logger.remove()

    # Создаем папку для логов, если её нет
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # Настраиваем вывод в консоль с цветами
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>",
        level=config.log_level,
        colorize=True,
    )

    # Настраиваем вывод в файл с подробной информацией
    logger.add(
        log_dir / "wednesday_bot_{time:YYYY-MM-DD}.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
        level=config.log_level,
        rotation="1 day",  # Ротация каждый день
        retention="10 days",  # Хранить логи 10 дней
        compression="zip",  # Сжимать старые логи
        backtrace=True,  # Показывать полный стек ошибок
        diagnose=True,  # Показывать переменные в ошибках
    )

    # Логируем успешную инициализацию
    logger.info("Система логирования успешно настроена")


def get_logger(name: str | None = None) -> "LoggerType":
    """
    Получает настроенный логгер для указанного модуля.

    Args:
        name: Имя модуля (обычно __name__)

    Returns:
        Настроенный экземпляр логгера
    """
    if name:
        return logger.bind(name=name)
    return logger


P = ParamSpec("P")
R = TypeVar("R")
F = TypeVar("F", bound=Callable[..., Any])
MAX_ARG_REPR_LENGTH = 300


def _safe_repr(value: object) -> str:
    try:
        text = repr(value)
    except Exception as repr_error:  # pragma: no cover - fallback для нестандартных объектов
        text = f"<repr_error: {repr_error}>"
    if len(text) > MAX_ARG_REPR_LENGTH:
        return f"{text[:MAX_ARG_REPR_LENGTH]}..."
    return text


def _prepare_arguments(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    *,
    skip_first: bool,
) -> tuple[list[str], dict[str, str]]:
    args_repr = list(args)
    if skip_first and args_repr:
        args_repr = args_repr[1:]
    args_repr_str = [_safe_repr(arg) for arg in args_repr]
    kwargs_repr_str = {key: _safe_repr(value) for key, value in kwargs.items()}
    return args_repr_str, kwargs_repr_str


def log_execution(func: F) -> F:
    """
    Декоратор, автоматически логирующий начало, успешное завершение и ошибки функции/метода.
    Поддерживает как синхронные, так и асинхронные функции.
    """

    if getattr(func, "__log_wrapped__", False):
        return func

    func_name = f"{func.__module__}.{func.__qualname__}"
    parameters = list(inspect.signature(func).parameters.keys())
    skip_first_argument = bool(parameters and parameters[0] in {"self", "cls"})

    if inspect.iscoroutinefunction(func):

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            logger_instance = get_logger(func.__module__)
            args_repr, kwargs_repr = _prepare_arguments(args, kwargs, skip_first=skip_first_argument)
            logger_instance.info(f"Начало {func_name} args={args_repr} kwargs={kwargs_repr}")
            try:
                result = await func(*args, **kwargs)
                logger_instance.info(f"Успешное завершение {func_name}")
                return result
            except Exception as exc:
                logger_instance.error(f"Ошибка в {func_name}: {exc}", exc_info=True)
                raise

        setattr(async_wrapper, "__log_wrapped__", True)  # noqa: B010
        return cast(F, async_wrapper)

    @wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        logger_instance = get_logger(func.__module__)
        args_repr, kwargs_repr = _prepare_arguments(args, kwargs, skip_first=skip_first_argument)
        logger_instance.info(f"Начало {func_name} args={args_repr} kwargs={kwargs_repr}")
        try:
            result = func(*args, **kwargs)
            logger_instance.info(f"Успешное завершение {func_name}")
            return result
        except Exception as exc:
            logger_instance.error(f"Ошибка в {func_name}: {exc}", exc_info=True)
            raise

    setattr(sync_wrapper, "__log_wrapped__", True)  # noqa: B010
    return cast(F, sync_wrapper)


def log_all_methods(*, skip: tuple[str, ...] | None = None) -> Callable[[type], type]:
    """
    Класс-декоратор, автоматически оборачивающий все методы класса в log_execution.

    Args:
        skip: Список имен методов, которые не нужно оборачивать.
    """

    skip_set = set(skip or ())

    def decorator(cls: type) -> type:
        for attr_name, attr_value in cls.__dict__.items():
            if attr_name in skip_set:
                continue
            if attr_name.startswith("__") and attr_name.endswith("__"):
                continue

            if inspect.isfunction(attr_value):
                setattr(cls, attr_name, log_execution(attr_value))
            elif isinstance(attr_value, staticmethod):
                func = getattr(attr_value, "__func__", None)
                if func is not None:
                    wrapped = log_execution(func)
                    setattr(cls, attr_name, staticmethod(wrapped))
            elif isinstance(attr_value, classmethod):
                func = getattr(attr_value, "__func__", None)
                if func is not None:
                    wrapped = log_execution(func)
                    setattr(cls, attr_name, classmethod(wrapped))
        return cls

    return decorator


# Инициализируем логирование при импорте модуля
setup_logger()
