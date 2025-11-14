-- Удаление всех данных пользователя 428114

-- Показываем статистику перед удалением
SELECT 
    'Перед удалением:' as info,
    (SELECT COUNT(*) FROM users WHERE user_id = '428114') as users_count,
    (SELECT COUNT(*) FROM conversations WHERE user_id = '428114') as conversations_count,
    (SELECT COUNT(*) FROM summaries WHERE user_id = '428114') as summaries_count;

-- Удаляем данные
DELETE FROM conversations WHERE user_id = '428114';
DELETE FROM summaries WHERE user_id = '428114';
DELETE FROM users WHERE user_id = '428114';

-- Показываем результат
SELECT 
    'После удаления:' as info,
    (SELECT COUNT(*) FROM users WHERE user_id = '428114') as users_count,
    (SELECT COUNT(*) FROM conversations WHERE user_id = '428114') as conversations_count,
    (SELECT COUNT(*) FROM summaries WHERE user_id = '428114') as summaries_count;
