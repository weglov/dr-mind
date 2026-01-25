-- Миграция для шифрования суммаризаций
-- Выполнить: psql -d dr_mind -f migrations/003_encrypt_summaries.sql

-- Шаг 1: Переименовываем колонку summary_text в encrypted_summary_text
ALTER TABLE summaries 
RENAME COLUMN summary_text TO encrypted_summary_text;

-- Шаг 2: Проверяем результат
SELECT 
    'Migration completed' as status,
    COUNT(*) as total_summaries
FROM summaries;




