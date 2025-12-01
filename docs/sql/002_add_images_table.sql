-- Миграция: создание таблицы images для хранения метаданных сгенерированных изображений

CREATE TABLE IF NOT EXISTS images (
    id          BIGSERIAL PRIMARY KEY,
    image_hash  CHAR(64) NOT NULL UNIQUE,
    prompt_hash CHAR(64) NOT NULL UNIQUE
        REFERENCES prompts(prompt_hash) ON DELETE CASCADE,
    path        TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_images_prompt_hash ON images(prompt_hash);
