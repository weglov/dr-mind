-- Миграция данных из старой схемы в новую
-- ВАЖНО: Выполняйте эту миграцию только если у вас уже есть база со старой схемой!

-- Шаг 1: Создаем новые таблицы (если их еще нет)
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

-- Шаг 2: Добавляем внешние ключи (если таблица users уже существует)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users') THEN
        -- Добавляем внешние ключи только если таблица users существует
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

-- Шаг 3: Создаем индексы
CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_created_at ON conversations(created_at);
CREATE INDEX IF NOT EXISTS idx_summaries_user_id ON summaries(user_id);
CREATE INDEX IF NOT EXISTS idx_summaries_current ON summaries(user_id, is_current) WHERE is_current = TRUE;

-- Шаг 4: Миграция данных из history (jsonb) в conversations
-- ВАЖНО: Данные будут сохранены БЕЗ шифрования в этой миграции
-- Шифрование будет применяться при новых сообщениях через приложение
DO $$
DECLARE
    user_record RECORD;
    msg_record RECORD;
    msg_index INTEGER;
    user_msg TEXT;
    assistant_msg TEXT;
    msg_timestamp TIMESTAMP WITH TIME ZONE;
BEGIN
    -- Проходим по всем пользователям, у которых есть history
    FOR user_record IN 
        SELECT user_id, history 
        FROM users 
        WHERE history IS NOT NULL 
        AND jsonb_typeof(history) = 'array'
        AND jsonb_array_length(history) > 0
    LOOP
        msg_index := 0;
        
        -- Проходим по каждому сообщению в history
        FOR msg_record IN 
            SELECT value FROM jsonb_array_elements(user_record.history)
        LOOP
            -- Извлекаем данные из JSON
            user_msg := (msg_record.value)->>'user';
            assistant_msg := (msg_record.value)->>'assistant';
            
            -- Пытаемся извлечь timestamp, если есть
            BEGIN
                msg_timestamp := ((msg_record.value)->>'timestamp')::TIMESTAMP WITH TIME ZONE;
            EXCEPTION WHEN OTHERS THEN
                msg_timestamp := NOW();
            END;
            
            -- Пропускаем пустые сообщения
            IF (user_msg IS NOT NULL AND user_msg != '') OR 
               (assistant_msg IS NOT NULL AND assistant_msg != '') THEN
                
                -- Вставляем в conversations БЕЗ шифрования
                -- Примечание: В продакшене эти данные должны быть зашифрованы
                -- Но для миграции мы сохраняем их как есть, чтобы не потерять данные
                INSERT INTO conversations (
                    user_id, 
                    message_index, 
                    encrypted_user_message, 
                    encrypted_assistant_message,
                    created_at
                ) VALUES (
                    user_record.user_id,
                    msg_index,
                    COALESCE(user_msg, '[empty]'),  -- Временно без шифрования
                    COALESCE(assistant_msg, '[empty]'),  -- Временно без шифрования
                    COALESCE(msg_timestamp, NOW())
                )
                ON CONFLICT (user_id, message_index) DO NOTHING;
                
                msg_index := msg_index + 1;
            END IF;
        END LOOP;
    END LOOP;
END $$;

-- Шаг 5: Миграция summary в новую таблицу summaries
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
        -- Получаем количество сообщений
        msg_count := COALESCE(user_record.message_count, 0);
        
        -- Вставляем в summaries
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

-- Шаг 6: Удаляем старые колонки (ОПЦИОНАЛЬНО - раскомментируйте если уверены)
-- ВАЖНО: Сначала убедитесь, что данные успешно мигрированы!

-- ALTER TABLE users DROP COLUMN IF EXISTS history;
-- ALTER TABLE users DROP COLUMN IF EXISTS summary;
-- ALTER TABLE users DROP COLUMN IF EXISTS message_limit;
-- ALTER TABLE users DROP COLUMN IF EXISTS voice_enabled;

-- Шаг 7: Проверка миграции (выполните вручную после миграции)
-- SELECT 
--     (SELECT COUNT(*) FROM users) as total_users,
--     (SELECT COUNT(*) FROM conversations) as total_conversations,
--     (SELECT COUNT(*) FROM summaries) as total_summaries;

