"""
Модуль настройки логирования для приложения.
Использует библиотеку loguru для удобного и красивого логирования.
"""

import sys
from pathlib import Path
from typing import Optional, TYPE_CHECKING
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
        colorize=True
    )
    
    # Настраиваем вывод в файл с подробной информацией
    logger.add(
        log_dir / "wednesday_bot_{time:YYYY-MM-DD}.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
               "{name}:{function}:{line} | {message}",
        level=config.log_level,
        rotation="1 day",      # Ротация каждый день
        retention="10 days",   # Хранить логи 10 дней
        compression="zip",     # Сжимать старые логи
        backtrace=True,        # Показывать полный стек ошибок
        diagnose=True          # Показывать переменные в ошибках
    )
    
    # Логируем успешную инициализацию
    logger.info("Система логирования успешно настроена")


def get_logger(name: Optional[str] = None) -> 'LoggerType':
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


# Инициализируем логирование при импорте модуля
setup_logger()
