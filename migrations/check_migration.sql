-- Проверка результатов миграции
-- Выполните этот запрос в DataGrip чтобы убедиться что все прошло успешно

-- Общая статистика
SELECT 
    'Пользователи' as table_name,
    COUNT(*) as count
FROM users
UNION ALL
SELECT 
    'Переписки (conversations)' as table_name,
    COUNT(*) as count
FROM conversations
UNION ALL
SELECT 
    'Суммаризации (summaries)' as table_name,
    COUNT(*) as count
FROM summaries;

-- Проверка что данные мигрировали
SELECT 
    (SELECT COUNT(*) FROM users) as total_users,
    (SELECT COUNT(*) FROM conversations) as total_conversations,
    (SELECT COUNT(DISTINCT user_id) FROM conversations) as users_with_conversations,
    (SELECT COUNT(*) FROM summaries) as total_summaries,
    (SELECT COUNT(DISTINCT user_id) FROM summaries) as users_with_summaries;

-- Проверка структуры таблиц
SELECT 
    table_name,
    column_name,
    data_type
FROM information_schema.columns
WHERE table_name IN ('users', 'conversations', 'summaries')
ORDER BY table_name, ordinal_position;

