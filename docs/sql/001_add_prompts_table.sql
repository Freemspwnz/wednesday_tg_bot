-- Миграция: создание таблицы prompts для хранения метаданных промптов

CREATE TABLE IF NOT EXISTS prompts (
    id               BIGSERIAL PRIMARY KEY,
    raw_text         TEXT NOT NULL,
    normalized_text  TEXT NOT NULL,
    prompt_hash      CHAR(64) NOT NULL UNIQUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ab_group         TEXT NULL
);

CREATE INDEX IF NOT EXISTS idx_prompts_prompt_hash ON prompts(prompt_hash);
