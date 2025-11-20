# Руководство по миграции данных

## Важно перед миграцией!

⚠️ **Сделайте резервную копию базы данных перед выполнением миграции!**

```bash
pg_dump dr_mind > backup_before_migration.sql
```

## Текущая структура (старая)

Ваша база имеет таблицу `users` с колонками:

- `user_id` (text, PK)
- `name` (text)
- `history` (jsonb) - массив сообщений
- `summary` (text) - текстовая суммаризация
- `message_count` (integer)
- `message_limit` (integer)
- `voice_enabled` (boolean)
- `created_at`, `updated_at` (timestamps)

## Новая структура

После миграции будет:

- `users` - только метаданные (user_id, name, message_count, timestamps)
- `conversations` - зашифрованные переписки
- `summaries` - отдельная таблица для суммаризаций

## Шаги миграции

### 1. Проверка текущего состояния

```sql
-- Проверьте сколько данных у вас есть
SELECT
    COUNT(*) as total_users,
    COUNT(CASE WHEN history IS NOT NULL AND jsonb_array_length(history) > 0 THEN 1 END) as users_with_history,
    COUNT(CASE WHEN summary IS NOT NULL AND summary != '' THEN 1 END) as users_with_summary
FROM users;
```

### 2. Выполнение миграции

```bash
psql -d dr_mind < migrations/002_migrate_from_old_schema.sql
```

### 3. Проверка результатов

```sql
-- Проверьте что данные мигрировали
SELECT
    (SELECT COUNT(*) FROM users) as total_users,
    (SELECT COUNT(*) FROM conversations) as total_conversations,
    (SELECT COUNT(DISTINCT user_id) FROM conversations) as users_with_conversations,
    (SELECT COUNT(*) FROM summaries) as total_summaries,
    (SELECT COUNT(DISTINCT user_id) FROM summaries) as users_with_summaries;
```

### 4. Проверка конкретного пользователя

```sql
-- Проверьте данные конкретного пользователя
SELECT
    u.user_id,
    u.name,
    u.message_count,
    COUNT(c.id) as conversation_count,
    COUNT(s.id) as summary_count
FROM users u
LEFT JOIN conversations c ON c.user_id = u.user_id
LEFT JOIN summaries s ON s.user_id = u.user_id AND s.is_current = TRUE
WHERE u.user_id = 'YOUR_USER_ID'
GROUP BY u.user_id, u.name, u.message_count;
```

## Важные замечания

### Шифрование данных

⚠️ **ВНИМАНИЕ**: Данные из старой таблицы `history` мигрируются **БЕЗ шифрования** в новую таблицу `conversations`.

Это сделано намеренно, чтобы:

1. Не потерять данные при миграции
2. Не требовать ключ шифрования во время миграции

**Что делать:**

- Новые сообщения будут автоматически шифроваться через приложение
- Старые сообщения останутся незашифрованными
- Если нужно зашифровать старые данные, создайте отдельный скрипт с использованием `ENCRYPTION_KEY`

### Удаление старых колонок

В миграции есть закомментированные команды для удаления старых колонок:

- `history`
- `summary`
- `message_limit`
- `voice_enabled`

**Рекомендация:**

- Сначала убедитесь, что миграция прошла успешно
- Проверьте работу приложения
- Только потом раскомментируйте и выполните удаление колонок

### Откат миграции

Если что-то пошло не так, восстановите из бэкапа:

```bash
psql -d dr_mind < backup_before_migration.sql
```

## После миграции

1. Убедитесь, что приложение работает корректно
2. Проверьте, что новые сообщения сохраняются правильно
3. Проверьте, что суммаризация работает
4. Только после этого удаляйте старые колонки

## Проблемы и решения

### Ошибка "relation already exists"

Таблицы `conversations` или `summaries` уже существуют. Это нормально, миграция использует `CREATE TABLE IF NOT EXISTS`.

### Ошибка "duplicate key value"

Данные уже были мигрированы. Миграция использует `ON CONFLICT DO NOTHING`, так что это безопасно.

### Данные не мигрировались

Проверьте:

1. Есть ли данные в `history` (не NULL и не пустой массив)
2. Есть ли данные в `summary` (не NULL и не пустая строка)
3. Выполните проверочные запросы из шага 3


