"""
Модуль настройки логирования для приложения.
Использует библиотеку loguru для удобного и красивого логирования.
"""

import inspect
import sys
from collections.abc import Callable
from functools import wraps
from typing import TYPE_CHECKING, Any, Literal, ParamSpec, TypeVar, cast, overload

from loguru import logger

if TYPE_CHECKING:
    from loguru import Logger as LoggerType

from utils.config import config
from utils.paths import LOGS_CONTAINER_PATH, resolve_logs_dir

# Типы для уровней логирования
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


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

    # Создаем папку для логов, если её нет.
    # Используем относительный путь (logs/), который внутри Docker-контейнера
    # при WORKDIR=/app будет соответствовать /app/logs и будет примонтирован
    # в volume. При локальном запуске логи пишутся в ./logs рядом с проектом.
    log_dir = resolve_logs_dir()
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

    # Настраиваем вывод в файл с подробной информацией.
    # Важно: путь привязан к volume с логами внутри контейнера:
    # - локально пишем в ./logs;
    # - в Docker при WORKDIR=/app это /app/logs, примонтированный как volume.
    # Используем ротацию по размеру (10 MB) и retention 7 дней, чтобы:
    # - не допустить бесконтрольного роста логов;
    # - сохранить достаточно истории для расследований инцидентов.
    logger.add(
        log_dir / "wednesday_bot.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
        level=config.log_level,
        rotation="10 MB",  # Ротация по размеру файла
        retention="7 days",  # Хранить логи 7 дней
        compression="zip",  # Сжимать старые логи
        backtrace=True,  # Показывать полный стек ошибок
        diagnose=True,  # Показывать переменные в ошибках
    )

    # Логируем успешную инициализацию с явным указанием контейнерного пути.
    logger.info(
        f"Система логирования успешно настроена, логи пишутся в {LOGS_CONTAINER_PATH}",
    )


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
_SENSITIVE_KEYWORDS: set[str] = {
    "token",
    "secret",
    "password",
    "passwd",
    "api_key",
    "authorization",
}


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
    # Для позиционных аргументов оставляем только усечённый repr без
    # дополнительной фильтрации: секреты как позиционные параметры в
    # проекте не передаются, а логирование здесь нужно для отладки.
    args_repr_str = [_safe_repr(arg) for arg in args_repr]
    # Для именованных аргументов дополнительно защищаем потенциально
    # чувствительные данные (токены, пароли, ключи и т.п.). Это позволяет
    # безопасно использовать декоратор log_execution даже для функций,
    # которые принимают секреты через kwargs.
    kwargs_repr_str: dict[str, str] = {}
    for key, value in kwargs.items():
        key_lower = key.lower()
        if any(word in key_lower for word in _SENSITIVE_KEYWORDS):
            kwargs_repr_str[key] = "<redacted>"
        else:
            kwargs_repr_str[key] = _safe_repr(value)
    return args_repr_str, kwargs_repr_str


@overload
def log_execution(
    func: F,
    *,
    level: LogLevel = ...,
    log_args: bool = ...,
    log_result: bool = ...,
) -> F: ...


@overload
def log_execution(
    func: None = None,
    *,
    level: LogLevel = ...,
    log_args: bool = ...,
    log_result: bool = ...,
) -> Callable[[F], F]: ...


