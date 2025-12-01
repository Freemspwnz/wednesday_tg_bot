-- Миграция: создание таблицы metrics_events для логирования событий генерации и кеша

CREATE TABLE IF NOT EXISTS metrics_events (
    id BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL, -- например: 'error', 'generation', 'cache_hit', 'cache_miss'
    user_id TEXT NULL,
    prompt_hash CHAR(64) NULL,
    image_hash CHAR(64) NULL,
    latency_ms INTEGER NULL, -- латентность в миллисекундах
    status TEXT NULL, -- например: 'ok', 'error', 'cached', 'started'
    timestamp TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_metrics_event_type ON metrics_events(event_type);
CREATE INDEX IF NOT EXISTS idx_metrics_prompt_hash ON metrics_events(prompt_hash);
