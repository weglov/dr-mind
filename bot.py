import os
from dotenv import load_dotenv
import warnings
warnings.filterwarnings('ignore', category=FutureWarning)
warnings.filterwarnings('ignore', message="FP16 is not supported on CPU; using FP32 instead")
from posthog import Posthog
from supabase import create_client, Client
from prompts import (
    THERAPIST_PROMPT,
    RELEVANCE_CHECK_PROMPT,
    RELEVANCE_CHECK_WITH_CONTEXT
)

# Загружаем переменные окружения из .env файла
load_dotenv()

from aiogram import Bot, Dispatcher, types, Router
from aiogram.fsm.storage.memory import MemoryStorage
from pathlib import Path
import whisper
import anthropic
import json
from datetime import datetime
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from aiogram.filters.command import Command
from aiogram import F
from aiogram.enums import ParseMode
import asyncio

# Инициализация ключей API
BOT_TOKEN = os.getenv('BOT_TOKEN')
CLAUDE_API_KEY = os.getenv('CLAUDE_API_KEY')
POSTHOG_API_KEY = os.getenv('POSTHOG_API_KEY')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
CLAUDE_MODEL = os.getenv('CLAUDE_MODEL')

# Инициализация Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Инициализация PostHog
posthog = Posthog(
    project_api_key=POSTHOG_API_KEY,
    host='https://app.posthog.com'  # или ваш self-hosted URL
)

# Инициализация основных компонентов
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
router = Router()
dp = Dispatcher(storage=storage)
dp.include_router(router)
claude = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
whisper_model = whisper.load_model("base")

# Словарь для хранения данных пользователей
user_data = {}

async def load_user_data():
    try:
        response = supabase.table('users').select('*').execute()
        users = {}
        for user in response.data:
            users[str(user['user_id'])] = {
                'name': user['name'],
                'history': user['history']
            }
        return users
    except Exception as e:
        print(f"Error loading user data: {e}")
        return {}

async def save_user_data(user_id: str, user_data: dict):
    try:
        data = {
            'user_id': user_id,
            'name': user_data[user_id]['name'],
            'history': user_data[user_id]['history']
        }
        response = supabase.table('users').upsert(data).execute()
        if hasattr(response, 'error') and response.error:
            print(f"Supabase error: {response.error}")
    except Exception as e:
        print(f"Error saving user data: {str(e)}")
        print(f"Data attempted to save: {data}")

@router.message(Command('start'))
async def start_handler(message: types.Message):
    user_id = str(message.from_user.id)
    if user_id not in user_data:
        user_data[user_id] = {
            "name": message.from_user.first_name,
            "history": []
        }
        await save_user_data(user_id, user_data)
    
    await message.answer("Здравствуйте! Я ваш персональный психолог-терапевт. Как я могу вам помочь сегодня?")

@router.message(F.content_type.in_({'voice', 'audio'}))
async def handle_audio(message: types.Message):
    # Отправляем статус "печатает"
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    user_id = str(message.from_user.id)
    # Проверяем существование пользователя
    if user_id not in user_data:
        user_data[user_id] = {
            "name": message.from_user.first_name,
            "history": []
        }
        await save_user_data(user_id, user_data)
    
    # Скачивание аудиофайла
    file_id = message.voice.file_id if message.voice else message.audio.file_id
    file = await bot.get_file(file_id)
    file_path = file.file_path
    await bot.download_file(file_path, f"audio_{message.from_user.id}.ogg")
    
    # Конвертация аудио в текст с помощью Whisper
    result = whisper_model.transcribe(f"audio_{message.from_user.id}.ogg")
    text = result["text"]
    
    # Проверяем релевантность запроса
    is_relevant, explanation = await is_psychological_query(text, str(message.from_user.id))
    if not is_relevant:
        await message.answer("Извините, но я могу помочь только с вопросами, связанными с психологической помощью и ментальным здоровьем. " + 
                           explanation.replace('no', '').strip())
        return
    
    # Обработка текста через Claude
    response = await process_message(str(message.from_user.id), text)
    await message.answer(response)
    
    # Удаление временного файла
    os.remove(f"audio_{message.from_user.id}.ogg")

async def is_psychological_query(message: str, user_id: str = None) -> tuple[bool, str]:
    # Если есть user_id, получаем историю диалога
    context = ""
    if user_id and user_id in user_data and user_data[user_id]["history"]:
        last_messages = user_data[user_id]["history"][-3:]  # Берем последние 3 сообщения
        context = "\n".join([
            f"User: {msg['user']}\nAssistant: {msg['assistant']}"
            for msg in last_messages
        ])
    
    # Проверяем релевантность запроса через Claude
    response = claude.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        temperature=0.7,
        system=RELEVANCE_CHECK_PROMPT,
        messages=[
            {"role": "user", "content": RELEVANCE_CHECK_WITH_CONTEXT.format(
                context=context,
                message=message
            )}
        ]
    )
    
    response_text = response.content[0].text if isinstance(response.content, list) else response.content
    is_relevant = response_text.lower().startswith('yes')
    return is_relevant, response_text

@router.message(F.content_type == 'text')
async def handle_text(message: types.Message):
    # Проверяем релевантность запроса
    is_relevant, explanation = await is_psychological_query(message.text, str(message.from_user.id))
    if not is_relevant:
        await message.answer("Извините, но я могу помочь только с вопросами, связанными с психологической помощью и ментальным здоровьем. " + 
                           explanation.replace('no', '').strip())
        return
    
    # Отправляем статус "печатает"
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    response = await process_message(str(message.from_user.id), message.text)
    # Отправляем событие в PostHog
    posthog.capture(
        distinct_id=str(message.from_user.id),
        event='message_sent',
        properties={
            'message_type': 'text',
            'username': message.from_user.username,
            'first_name': message.from_user.first_name,
        }
    )
    await message.answer(response)

async def process_message(user_id: str, message: str) -> str:
    # Проверяем существование пользователя
    if user_id not in user_data:
        user_data[user_id] = {
            "name": "Unknown",  # Будет обновлено при следующем взаимодействии
            "history": []
        }
        await save_user_data(user_id, user_data)
    
    # Получение истории пользователя
    user_history = user_data[user_id]["history"]
    
    # Формирование системного промпта
    system_prompt = THERAPIST_PROMPT
    
    # Формируем массив сообщений из истории
    messages = []
    # Добавляем последние 15 сообщений из истории для лучшего контекста
    for h in user_history[-10:]:
        messages.extend([
            {"role": "user", "content": h["user"]},
            {"role": "assistant", "content": h["assistant"]}
        ])
    # Добавляем текущее сообщение
    messages.append({"role": "user", "content": message})
    
    # Получение ответа от Claude
    response = claude.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        temperature=0.7,
        system=system_prompt,
        messages=messages
    )
    
    # Преобразование ответа в строку
    response_text = response.content[0].text if isinstance(response.content, list) else response.content
    
    # Сохранение истории
    user_data[user_id]["history"].append({
        "user": message,
        "assistant": response_text,
        "timestamp": datetime.now().isoformat()
    })
    await save_user_data(user_id, user_data)
    
    return response_text

# Обновляем help handler
@router.message(Command('help'))
async def help_handler(message: types.Message):
    help_text = """
Доступные команды:
/start - Начать диалог
/help - Показать это сообщение

Вы также можете:
- Отправлять текстовые сообщения
- Отправлять голосовые сообщения
    """
    await message.answer(help_text)

if __name__ == '__main__':
    async def main():
        global user_data
        user_data = await load_user_data()
        await dp.start_polling(bot, skip_updates=True)
    asyncio.run(main()) 