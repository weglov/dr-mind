import os
import sys
import logging
from openai import OpenAI
from dotenv import load_dotenv
import warnings
warnings.filterwarnings('ignore', category=FutureWarning)
warnings.filterwarnings('ignore', message="FP16 is not supported on CPU; using FP32 instead")
from posthog import Posthog
from supabase import create_client, Client
from prompts import (
    THERAPIST_PROMPT,
    RELEVANCE_CHECK_PROMPT,
    RELEVANCE_CHECK_WITH_CONTEXT,
    WELCOME_MESSAGE,
    HELP_MESSAGE
)

# Загружаем переменные окружения из .env файла
load_dotenv()

from aiogram import Bot, Dispatcher, types, Router
from aiogram.fsm.storage.memory import MemoryStorage
import anthropic
from datetime import datetime
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from aiogram.filters.command import Command
from aiogram import F
from aiogram.enums import ParseMode
import asyncio
from aiogram.types import LabeledPrice
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout  # Важно для Railway - логи будут видны в консоли
)
logger = logging.getLogger(__name__)

# Инициализация ключей API
BOT_TOKEN = os.getenv('BOT_TOKEN')
CLAUDE_API_KEY = os.getenv('CLAUDE_API_KEY')
POSTHOG_API_KEY = os.getenv('POSTHOG_API_KEY')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
CLAUDE_MODEL = os.getenv('CLAUDE_MODEL')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')


openAiClient = OpenAI(
    api_key=OPENAI_API_KEY,  # This is the default and can be omitted
)

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

# Словарь для хранения данных пользователей
user_data = {}

async def load_user_data():
    try:
        response = supabase.table('users').select('*').execute()
        users = {}
        for user in response.data:
            users[str(user['user_id'])] = {
                'name': user['name'],
                'history': user['history'],
                'message_count': user['message_count'] or 0,
                'premium_since': user['premium_since']
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
            'history': user_data[user_id]['history'],
            'message_count': user_data[user_id].get('message_count', 0),
        }
        response = supabase.table('users').upsert(data).execute()
        if hasattr(response, 'error') and response.error:
            print(f"Supabase error: {response.error}")
    except Exception as e:
        print(f"Error saving user data: {str(e)}")
        print(f"Data attempted to save: {data}")

@router.message(Command('start'))
async def start_handler(message: types.Message):
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Привет, Mindy!", callback_data="hello_mindy")]
    ])
    
    user_id = str(message.from_user.id)
    posthog.capture(
        distinct_id=user_id,
        event='start',
        properties={
            'username': message.from_user.username,
            'first_name': message.from_user.first_name,
        }
    )
    
    await message.answer(
        WELCOME_MESSAGE,
        reply_markup=keyboard
    )

