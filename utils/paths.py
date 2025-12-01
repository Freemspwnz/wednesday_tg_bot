"""
Утилитный модуль с централизованными путями для файловых операций.

Хранит как относительные пути внутри проекта, так и ожидаемые абсолютные
пути внутри Docker-контейнера. Это позволяет:

- единообразно настраивать директории хранения изображений, логов и промптов;
- использовать относительные пути при локальном запуске (без /app);
- однозначно документировать, где именно находятся файлы в контейнере.
"""

from __future__ import annotations

from pathlib import Path

# === Изображения жабы ===

# Относительный путь внутри проекта (от текущей рабочей директории).
FROG_IMAGES_DIR: str = "data/frogs"

# Абсолютный путь внутри Docker-контейнера (WORKDIR=/app).
FROG_IMAGES_CONTAINER_PATH: str = "/app/data/frogs"


# === Логи приложения ===

# Относительный путь для логов (локальный запуск и внутри контейнера).
LOGS_DIR: str = "logs"

# Абсолютный путь к директории логов внутри Docker-контейнера.
LOGS_CONTAINER_PATH: str = "/app/logs"


# === Хранилище промптов GigaChat ===

PROMPTS_DIR: str = "data/prompts"
PROMPTS_CONTAINER_PATH: str = "/app/data/prompts"


def resolve_frog_images_dir() -> Path:
    """
    Возвращает путь к директории с изображениями жабы.

    При локальном запуске это <project_root>/data/frogs.
    В контейнере при WORKDIR=/app путь будет /app/data/frogs.
    """

    return Path(FROG_IMAGES_DIR)


def resolve_logs_dir() -> Path:
    """
    Возвращает путь к директории с логами.

    При локальном запуске это <project_root>/logs.
    В контейнере при WORKDIR=/app путь будет /app/logs.
    """

    return Path(LOGS_DIR)


def resolve_prompts_dir() -> Path:
    """
    Возвращает путь к директории с сохранёнными промптами GigaChat.

    При локальном запуске это <project_root>/data/prompts.
    В контейнере при WORKDIR=/app путь будет /app/data/prompts.
    """

    return Path(PROMPTS_DIR)