def log_execution(
    func: F | None = None,
    *,
    level: LogLevel = "INFO",
    log_args: bool = True,
    log_result: bool = False,
) -> F | Callable[[F], F]:
    """
    Декоратор, автоматически логирующий начало, успешное завершение и ошибки функции/метода.
    Поддерживает как синхронные, так и асинхронные функции.

    Args:
        func: Функция для обёртки (при использовании как декоратор без скобок)
        level: Уровень логирования для начала и завершения (DEBUG, INFO, WARNING, ERROR)
        log_args: Логировать ли аргументы функции (по умолчанию True)
        log_result: Логировать ли результат функции (по умолчанию False)

    Returns:
        Обёрнутая функция с логированием
    """
    # Поддержка использования как @log_execution или @log_execution(level="DEBUG")
    if func is None:
        # Вызов с параметрами: @log_execution(level="DEBUG")
        def decorator(f: F) -> F:
            return log_execution(f, level=level, log_args=log_args, log_result=log_result)

        return decorator

    if getattr(func, "__log_wrapped__", False):
        return func

    func_name = f"{func.__module__}.{func.__qualname__}"
    parameters = list(inspect.signature(func).parameters.keys())
    skip_first_argument = bool(parameters and parameters[0] in {"self", "cls"})

    # Определяем, является ли метод приватным (начинается с _)
    # Для приватных методов используем DEBUG, если уровень не был явно указан (остался INFO по умолчанию)
    is_private = func.__name__.startswith("_") and not func.__name__.startswith("__")
    # Если уровень явно указан (не INFO по умолчанию), используем его; иначе для приватных используем DEBUG
    effective_level: LogLevel = "DEBUG" if (is_private and level == "INFO") else level

    if inspect.iscoroutinefunction(func):

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            logger_instance = get_logger(func.__module__)
            # Получаем метод логирования по уровню из logger_instance
            log_method = getattr(logger_instance, effective_level.lower())
            if log_args:
                args_repr, kwargs_repr = _prepare_arguments(args, kwargs, skip_first=skip_first_argument)
                log_method(f"Начало {func_name} args={args_repr} kwargs={kwargs_repr}")
            else:
                log_method(f"Начало {func_name}")
            try:
                result = await func(*args, **kwargs)
                if log_result:
                    log_method(f"Успешное завершение {func_name} result={_safe_repr(result)}")
                else:
                    log_method(f"Успешное завершение {func_name}")
                return result
            except Exception as exc:
                logger_instance.error(f"Ошибка в {func_name}: {exc}", exc_info=True)
                raise

        setattr(async_wrapper, "__log_wrapped__", True)  # noqa: B010
        return cast(F, async_wrapper)

    @wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        logger_instance = get_logger(func.__module__)
        # Получаем метод логирования по уровню из logger_instance
        log_method = getattr(logger_instance, effective_level.lower())
        if log_args:
            args_repr, kwargs_repr = _prepare_arguments(args, kwargs, skip_first=skip_first_argument)
            log_method(f"Начало {func_name} args={args_repr} kwargs={kwargs_repr}")
        else:
            log_method(f"Начало {func_name}")
        try:
            result = func(*args, **kwargs)
            if log_result:
                log_method(f"Успешное завершение {func_name} result={_safe_repr(result)}")
            else:
                log_method(f"Успешное завершение {func_name}")
            return result
        except Exception as exc:
            logger_instance.error(f"Ошибка в {func_name}: {exc}", exc_info=True)
            raise

    setattr(sync_wrapper, "__log_wrapped__", True)  # noqa: B010
    return cast(F, sync_wrapper)


def log_all_methods(
    *,
    skip: tuple[str, ...] | None = None,
    skip_private: bool = True,
    default_level: LogLevel = "INFO",
    method_levels: dict[str, LogLevel] | None = None,
) -> Callable[[type], type]:
    """
    Класс-декоратор, автоматически оборачивающий все методы класса в log_execution.

    Args:
        skip: Список имен методов, которые не нужно оборачивать (полное исключение).
        skip_private: Исключать ли приватные методы (начинающиеся с `_`, но не `__`).
                     По умолчанию True - приватные методы не логируются.
        default_level: Уровень логирования по умолчанию для публичных методов (INFO, DEBUG, WARNING, ERROR).
        method_levels: Словарь {имя_метода: уровень} для явного указания уровня логирования
                      для конкретных методов. Имеет приоритет над default_level.

    Примеры:
        @log_all_methods()  # Логирует только публичные методы на уровне INFO
        @log_all_methods(skip_private=False)  # Логирует все методы, приватные на DEBUG
        @log_all_methods(skip=("_internal",), method_levels={"critical_method": "ERROR"})
    """

    skip_set = set(skip or ())
    method_levels_dict = method_levels or {}

    def decorator(cls: type) -> type:
        for attr_name, attr_value in cls.__dict__.items():
            # Пропускаем явно исключённые методы
            if attr_name in skip_set:
                continue

            # Пропускаем магические методы (__init__, __str__ и т.д.)
            if attr_name.startswith("__") and attr_name.endswith("__"):
                continue

            # Пропускаем приватные методы, если skip_private=True
            is_private = attr_name.startswith("_") and not attr_name.startswith("__")
            if skip_private and is_private:
                continue

            # Определяем уровень логирования для метода
            level = method_levels_dict.get(attr_name, default_level)
            # Для приватных методов, если не указан явно, используем DEBUG
            if is_private and attr_name not in method_levels_dict:
                level = "DEBUG"

            # Оборачиваем функцию/метод
            if inspect.isfunction(attr_value):
                setattr(cls, attr_name, log_execution(attr_value, level=level))
            elif isinstance(attr_value, staticmethod):
                func = getattr(attr_value, "__func__", None)
                if func is not None:
                    wrapped = log_execution(func, level=level)
                    setattr(cls, attr_name, staticmethod(wrapped))
            elif isinstance(attr_value, classmethod):
                func = getattr(attr_value, "__func__", None)
                if func is not None:
                    wrapped = log_execution(func, level=level)
                    setattr(cls, attr_name, classmethod(wrapped))
        return cls

    return decorator


# Инициализируем логирование при импорте модуля
setup_logger()
