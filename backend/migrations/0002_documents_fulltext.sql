-- Полнотекстовый поиск по текстам документов (OCR и цифровые оригиналы), с учётом русской морфологии:
-- «неустойку» находит «неустойка», «неустойки». Индекс по выражению — колонку добавлять не нужно.
CREATE INDEX IF NOT EXISTS ix_documents_text_fts ON documents USING gin (to_tsvector('russian', coalesce(text, '')));
