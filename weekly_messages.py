import random
from aiogram import Bot
import asyncio
from config import bot_token
import sqlite3

# Список фраз для рассылки
WEEKLY_MESSAGES = [
    "Привет, как дела?",
    "Приветик, как ты?",
    "Привет, как прошла неделя?",
    "Привет, как настроение?",
    "Привет, как твои успехи? 💪",
    "Надеюсь, у тебя всё хорошо! ❤️",
    "Не забывай заботиться о себе! 🌺"
]

async def send_weekly_messages():
    bot = Bot(token=bot_token)
    
    # Подключаемся к базе данных
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    
    # Получаем всех пользователей
    cursor.execute('SELECT user_id FROM users')
    users = cursor.fetchall()
    
    # Отправляем случайное сообщение каждому пользователю
    for user in users:
        try:
            message = random.choice(WEEKLY_MESSAGES)
            await bot.send_message(chat_id=user[0], text=message)
            await asyncio.sleep(0.1)  # Небольшая задержка между отправками
        except Exception as e:
            print(f"Ошибка при отправке сообщения пользователю {user[0]}: {e}")
    
    conn.close()
    await bot.session.close()

if __name__ == "__main__":
    asyncio.run(send_weekly_messages()) 