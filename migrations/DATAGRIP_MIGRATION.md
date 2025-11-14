# Миграция через DataGrip

## Шаг 1: Откройте файл миграции в DataGrip

1. Откройте DataGrip
2. Подключитесь к вашей базе данных Railway (или другой)
3. Откройте файл `migrations/002_migrate_from_old_schema.sql` в DataGrip

## Шаг 2: Выполнение миграции

### Вариант A: Выполнить весь файл сразу

1. Откройте файл `002_migrate_from_old_schema.sql` в DataGrip
2. Убедитесь, что в правом верхнем углу выбран правильный Data Source (ваша база Railway)
3. Нажмите `Ctrl+Enter` (или `Cmd+Enter` на Mac) - это выполнит весь скрипт
4. Или выделите весь текст (`Ctrl+A`) и нажмите `Ctrl+Enter`

### Вариант B: Выполнить по частям (рекомендуется)

Выполняйте миграцию по блокам, чтобы видеть прогресс:

#### Блок 1: Создание таблиц

```sql
-- Скопируйте и выполните этот блок
CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    message_index INTEGER NOT NULL,
    encrypted_user_message TEXT NOT NULL,
    encrypted_assistant_message TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, message_index)
);

CREATE TABLE IF NOT EXISTS summaries (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    summary_text TEXT NOT NULL,
    message_count_at_summary INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    is_current BOOLEAN DEFAULT TRUE
);
```

#### Блок 2: Добавление внешних ключей

```sql
-- Выполните этот блок
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users') THEN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.table_constraints
            WHERE constraint_name = 'conversations_user_id_fkey'
        ) THEN
            ALTER TABLE conversations
            ADD CONSTRAINT conversations_user_id_fkey
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE;
        END IF;

        IF NOT EXISTS (
            SELECT 1 FROM information_schema.table_constraints
            WHERE constraint_name = 'summaries_user_id_fkey'
        ) THEN
            ALTER TABLE summaries
            ADD CONSTRAINT summaries_user_id_fkey
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE;
        END IF;
    END IF;
END $$;
```

#### Блок 3: Создание индексов

```sql
-- Выполните этот блок
CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_created_at ON conversations(created_at);
CREATE INDEX IF NOT EXISTS idx_summaries_user_id ON summaries(user_id);
CREATE INDEX IF NOT EXISTS idx_summaries_current ON summaries(user_id, is_current) WHERE is_current = TRUE;
```

#### Блок 4: Миграция данных из history

```sql
-- Выполните этот блок - он перенесет все сообщения из history в conversations
DO $$
DECLARE
    user_record RECORD;
    msg_record RECORD;
    msg_index INTEGER;
    user_msg TEXT;
    assistant_msg TEXT;
    msg_timestamp TIMESTAMP WITH TIME ZONE;
BEGIN
    FOR user_record IN
        SELECT user_id, history
        FROM users
        WHERE history IS NOT NULL
        AND jsonb_typeof(history) = 'array'
        AND jsonb_array_length(history) > 0
    LOOP
        msg_index := 0;

        FOR msg_record IN
            SELECT value FROM jsonb_array_elements(user_record.history)
        LOOP
            user_msg := (msg_record.value)->>'user';
            assistant_msg := (msg_record.value)->>'assistant';

            BEGIN
                msg_timestamp := ((msg_record.value)->>'timestamp')::TIMESTAMP WITH TIME ZONE;
            EXCEPTION WHEN OTHERS THEN
                msg_timestamp := NOW();
            END;

            IF (user_msg IS NOT NULL AND user_msg != '') OR
               (assistant_msg IS NOT NULL AND assistant_msg != '') THEN

                INSERT INTO conversations (
                    user_id,
                    message_index,
                    encrypted_user_message,
                    encrypted_assistant_message,
                    created_at
                ) VALUES (
                    user_record.user_id,
                    msg_index,
                    COALESCE(user_msg, '[empty]'),
                    COALESCE(assistant_msg, '[empty]'),
                    COALESCE(msg_timestamp, NOW())
                )
                ON CONFLICT (user_id, message_index) DO NOTHING;

                msg_index := msg_index + 1;
            END IF;
        END LOOP;
    END LOOP;
END $$;
```

#### Блок 5: Миграция summary

```sql
-- Выполните этот блок - он перенесет все суммаризации
DO $$
DECLARE
    user_record RECORD;
    msg_count INTEGER;
BEGIN
    FOR user_record IN
        SELECT user_id, summary, message_count
        FROM users
        WHERE summary IS NOT NULL
        AND summary != ''
    LOOP
        msg_count := COALESCE(user_record.message_count, 0);

        INSERT INTO summaries (
            user_id,
            summary_text,
            message_count_at_summary,
            is_current
        ) VALUES (
            user_record.user_id,
            user_record.summary,
            msg_count,
            TRUE
        )
        ON CONFLICT DO NOTHING;
    END LOOP;
END $$;
```

## Шаг 3: Проверка результатов

Выполните этот запрос, чтобы проверить что миграция прошла успешно:

```sql
SELECT
    (SELECT COUNT(*) FROM users) as total_users,
    (SELECT COUNT(*) FROM conversations) as total_conversations,
    (SELECT COUNT(DISTINCT user_id) FROM conversations) as users_with_conversations,
    (SELECT COUNT(*) FROM summaries) as total_summaries,
    (SELECT COUNT(DISTINCT user_id) FROM summaries) as users_with_summaries;
```

## Шаг 4: Проверка конкретного пользователя

Проверьте данные конкретного пользователя:

```sql
SELECT
    u.user_id,
    u.name,
    u.message_count,
    COUNT(c.id) as conversation_count,
    COUNT(s.id) as summary_count
FROM users u
LEFT JOIN conversations c ON c.user_id = u.user_id
LEFT JOIN summaries s ON s.user_id = u.user_id AND s.is_current = TRUE
WHERE u.user_id = 'YOUR_USER_ID_HERE'  -- Замените на реальный user_id
GROUP BY u.user_id, u.name, u.message_count;
```

## Полезные горячие клавиши в DataGrip

- `Ctrl+Enter` (или `Cmd+Enter` на Mac) - выполнить запрос
- `Ctrl+Shift+Enter` - выполнить весь скрипт
- `Ctrl+Space` - автодополнение
- `F5` - выполнить и показать результат

## Если что-то пошло не так

1. Проверьте логи выполнения в нижней панели DataGrip
2. Убедитесь, что вы подключены к правильной базе данных
3. Проверьте, что таблица `users` существует и содержит данные
