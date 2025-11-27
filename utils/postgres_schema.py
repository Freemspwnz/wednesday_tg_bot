"""
Инициализация схемы PostgreSQL для Wednesday Frog Bot.

Модуль содержит SQL для создания таблиц, которые заменяют файловые JSON‑хранилища:
- chats            ← ранее data/chats.json
- admins           ← ранее data/admins.json
- usage_stats      ← ранее data/usage_stats.json
- usage_settings   ← настройки квот /frog
- dispatch_registry← ранее data/dispatch_registry.json
- metrics          ← ранее data/metrics.json
- models_kandinsky ← настройки и список моделей Kandinsky
- models_gigachat  ← настройки и список моделей GigaChat

Создание таблиц выполняется идемпотентно через CREATE TABLE IF NOT EXISTS,
поэтому функцию `ensure_schema()` можно безопасно вызывать при каждом старте.
"""

from __future__ import annotations

from utils.logger import get_logger
from utils.postgres_client import get_postgres_pool

logger = get_logger(__name__)


_DDL_STATEMENTS: list[str] = [
    # Список чатов для рассылки
    """
    CREATE TABLE IF NOT EXISTS chats (
        chat_id BIGINT PRIMARY KEY,
        title   TEXT NOT NULL DEFAULT ''
    );
    """,
    # Список администраторов (кроме главного из ENV)
    """
    CREATE TABLE IF NOT EXISTS admins (
        user_id BIGINT PRIMARY KEY
    );
    """,
    # Помесячная статистика использования генераций
    """
    CREATE TABLE IF NOT EXISTS usage_stats (
        month  TEXT PRIMARY KEY,   -- формат YYYY-MM
        count  INTEGER NOT NULL DEFAULT 0
    );
    """,
    # Глобальные настройки квот /frog (единая строка id=1)
    """
    CREATE TABLE IF NOT EXISTS usage_settings (
        id             SMALLINT PRIMARY KEY DEFAULT 1,
        monthly_quota  INTEGER NOT NULL,
        frog_threshold INTEGER NOT NULL
    );
    """,
    # Реестр отправок по слотам (антидубликат)
    """
    CREATE TABLE IF NOT EXISTS dispatch_registry (
        key        TEXT PRIMARY KEY,
        slot_date  DATE NOT NULL,
        slot_time  TEXT NOT NULL,
        chat_id    BIGINT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    # Метрики производительности (единая строка id=1)
    """
    CREATE TABLE IF NOT EXISTS metrics (
        id                      SMALLINT PRIMARY KEY DEFAULT 1,
        generations_success     INTEGER NOT NULL DEFAULT 0,
        generations_failed      INTEGER NOT NULL DEFAULT 0,
        generations_retries     INTEGER NOT NULL DEFAULT 0,
        generations_total_time  DOUBLE PRECISION NOT NULL DEFAULT 0,
        dispatch_success        INTEGER NOT NULL DEFAULT 0,
        dispatch_failed         INTEGER NOT NULL DEFAULT 0,
        circuit_breaker_trips   INTEGER NOT NULL DEFAULT 0
    );
    """,
    # Настройки и доступные модели Kandinsky
    """
    CREATE TABLE IF NOT EXISTS models_kandinsky (
        id                   SMALLINT PRIMARY KEY DEFAULT 1,
        current_pipeline_id   TEXT,
        current_pipeline_name TEXT,
        available_models      TEXT[] NOT NULL DEFAULT '{}'
    );
    """,
    # Настройки и доступные модели GigaChat
    """
    CREATE TABLE IF NOT EXISTS models_gigachat (
        id                SMALLINT PRIMARY KEY DEFAULT 1,
        current_model     TEXT,
        available_models  TEXT[] NOT NULL DEFAULT '{}'
    );
    """,
]


async def ensure_schema() -> None:
    """
    Гарантирует наличие всех необходимых таблиц в базе Postgres.

    Функция идемпотентна и может вызываться при каждом запуске приложения.
    """
    pool = get_postgres_pool()
    logger.info("Проверяю инициализацию схемы Postgres (создание таблиц при необходимости)")

    async with pool.acquire() as conn:
        for stmt in _DDL_STATEMENTS:
            try:
                await conn.execute(stmt)
            except Exception as exc:  # pragma: no cover - защитное логирование
                logger.error(f"Ошибка при выполнении DDL для Postgres: {exc}")
                raise

    logger.info("Схема Postgres успешно проверена/инициализирована")
