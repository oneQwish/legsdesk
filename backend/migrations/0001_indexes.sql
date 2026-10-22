-- Индексы для частых запросов (лента изменений, «Моя неделя», сроки, просмотр документа).
-- Пишите миграции так, чтобы их можно было выполнить повторно: IF NOT EXISTS / IF EXISTS.
CREATE INDEX IF NOT EXISTS ix_events_unsequenced ON events (id) WHERE feed_seq IS NULL;
CREATE INDEX IF NOT EXISTS ix_events_actor_action_ts ON events (actor, action, ts);
CREATE INDEX IF NOT EXISTS ix_deadlines_case_status ON deadlines (case_id, status);
CREATE INDEX IF NOT EXISTS ix_deadlines_status_due ON deadlines (status, due_date);
CREATE INDEX IF NOT EXISTS ix_value_observations_document_id ON value_observations (document_id);
