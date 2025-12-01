-- Rollback для миграции 003_add_metrics_events_table.sql

DROP TABLE IF EXISTS metrics_events CASCADE;
