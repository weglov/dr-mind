# Используем официальный образ Python
FROM python:3.12-slim

# Устанавливаем рабочую директорию в контейнере
WORKDIR /app

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
  ffmpeg \
  git \
  && rm -rf /var/lib/apt/lists/*

# Копируем файлы зависимостей
COPY requirements.txt .

# Устанавливаем зависимости Python
RUN pip install --no-cache-dir -r requirements.txt

# Предварительно загружаем модель whisper
RUN python -c "import whisper; whisper.load_model('base')"

# Копируем остальные файлы проекта
COPY . .

# Запускаем бота
CMD ["python", "bot.py"]