-- Скрипт для удаления всех данных пользователя
-- Использование: psql -d dr_mind -f migrations/delete_user.sql
-- ВАЖНО: user_id должен быть в кавычках, так как это VARCHAR!

-- Замените '428114' на нужный user_id (обязательно в кавычках!)
\set user_id '''428114'''

-- Показываем статистику перед удалением
SELECT 
    'Перед удалением:' as info,
    (SELECT COUNT(*) FROM users WHERE user_id = :user_id) as users_count,
    (SELECT COUNT(*) FROM conversations WHERE user_id = :user_id) as conversations_count,
    (SELECT COUNT(*) FROM summaries WHERE user_id = :user_id) as summaries_count;

-- Удаляем данные (благодаря ON DELETE CASCADE, удаление из users удалит все связанные записи)
-- Но для ясности удаляем явно:

-- 1. Удаляем переписки
DELETE FROM conversations WHERE user_id = :user_id;

-- 2. Удаляем суммаризации
DELETE FROM summaries WHERE user_id = :user_id;

-- 3. Удаляем пользователя
DELETE FROM users WHERE user_id = :user_id;

-- Показываем результат
SELECT 
    'После удаления:' as info,
    (SELECT COUNT(*) FROM users WHERE user_id = :user_id) as users_count,
    (SELECT COUNT(*) FROM conversations WHERE user_id = :user_id) as conversations_count,
    (SELECT COUNT(*) FROM summaries WHERE user_id = :user_id) as summaries_count;

