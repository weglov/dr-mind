# Dr. Mind - Telegram Bot

Telegram бот для психологической поддержки на Go.

## Возможности

- 🤖 Психологическая поддержка через AI (Claude)
- 💬 Мультимодальность: текст, голос, аудио, видео-кружки
- 📝 История диалогов с автоматической суммаризацией
- 🔒 Шифрование переписок в базе данных
- 📅 Еженедельные рассылки пользователям

## Требования

- Go 1.21+
- PostgreSQL
- Переменные окружения (см. ниже)

## Установка

1. Клонируйте репозиторий
2. Установите зависимости:
```bash
go mod download
```

3. Создайте базу данных и выполните миграции:
```bash
psql -d your_database < migrations/001_initial.sql
```

4. Настройте переменные окружения (создайте `.env` файл):
```env
BOT_TOKEN=your_telegram_bot_token
CLAUDE_API_KEY=your_claude_api_key
CLAUDE_MODEL=claude-3-5-sonnet-20241022
DATABASE_URL=postgres://user:password@localhost/dbname
ENCRYPTION_KEY=your_encryption_key_32_chars_minimum
```

5. Соберите и запустите:
```bash
go build ./cmd/bot
./bot
```

## Структура проекта

```
dr_mind/
├── cmd/bot/          # Точка входа
├── internal/
│   ├── config/       # Конфигурация
│   ├── crypto/       # Шифрование
│   ├── handlers/     # Обработчики сообщений
│   ├── prompts/      # Промпты для Claude
│   ├── repository/   # Работа с БД
│   ├── scheduler/    # Планировщик задач
│   └── services/     # Бизнес-логика
├── pkg/telegram/     # Telegram клиент
└── migrations/       # SQL миграции
```

## Особенности

- **Шифрование**: Все переписки хранятся в зашифрованном виде в БД
- **Суммаризация**: Автоматическая суммаризация диалогов каждые 15 сообщений
- **Отдельная таблица суммаризаций**: Суммаризации хранятся отдельно для быстрого доступа

## Docker

Если используете Docker:

```bash
docker build -t dr_mind .
docker run --env-file .env dr_mind
```

