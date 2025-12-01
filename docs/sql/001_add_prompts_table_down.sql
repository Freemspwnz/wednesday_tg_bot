-- Rollback для миграции 001_add_prompts_table.sql

DROP TABLE IF EXISTS prompts CASCADE;
