# Инструкция по запуску Dr. Mind Bot

## Шаг 1: Подготовка базы данных

1. Установите PostgreSQL (если еще не установлен):

   ```bash
   # macOS
   brew install postgresql
   brew services start postgresql

   # Linux (Ubuntu/Debian)
   sudo apt-get install postgresql
   sudo systemctl start postgresql
   ```

2. Создайте базу данных:

   ```bash
   createdb dr_mind
   # или через psql:
   psql -c "CREATE DATABASE dr_mind;"
   ```

3. Выполните миграции:
   ```bash
   psql -d dr_mind < migrations/001_initial.sql
   ```

## Шаг 2: Получение API ключей

### Telegram Bot Token

1. Откройте Telegram и найдите [@BotFather](https://t.me/BotFather)
2. Отправьте команду `/newbot`
3. Следуйте инструкциям и получите токен
4. Скопируйте токен (выглядит как `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### Claude API Key

1. Зайдите на https://console.anthropic.com/
2. Зарегистрируйтесь или войдите
3. Перейдите в раздел API Keys
4. Создайте новый ключ и скопируйте его

### Ключ шифрования

Сгенерируйте случайную строку (минимум 32 символа):

```bash
# macOS/Linux
openssl rand -base64 32
```

## Шаг 3: Настройка переменных окружения

1. Скопируйте пример файла:

   ```bash
   cp .env.example .env
   ```

2. Откройте `.env` и заполните все переменные:
   ```env
   BOT_TOKEN=ваш_токен_от_BotFather
   CLAUDE_API_KEY=ваш_ключ_от_Claude
   CLAUDE_MODEL=claude-3-5-sonnet-20241022
   DATABASE_URL=postgres://user:password@localhost:5432/dr_mind
   ENCRYPTION_KEY=ваш_сгенерированный_ключ_шифрования
   ```

## Шаг 4: Установка зависимостей

```bash
go mod download
```

## Шаг 5: Запуск бота

### Вариант 1: Прямой запуск

```bash
go run ./cmd/bot
```

### Вариант 2: Сборка и запуск

```bash
go build ./cmd/bot
./bot
```

## Шаг 6: Проверка работы

1. Откройте Telegram
2. Найдите вашего бота по имени, которое вы указали в BotFather
3. Отправьте команду `/start`
4. Бот должен ответить приветственным сообщением

## Возможные проблемы

### Ошибка подключения к БД

- Проверьте, что PostgreSQL запущен: `pg_isready`
- Проверьте правильность DATABASE_URL
- Убедитесь, что база данных создана

### Ошибка "ENCRYPTION_KEY is required"

- Убедитесь, что в `.env` файле указан ENCRYPTION_KEY
- Ключ должен быть минимум 32 символа

### Бот не отвечает

- Проверьте правильность BOT_TOKEN
- Убедитесь, что бот запущен (смотрите логи)
- Проверьте, что у бота есть доступ к интернету

## Логи

Бот выводит логи в консоль. Вы увидите:

- `Starting bot...` - бот запускается
- `Authorized on account @your_bot_name` - успешная авторизация
- `Starting polling...` - бот начал получать сообщения

## Остановка бота

Нажмите `Ctrl+C` для graceful shutdown.
