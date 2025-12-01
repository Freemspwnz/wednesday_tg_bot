"""
Репозиторий промптов на базе PostgreSQL.

Таблица `prompts` хранит:
- исходный текст промпта (raw_text);
- нормализованный текст (normalized_text);
- детерминированный sha256‑хэш нормализованного текста (prompt_hash) для дедупликации;
- временную метку создания и необязательную A/B‑группу.

Базовые операции:
- get_or_create_prompt(prompt_text) — нормализует текст, считает hash и возвращает
  существующую запись или создаёт новую;
- get_prompt_by_hash(prompt_hash) — ищет промпт по hash;
- get_random_prompt() — возвращает случайный сохранённый промпт (используется как fallback).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from utils.logger import get_logger, log_all_methods
from utils.postgres_client import get_postgres_pool

logger = get_logger(__name__)


@dataclass(slots=True)
class PromptRecord:
    """Структура данных одной записи из таблицы prompts."""

    id: int
    raw_text: str
    normalized_text: str
    prompt_hash: str
    created_at: datetime
    ab_group: str | None


@log_all_methods()
class PromptsStore:
    """
    Репозиторий для работы с таблицей `prompts`.

    Все методы асинхронные и используют Postgres как единственный источник истины
    для метаданных промптов (файловое хранилище — только как дополнительный backup/fallback).
    """

    def __init__(self) -> None:
        self.logger = get_logger(__name__)

    @staticmethod
    def _normalize(prompt_text: str) -> str:
        """
        Возвращает нормализованный текст промпта.

        Сейчас нормализация минимальна: strip() по краям.
        Важно хранить и raw, и normalized, чтобы можно было откатить нормализацию.
        """

        return prompt_text.strip()

    @staticmethod
    def _hash(normalized: str) -> str:
        """Считает sha256‑хэш нормализованного текста в hex‑представлении."""

        return sha256(normalized.encode("utf-8")).hexdigest()

    @staticmethod
    def _row_to_record(row: object) -> PromptRecord:
        """Преобразует asyncpg.Record в PromptRecord."""

        return PromptRecord(
            id=int(row["id"]),  # type: ignore[index]
            raw_text=str(row["raw_text"]),  # type: ignore[index]
            normalized_text=str(row["normalized_text"]),  # type: ignore[index]
            prompt_hash=str(row["prompt_hash"]),  # type: ignore[index]
            created_at=row["created_at"],  # type: ignore[index]
            ab_group=row["ab_group"],  # type: ignore[index]
        )

    async def get_or_create_prompt(self, prompt_text: str) -> PromptRecord:
        """
        Возвращает существующий или создаёт новый промпт.

        Алгоритм:
        - normalized = prompt_text.strip();
        - prompt_hash = sha256(normalized.encode("utf-8")).hexdigest();
        - если запись с таким hash уже есть — возвращаем её;
        - иначе создаём новую с ab_group=NULL.
        """

        normalized = self._normalize(prompt_text)
        prompt_hash = self._hash(normalized)

        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            # 1. Пытаемся найти уже существующую запись.
            row = await conn.fetchrow(
                """
                SELECT id, raw_text, normalized_text, prompt_hash, created_at, ab_group
                FROM prompts
                WHERE prompt_hash = $1;
                """,
                prompt_hash,
            )
            if row is not None:
                record = self._row_to_record(row)
                self.logger.info(f"Prompt exists: {prompt_hash} (id={record.id})")
                return record

            # 2. Создаём новую запись. ab_group пока всегда NULL,
            #    в будущем сюда может добавиться логика A/B‑распределения.
            row = await conn.fetchrow(
                """
                INSERT INTO prompts (raw_text, normalized_text, prompt_hash, ab_group)
                VALUES ($1, $2, $3, NULL)
                ON CONFLICT (prompt_hash) DO NOTHING
                RETURNING id, raw_text, normalized_text, prompt_hash, created_at, ab_group;
                """,
                prompt_text,
                normalized,
                prompt_hash,
            )

            if row is None:
                # Возможен condition‑race: кто‑то другой вставил такую же строку
                # между SELECT и INSERT. В этом случае просто перечитываем.
                row = await conn.fetchrow(
                    """
                    SELECT id, raw_text, normalized_text, prompt_hash, created_at, ab_group
                    FROM prompts
                    WHERE prompt_hash = $1;
                    """,
                    prompt_hash,
                )
                if row is None:  # pragma: no cover - крайне маловероятный кейс
                    raise RuntimeError("Failed to upsert prompt: concurrent insert lost")

            record = self._row_to_record(row)
            self.logger.info(f"Prompt created: {prompt_hash} (id={record.id})")
            return record

    async def get_prompt_by_hash(self, prompt_hash: str) -> PromptRecord | None:
        """
        Возвращает промпт по prompt_hash или None, если не найден.
        """

        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, raw_text, normalized_text, prompt_hash, created_at, ab_group
                FROM prompts
                WHERE prompt_hash = $1;
                """,
                prompt_hash,
            )
        if row is None:
            self.logger.debug(f"Prompt not found for hash: {prompt_hash}")
            return None

        record = self._row_to_record(row)
        self.logger.info(f"Prompt loaded by hash: {prompt_hash} (id={record.id})")
        return record

    async def get_random_prompt(self) -> PromptRecord | None:
        """
        Возвращает случайный промпт из таблицы или None, если таблица пуста.
        Используется как fallback при недоступности GigaChat.
        """

        pool = get_postgres_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, raw_text, normalized_text, prompt_hash, created_at, ab_group
                FROM prompts
                ORDER BY random()
                LIMIT 1;
                """,
            )
        if row is None:
            self.logger.debug("get_random_prompt: таблица prompts пуста")
            return None

        record = self._row_to_record(row)
        self.logger.info(f"Random prompt selected: {record.prompt_hash} (id={record.id})")
        return record