@router.callback_query(F.data == "hello_mindy")
async def hello_mindy_callback(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer(HELP_MESSAGE)

async def update_user_message_count(message: types.Message, user_id: str): 
    # Увеличиваем счетчик сообщений
    user_data[user_id]["message_count"] = user_data[user_id].get("message_count", 0) + 1
    
    # Отправляем событие в PostHog
    posthog.capture(
        distinct_id=user_id,
        event='message_sent',
        properties={
            'message_count': user_data[user_id]["message_count"],
            'is_premium': user_data[user_id].get("is_premium", False),
            'username': message.from_user.username,
            'first_name': message.from_user.first_name,
        }
    )
    
    await save_user_data(user_id, user_data)


async def check_premium_access(message: types.Message, user_id: str) -> bool:
    PRICE = LabeledPrice(label='5 дополнительных сообщений', amount=10)  # Цена в минимальных единицах валюты (например, 100 XTR)

    """
    Проверяет доступ пользователя на основе его премиум-статуса.
    Возвращает True если у пользователя есть доступ, False если нет.
    """
    if user_data[user_id].get("message_count", 0) >= 5:
        # Проверяем, есть ли у пользователя оставшиеся сообщения
        if user_data[user_id].get("remaining_messages", 0) > 0:
            return True
        else:
            posthog.capture(
                distinct_id=user_id,
                event='premium_invoice',
                properties={
                    'message_count': user_data[user_id]["message_count"],
                    'user_id': user_id
                }
            )
                        
            await bot.send_invoice(
                chat_id=message.chat.id,
                title='Покупка дополнительных сообщений',
                description='Получите еще 5 сообщений для использования с ботом.',
                payload='start_param_unique_v1',
                provider_token='',
                currency='XTR', 
                prices=[PRICE],
                start_parameter='get_access',
                need_name=False,
                suggested_tip_amounts=[],
                need_phone_number=False,
                need_email=False,
                need_shipping_address=False,
                is_flexible=False
            )
            return False
    return True

@router.message(F.content_type.in_({'voice', 'audio'}))
async def handle_audio(message: types.Message):
    try:
        user_id = str(message.from_user.id)
        logger.info(f"Получено аудио сообщение от пользователя {user_id}")
        
        # Проверяем существование пользователя
        if user_id not in user_data:
            logger.info(f"Инициализация данных для нового пользователя {user_id}")
            user_data[user_id] = {
                "name": message.from_user.first_name,
                "history": [],
                "message_count": 0,
                "is_premium": False
            }

        # Проверяем премиум доступ
        if not await check_premium_access(message, user_id):
            logger.info(f"Нет премиум доступа для пользователя {user_id}")
            return

        # Отправляем статус "печатает"
        await bot.send_chat_action(chat_id=message.chat.id, action="typing")
        
        # Скачивание аудиофайла
        logger.info("Начинаем скачивание аудиофайла")
        file_id = message.voice.file_id if message.voice else message.audio.file_id
        file = await bot.get_file(file_id)
        file_path = file.file_path
        local_file_path = f"audio_{message.from_user.id}.ogg"
        await bot.download_file(file_path, local_file_path)
        logger.info(f"Аудиофайл сохранен локально: {local_file_path}")
        
        # Конвертация аудио в текст с помощью Whisper
        logger.info("Начинаем транскрибацию через Whisper")
        try:
           with open(local_file_path, "rb") as audio_file:
                result = await openAiClient.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                )
                text = result.text  # получаем текст из результата
                logger.info(f"Успешная транскрибация. Получен текст: {text[:100]}...")
        except Exception as e:
            logger.error(f"Ошибка при транскрибации: {str(e)}", exc_info=True)
            await message.answer("Извините, произошла ошибка при обработке аудио. Пожалуйста, попробуйте еще раз или отправьте текстовое сообщение.")
            return
        
        # Проверяем релевантность запроса
        logger.info("Проверяем релевантность запроса")
        is_relevant, explanation = await is_psychological_query(text, str(message.from_user.id))
        if not is_relevant:
            logger.info(f"Запрос нерелевантен: {explanation}")
            await message.answer("Извините, но я могу помочь только с вопросами, связанными с психологической помощью и ментальным здоровьем. " + 
                               explanation.replace('no', '').strip())
            return
        
        # Обработка текста через Claude
        logger.info("Отправляем запрос в Claude")
        response = await process_message(str(message.from_user.id), text)
        await message.answer(response)
        
        # Удаление временного файла
        try:
            os.remove(local_file_path)
            logger.info(f"Временный файл {local_file_path} удален")
        except Exception as e:
            logger.error(f"Ошибка при удалении временного файла: {str(e)}")
            
    except Exception as e:
        logger.error(f"Общая ошибка в handle_audio: {str(e)}", exc_info=True)
        await message.answer("Произошла ошибка при обработке аудио сообщения. Пожалуйста, попробуйте позже.")
    finally:
        # Попытка удалить временный файл в любом случае
        try:
            if 'local_file_path' in locals():
                os.remove(local_file_path)
        except:
            pass

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
    user_id = str(message.from_user.id)
    
    # Получаем или инициализируем данные пользователя
    if user_id not in user_data:
        user_data[user_id] = {
            "name": message.from_user.first_name,
            "history": [],
            "message_count": 0,
            "is_premium": False
        }
        
        await save_user_data(user_id, user_data)
    
    # Проверяем премиум доступ
    if not await check_premium_access(message, user_id):
        return
    
    # Существующая логика обработки сообщений...
    is_relevant, explanation = await is_psychological_query(message.text, user_id)
    if not is_relevant:
        await message.answer("Извините, но я могу помочь только с вопросами, связанными с психологической помощью и ментальным здоровьем. " + 
                           explanation.replace('no', '').strip())
        return
    
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    await update_user_message_count(message, user_id)
    response = await process_message(user_id, message.text)
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

@router.callback_query(F.data == "send_star")
async def handle_star_button(callback: types.CallbackQuery):
    user_id = str(callback.from_user.id)
    await callback.answer()
    
    # Добавляем 5 сообщений пользователю после отправки Star
    user_data[user_id]["remaining_messages"] = user_data[user_id].get("remaining_messages", 0) + 5
    await save_user_data(user_id, user_data)
    
    await callback.message.edit_text(
        "Спасибо за поддержку! Вы получили еще 5 сообщений."
    )

async def main():
    try:
        logger.info("Starting bot...")
        global user_data
        
        logger.info("Loading user data...")
        user_data = await load_user_data()
        
        logger.info("Starting polling...")
        await dp.start_polling(bot, skip_updates=True)
    except Exception as e:
        logger.error(f"Critical error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    logger.info("Starting main function...")
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Main function error: {e}", exc_info=True)
        sys.exit(1)