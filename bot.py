import os
import sys
import logging
from openai import OpenAI, AsyncOpenAI
from dotenv import load_dotenv
import warnings
warnings.filterwarnings('ignore', category=FutureWarning)
warnings.filterwarnings('ignore', message="FP16 is not supported on CPU; using FP32 instead")
from posthog import Posthog
from supabase import create_client, Client
from config import (
    PRICING_PLANS,
    PURCHASE_MESSAGE,
    WELCOME_MESSAGE,
    HELP_MESSAGE,
    BALANCE_MESSAGE,
    BALANCE_STATUS_MESSAGES,
    FREE_MESSAGES
)
from base64 import b64encode
from typing import BinaryIO
from prompts import (
    THERAPIST_PROMPT,
    RELEVANCE_CHECK_PROMPT,
    RELEVANCE_CHECK_WITH_CONTEXT,
)

# Загружаем переменные окружения из .env файла
load_dotenv()

# Инициализация ключей API
BOT_TOKEN = os.getenv('BOT_TOKEN')
CLAUDE_API_KEY = os.getenv('CLAUDE_API_KEY')
POSTHOG_API_KEY = os.getenv('POSTHOG_API_KEY')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
CLAUDE_MODEL = os.getenv('CLAUDE_MODEL')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
TTS_MODEL = os.getenv('TTS_MODEL', 'gpt-4o-mini-tts')  # Используем gpt-4o-mini-tts по умолчанию

# Получаем и обрабатываем список ID администраторов из переменных окружения
admin_ids_env = os.getenv('ADMIN_IDS', '')
ADMIN_IDS = [admin_id.strip() for admin_id in admin_ids_env.split(',') if admin_id.strip()]

# Если ADMIN_IDS пустой, выводим предупреждение
if not ADMIN_IDS:
    print("Внимание: Список администраторов пуст. Укажите ID администраторов в переменной ADMIN_IDS через запятую.")
    ADMIN_IDS = []  # Устанавливаем пустой список, чтобы избежать ошибок

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
from scheduler import setup_scheduler

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout  # Важно для Railway - логи будут видны в консоли
)
logger = logging.getLogger(__name__)

openAiClient = OpenAI(
    api_key=OPENAI_API_KEY,  # This is the default and can be omitted
)

asyncOpenAiClient = AsyncOpenAI(
    api_key=OPENAI_API_KEY,
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
dp = Dispatcher(storage=storage)
router = Router()
# Регистрируем роутер после создания всех обработчиков в main()
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
                'summary': user.get('summary', ''),
                'message_limit': user.get('message_limit', 5),
                'voice_enabled': user.get('voice_enabled', False),
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
            'summary': user_data[user_id].get('summary', ''),
            'message_limit': user_data[user_id].get('message_limit', 5),
            'voice_enabled': user_data[user_id].get('voice_enabled', False),
        }
        response = supabase.table('users').upsert(data).execute()
        if hasattr(response, 'error') and response.error:
            print(f"Supabase error: {response.error}")
    except Exception as e:
        print(f"Error saving user data: {str(e)}")
        print(f"Data attempted to save: {data}")

async def generate_voice_message(text: str) -> str:
    """Генерирует голосовое сообщение из текста и возвращает путь к аудиофайлу"""
    try:
        # Генерируем уникальное имя файла
        file_path = f"voice_message_{hash(text + str(datetime.now()))}.ogg"
        
        logger.info(f"Генерация голосового сообщения: {text[:30]}...")
        
        # Инструкция для голоса
        instructions = """
        Voice Affect: Calm, Asian accent, and reassuring; project quiet authority and confidence.

Tone: Sincere, empathetic, and gently authoritative—express genuine apology while conveying competence.

Pacing: Steady and moderate; unhurried enough to communicate care, yet efficient enough to demonstrate professionalism.

Emotion: Genuine empathy and understanding; speak with warmth, especially during apologies ("I'm very sorry for any disruption...").

Pronunciation: Clear and precise, emphasizing key reassurances ("smoothly," "quickly," "promptly") to reinforce confidence.

Pauses: Brief pauses after offering assistance or requesting details, highlighting willingness to listen and support.
        """
        
        # Создаем голосовое сообщение с моделью из переменной окружения
        response = await asyncOpenAiClient.audio.speech.create(
            model=TTS_MODEL,
            voice="nova", 
            input=text,
            instructions=instructions,
            response_format="opus"
        )
        
        logger.info(f"Голосовое сообщение успешно сгенерировано, сохраняем в файл {file_path}")
        
        # Сохраняем в файл
        with open(file_path, 'wb') as f:
            for chunk in response.iter_bytes():
                f.write(chunk)
        
        logger.info(f"Голосовое сообщение сохранено как {file_path}")
        return file_path
        
    except Exception as e:
        logger.error(f"Ошибка при создании голосового сообщения: {str(e)}", exc_info=True)
        return None

async def send_voice_message(user_id, voice_file_path, text=None):
    """
    Отправляет голосовое сообщение пользователю
    
    Args:
        user_id: ID пользователя
        voice_file_path: Путь к файлу голосового сообщения
        text: Текст сообщения (для логирования)
    
    Returns:
        bool: Успешно ли отправлено сообщение
    """
    try:
        if not os.path.exists(voice_file_path):
            logger.error(f"Файл голосового сообщения не существует: {voice_file_path}")
            return False
        
        logger.info(f"Отправляю голосовое сообщение пользователю {user_id}")
        await bot.send_voice(
            chat_id=user_id,
            voice=types.FSInputFile(voice_file_path)
        )
        logger.info(f"Голосовое сообщение успешно отправлено пользователю {user_id}")
        return True
    except Exception as e:
        short_text = text[:50] + "..." if text and len(text) > 50 else "нет текста"
        logger.error(f"Ошибка при отправке голосового сообщения пользователю {user_id} (текст: {short_text}): {e}")
        return False

async def initialize_user_data(user_id: str, first_name: str) -> None:
    """Инициализация данных пользователя если их нет"""
    if user_id not in user_data:
        user_data[user_id] = {
            "name": first_name,
            "history": [],
            "message_count": 0,
            "message_limit": FREE_MESSAGES,
            "voice_enabled": True
        }
        await save_user_data(user_id, user_data)

@router.message(Command('start'))
async def start_handler(message: types.Message):
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Привет, Mindy!", callback_data="hello_mindy")]
    ])
    
    user_id = str(message.from_user.id)
    
    # Инициализация данных пользователя
    await initialize_user_data(user_id, message.from_user.first_name)
    
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
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True
    )

@router.callback_query(F.data == "hello_mindy")
async def hello_mindy_callback(callback: types.CallbackQuery):
    await callback.answer()


    await callback.message.answer(HELP_MESSAGE, parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True)

async def update_user_message_count(message: types.Message, user_id: str): 
    # Определяем тип сообщения
    if message.content_type == 'text':
        message_type = 'text'
    elif message.voice:
        message_type = 'voice'
    elif message.audio:
        message_type = 'audio'
    elif message.video_note:
        message_type = 'video_note'
    elif message.photo:
        message_type = 'photo'
    elif message.document and message.document.mime_type.startswith('image/'):
        message_type = 'document_image'
    else:
        message_type = 'unknown'

    # Увеличиваем счетчик сообщений
    user_data[user_id]["message_count"] = user_data[user_id].get("message_count", 0) + 1
    
    # Отправляем событие в PostHog
    posthog.capture(
        distinct_id=user_id,
        event='message_sent',
        properties={
            'message_type': message_type,
            'message_count': user_data[user_id]["message_count"],
            'message_limit': user_data[user_id].get("message_limit", 5),
            'username': message.from_user.username,
            'first_name': message.from_user.first_name,
        }
    )
    
    await save_user_data(user_id, user_data)


async def check_premium_access(message: types.Message, user_id: str) -> bool:
    # Список команд, которые должны быть доступны всегда
    free_commands = ['/balance', '/buy', '/help', '/start']
    
    # Проверяем, является ли сообщение одной из бесплатных команд
    if message.text and message.text in free_commands:
        return True
        
    # Перепроверяем количество сообщений в базе данных
    try:
        response = supabase.table('users').select('message_count, message_limit').eq('user_id', user_id).single().execute()
        if response.data:
            actual_message_count = response.data.get('message_count', 0)
            message_limit = response.data.get('message_limit', 5)
            # Обновляем локальные значения
            user_data[user_id]["message_count"] = actual_message_count
            user_data[user_id]["message_limit"] = message_limit
            logger.info(f"Перепроверка данных для пользователя {user_id}: count={actual_message_count}, limit={message_limit}")
        else:
            logger.warning(f"Пользователь {user_id} не найден в базе данных при перепроверке")
            actual_message_count = 0
            message_limit = 5
    except Exception as e:
        logger.error(f"Ошибка при перепроверке данных: {str(e)}")
        actual_message_count = user_data[user_id].get("message_count", 0)
        message_limit = 5

    if actual_message_count >= message_limit:
        posthog.capture(
            distinct_id=user_id,
            event='premium_invoice',
            properties={
                'message_count': actual_message_count,
                'message_limit': message_limit,
                'user_id': user_id
            }
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=PRICING_PLANS['basic']['button_text'], 
                callback_data=PRICING_PLANS['basic']['callback_data']
            )],
            [InlineKeyboardButton(
                text=PRICING_PLANS['premium']['button_text'], 
                callback_data=PRICING_PLANS['premium']['callback_data']
            )],
            [InlineKeyboardButton(
                text=PRICING_PLANS['unlimited']['button_text'], 
                callback_data=PRICING_PLANS['unlimited']['callback_data']
            )]
        ])

        is_free = message_limit == 5  # Базовый лимит = бесплатные сообщения

        if is_free:
            await message.answer("🌟 Привет! Твои бесплатные сообщения закончились, но не переживай!\n\n"
                               "Чтобы продолжить наше общение, ты можешь выбрать один из удобных пакетов сообщений. "
                               "Я буду очень рада продолжить помогать тебе! 💫\n\n"
                               "Выбери подходящий вариант ниже 👇")
        else:
            await message.answer("🌟 Привет! У тебя закончились сообщения в текущем пакете.\n\n"
                               "Чтобы продолжить наше общение, ты можешь приобрести дополнительные сообщения. "
                               "Я буду рада продолжить помогать тебе! 💫\n\n"
                               "Выбери подходящий вариант ниже 👇")
        
        await message.answer(
            PURCHASE_MESSAGE.format(
                basic_messages=PRICING_PLANS['basic']['messages'],
                basic_stars=PRICING_PLANS['basic']['stars'],
                basic_price_usd=PRICING_PLANS['basic']['price_usd'],
                premium_messages=PRICING_PLANS['premium']['messages'],
                premium_stars=PRICING_PLANS['premium']['stars'],
                premium_price_usd=PRICING_PLANS['premium']['price_usd'],
                unlimited_stars=PRICING_PLANS['unlimited']['stars'],
                unlimited_price_usd=PRICING_PLANS['unlimited']['price_usd']
            ),
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )
        return False
    return True

# Обновляем обработчики для всех тарифов
@router.callback_query(F.data == "buy_10")
async def buy_10_messages(callback: types.CallbackQuery):
    await process_purchase(callback, 'basic')

@router.callback_query(F.data == "buy_50")
async def buy_50_messages(callback: types.CallbackQuery):
    await process_purchase(callback, 'premium')

@router.callback_query(F.data == "buy_unlimited")
async def buy_unlimited_messages(callback: types.CallbackQuery):
    await process_purchase(callback, 'unlimited')

# Общая функция для обработки покупок
async def process_purchase(callback: types.CallbackQuery, plan_type: str):
    await callback.answer()
    plan = PRICING_PLANS[plan_type]
    await bot.send_invoice(
        chat_id=callback.message.chat.id,
        title=plan['invoice_title'],
        description=plan['invoice_description'],
        payload=f'buy_{plan_type}',
        provider_token='',  # Ваш токен платежной системы
        currency='XTR',
        prices=[LabeledPrice(label=plan['label'], amount=plan['stars'])],
        start_parameter=f'get_access_{plan_type}',
        need_name=False,
        suggested_tip_amounts=[],
        need_phone_number=False,
        need_email=False,
        need_shipping_address=False,
        is_flexible=False
    )

@router.message(F.content_type.in_({'voice', 'audio', 'video_note'}))
async def handle_audio(message: types.Message):
    try:
        user_id = str(message.from_user.id)
        
        # Инициализация данных пользователя
        await initialize_user_data(user_id, message.from_user.first_name)
        
        # Определяем тип сообщения
        message_type = 'voice' if message.voice else ('audio' if message.audio else 'video_note')
        logger.info(f"Получено {message_type} сообщение от пользователя {user_id}")
        
        # Логируем в PostHog тип полученного сообщения
        posthog.capture(
            distinct_id=user_id,
            event='message_received',
            properties={
                'message_type': message_type,
                'username': message.from_user.username,
                'first_name': message.from_user.first_name,
                'message_count': user_data[user_id].get("message_count", 0),
                'message_limit': user_data[user_id].get("message_limit", 5)
            }
        )

        # Проверяем премиум доступ
        if not await check_premium_access(message, user_id):
            logger.info(f"Нет премиум доступа для пользователя {user_id}")
            return

        # Отправляем статус "печатает"
        await bot.send_chat_action(chat_id=message.chat.id, action="typing")
        
        # Обновляем счетчик сообщений
        await update_user_message_count(message, user_id)
        
        # Обновляем логику получения file_id
        if message.voice:
            file_id = message.voice.file_id
        elif message.audio:
            file_id = message.audio.file_id
        else:  # video_note
            file_id = message.video_note.file_id
            
        file = await bot.get_file(file_id)
        file_path = file.file_path
        
        # Для видеосообщений сохраняем как .mp4
        if message.video_note:
            local_file_path = f"video_{message.from_user.id}.mp4"
        else:
            local_file_path = f"audio_{message.from_user.id}.ogg"
            
        await bot.download_file(file_path, local_file_path)
        logger.info(f"Файл сохранен локально: {local_file_path}")
        
        # Конвертация в текст с помощью Whisper
        logger.info("Начинаем транскрибацию через Whisper")
        try:
            with open(local_file_path, "rb") as media_file:
                result = openAiClient.audio.transcriptions.create(
                    model="whisper-1",
                    file=media_file,
                )
                text = result.text
                logger.info(f"Успешная транскрибация. Получен текст: {text[:100]}...")
        except Exception as e:
            logger.error(f"Ошибка при транскрибации: {str(e)}", exc_info=True)
            await message.answer("Извините, произошла ошибка при обработке сообщения. Пожалуйста, попробуйте еще раз или отправьте текстовое сообщение.")
            return
        
        # Проверяем релевантность запроса
        logger.info("Проверяем релевантность запроса")
        is_relevant, explanation = await is_psychological_query(text, str(message.from_user.id))
        if not is_relevant:
            # Логируем нерелевантный запрос
            posthog.capture(
                distinct_id=user_id,
                event='irrelevant_message',
                properties={
                    'message_text': text,
                    'message_type': message_type,
                    'explanation': explanation,
                    'username': message.from_user.username,
                    'first_name': message.from_user.first_name,
                    'message_count': user_data[user_id].get("message_count", 0),
                    'message_limit': user_data[user_id].get("message_limit", 5)
                }
            )
            logger.info(f"Нерелевантный аудио запрос от пользователя {user_id}: {text} | Объяснение: {explanation}")
            
            await message.answer("Извините, но я могу помочь только с вопросами, связанными с психологической помощью и ментальным здоровьем. " + 
                               explanation.replace('no', '').strip())
            return
        
        # Обработка текста через Claude
        logger.info("Отправляем запрос в Claude")
        response = await process_message(str(message.from_user.id), text)
        
        # Проверяем, включены ли голосовые сообщения для этого пользователя
        voice_enabled = user_data[user_id].get('voice_enabled', False)
        
        # ИЗМЕНЕНО: Отправляем либо голосовое, либо текстовое сообщение в зависимости от настройки
        if voice_enabled:
            # Отправляем статус записи голосового сообщения
            await bot.send_chat_action(chat_id=message.chat.id, action="record_voice")
            
            try:
                voice_file_path = await generate_voice_message(response)
                if voice_file_path:
                    await send_voice_message(user_id, voice_file_path, response)
                    # Удаляем временный файл
                    try:
                        os.remove(voice_file_path)
                    except Exception as e:
                        logger.error(f"Ошибка при удалении временного файла: {e}")
            except Exception as e:
                logger.error(f"Ошибка при отправке голосового сообщения: {e}", exc_info=True)
                # Если не удалось отправить голосовое, отправляем текстовое как запасной вариант
                await message.answer(response)
        else:
            # Отправляем только текстовый ответ
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
            f"User: {msg.get('user', '')}\nAssistant: {msg.get('assistant', '')}"
            for msg in last_messages
            if msg.get('user') is not None and msg.get('assistant') is not None
        ])

    logger.info(f"Контекст для проверки релевантности: {context[:100]}...")
    
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

# Добавляем фильтр для обычных текстовых сообщений (не команд)
@router.message(F.content_type == 'text', ~F.text.startswith('/'))
async def handle_text(message: types.Message, state: FSMContext):
    user_id = str(message.from_user.id)
    
    # Проверка на админское состояние перенесена в специальные обработчики
    # Проверяем состояние только для логирования
    current_state = await state.get_state()
    logger.info(f"Обработка сообщения. Пользователь {user_id}, состояние: {current_state}")
    
    # Инициализация данных пользователя
    await initialize_user_data(user_id, message.from_user.first_name)
    
    # Логируем получение текстового сообщения
    posthog.capture(
        distinct_id=user_id,
        event='message_received',
        properties={
            'message_type': 'text',
            'username': message.from_user.username,
            'first_name': message.from_user.first_name,
            'message_count': user_data[user_id].get("message_count", 0),
            'message_limit': user_data[user_id].get("message_limit", 5),
            'message_length': len(message.text)
        }
    )
    
    # Проверяем премиум доступ
    if not await check_premium_access(message, user_id):
        return
    
    # Пропускаем проверку релевантности для команд
    if message.text.startswith('/'):
        await message.answer("Извини, я не знаю такой команды. Используй /help чтобы увидеть список доступных команд 😊")
        return
        
    # Существующая логика обработки сообщений...
    is_relevant, explanation = await is_psychological_query(message.text, user_id)
    if not is_relevant:
        # Логируем нерелевантный запрос
        posthog.capture(
            distinct_id=user_id,
            event='irrelevant_message',
            properties={
                'message_text': message.text,
                'explanation': explanation,
                'username': message.from_user.username,
                'first_name': message.from_user.first_name,
                'message_count': user_data[user_id].get("message_count", 0),
                'message_limit': user_data[user_id].get("message_limit", 5)
            }
        )
        logger.info(f"Нерелевантный запрос от пользователя {user_id}: {message.text} | Объяснение: {explanation}")
        
        await message.answer("Извините, но я могу помочь только с вопросами, связанными с психологической помощью и ментальным здоровьем. " + 
                           explanation.replace('no', '').strip())
        return
    
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    await update_user_message_count(message, user_id)
    response = await process_message(user_id, message.text)
    
    # Если voice_enabled отсутствует в данных, устанавливаем в True
    if 'voice_enabled' not in user_data[user_id]:
        user_data[user_id]['voice_enabled'] = True
        await save_user_data(user_id, user_data)
    
    # Проверяем, включены ли голосовые сообщения для этого пользователя
    voice_enabled = user_data[user_id].get('voice_enabled', True)
    
    # ИЗМЕНЕНО: Отправляем либо голосовое, либо текстовое сообщение в зависимости от настройки
    if voice_enabled:
        # Отправляем статус записи голосового сообщения
        await bot.send_chat_action(chat_id=message.chat.id, action="record_voice")
        
        try:
            voice_file_path = await generate_voice_message(response)
            if voice_file_path:
                await send_voice_message(user_id, voice_file_path, response)
                # Удаляем временный файл
                try:
                    os.remove(voice_file_path)
                except Exception as e:
                    logger.error(f"Ошибка при удалении временного файла: {e}")
        except Exception as e:
            logger.error(f"Ошибка при отправке голосового сообщения: {e}", exc_info=True)
            # Если не удалось отправить голосовое, отправляем текстовое как запасной вариант
            await message.answer(response)
    else:
        # Отправляем только текстовый ответ
        await message.answer(response)

async def summarize_user_history(user_id: str) -> str:
    """
    Создает краткое резюме диалога с пользователем на основе истории сообщений
    """
    try:
        history = user_data[user_id]["history"][-10:]  # Берем последние 20 сообщений для суммаризации
        
        # Форматируем историю в текст
        history_text = "\n".join([
            f"User: {msg['user']}\nAssistant: {msg['assistant']}"
            for msg in history
        ])
        
        # Запрос к Claude для суммаризации
        response = claude.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            temperature=0.7,
            system="Ты - эксперт по анализу диалогов. Твоя задача - создать краткое, но информативное резюме диалога между пользователем и терапевтом. Сфокусируйся на ключевых проблемах, темах и паттернах в общении пользователя. Формат: краткое описание основных тем, проблем и особенностей пользователя.",
            messages=[
                {"role": "user", "content": f"Проанализируй этот диалог и создай краткое резюме о пользователе и его ключевых темах/проблемах:\n\n{history_text}"}
            ]
        )
        
        summary = response.content[0].text
        
        # Сохраняем суммаризацию в базу данных
        user_data[user_id]["summary"] = summary
        await save_user_data(user_id, user_data)
        
        logger.info(f"Создана новая суммаризация для пользователя {user_id}")
        return summary
        
    except Exception as e:
        logger.error(f"Ошибка при создании суммаризации: {str(e)}")
        return ""

async def process_message(user_id: str, message: str) -> str:
    if user_id not in user_data:
        user_data[user_id] = {
            "name": "Unknown",
            "history": [],
            "summary": "",
            "message_count": 0
        }
        await save_user_data(user_id, user_data)
    
    # Получение истории и суммаризации пользователя
    user_history = user_data[user_id]["history"]
    user_summary = user_data[user_id].get("summary", "")
    
    # Проверяем необходимость суммаризации (каждые 10 сообщений)
    message_count = len(user_history)
    if message_count > 0 and message_count % 10 == 0:
        user_summary = await summarize_user_history(user_id)
    
    # Формирование системного промпта с учетом суммаризации
    system_prompt = THERAPIST_PROMPT
    if user_summary:
        system_prompt += f"\n\nКраткое резюме о пользователе:\n{user_summary}"
    
    # Формируем массив сообщений из истории
    formatted_messages = []
    # Добавляем последние 10 сообщений из истории для контекста
    for h in user_history[-10:]:
        if h.get('user'):
            formatted_messages.append({
                "role": "user",
                "content": [{"type": "text", "text": h["user"]}]
            })
        if h.get('assistant'):
            formatted_messages.append({
                "role": "assistant",
                "content": [{"type": "text", "text": h["assistant"]}]
            })
    
    # Добавляем текущее сообщение
    formatted_messages.append({
        "role": "user",
        "content": [{"type": "text", "text": message}]
    })
    
    # Получение ответа от Claude
    response = claude.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        temperature=0.7,
        system=system_prompt,
        messages=formatted_messages
    )
    
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
    user_id = str(message.from_user.id)
    is_admin = user_id in ADMIN_IDS
    
    help_text = """
🤖 *Доступные команды:*
• /start - Начать диалог
• /help - Показать это сообщение
• /balance - Проверить баланс сообщений
• /buy - Купить дополнительные сообщения
• /startvoice - Включить голосовой режим (только голосовые ответы)
• /stopvoice - Отключить голосовой режим (только текстовые ответы)
"""

    if is_admin:
        help_text += "• /admin - Панель администратора\n"

    help_text += """
📝 *Я понимаю следующие форматы:*
• Текстовые сообщения 💭
• Голосовые сообщения 🎤
• Скриншоты переписок 📸
• Изображения документом 📄
• Видео-кружки 🎥

🔊 *Режимы ответов:*
По умолчанию я отвечаю текстовыми сообщениями. Используй команду /startvoice, чтобы включить голосовой режим, и я буду отвечать только голосом. Используй /stopvoice, чтобы вернуться к текстовым ответам.

Что-то не работает? Обратитесь к нашему боту поддержки: @useSomethingBot
    """
    await message.answer(help_text, parse_mode=ParseMode.MARKDOWN)

@router.message(Command('startvoice'))
async def start_voice_handler(message: types.Message):
    user_id = str(message.from_user.id)
    
    # Инициализируем данные пользователя если их нет
    await initialize_user_data(user_id, message.from_user.first_name)
    
    # Включаем голосовые сообщения
    user_data[user_id]['voice_enabled'] = True
    await save_user_data(user_id, user_data)
    
    # Логируем действие в PostHog
    posthog.capture(
        distinct_id=user_id,
        event='voice_enabled',
        properties={
            'username': message.from_user.username,
            'first_name': message.from_user.first_name
        }
    )
    
    await message.answer("🔊 Голосовой режим включен! Теперь я буду отвечать тебе только голосовыми сообщениями вместо текста.")

@router.message(Command('stopvoice'))
async def stop_voice_handler(message: types.Message):
    user_id = str(message.from_user.id)
    
    # Инициализируем данные пользователя если их нет
    await initialize_user_data(user_id, message.from_user.first_name)
    
    # Отключаем голосовые сообщения
    user_data[user_id]['voice_enabled'] = False
    await save_user_data(user_id, user_data)
    
    # Логируем действие в PostHog
    posthog.capture(
        distinct_id=user_id,
        event='voice_disabled',
        properties={
            'username': message.from_user.username,
            'first_name': message.from_user.first_name
        }
    )
    
    await message.answer("📝 Голосовой режим отключен. Я буду отвечать тебе только текстовыми сообщениями.")

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

# Обновляем обработчики покупок
@router.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@router.message(F.successful_payment)
async def successful_payment(message: types.Message):
    user_id = str(message.from_user.id)
    
    try:
        # Определяем тип купленного плана по payload
        payload = message.successful_payment.invoice_payload
        plan_type = payload.replace('buy_', '').replace('_messages', '')
        
        # Получаем текущий лимит из базы
        response = supabase.table('users').select('message_limit').eq('user_id', user_id).single().execute()
        current_limit = response.data.get('message_limit', 30) if response.data else 5
        
        # Определяем новый лимит в зависимости от плана
        if plan_type == 'basic':
            new_limit = current_limit + PRICING_PLANS['basic']['messages']
        elif plan_type == 'premium':
            new_limit = current_limit + PRICING_PLANS['premium']['messages']
        elif plan_type in ['unlimited', '100']:  # поддержка старого названия
            new_limit = 999999  # или float('inf')
        else:
            logger.error(f"Неизвестный тип плана: {plan_type}")
            return
            
        # Обновляем лимит в базе данных
        data = {
            'user_id': user_id,
            'message_limit': new_limit
        }
        response = supabase.table('users').upsert(data).execute()
        
        # Обновляем локальные данные
        if user_id in user_data:
            user_data[user_id]['message_limit'] = new_limit
        
        # Отправляем сообщение об успешной покупке
        if plan_type in ['unlimited', '100']:
            success_message = "🌟 Поздравляю! Теперь у тебя безлимитный доступ к общению со мной!"
        else:
            success_message = f"✨ Отлично! Я добавила тебе {PRICING_PLANS[plan_type]['messages']} сообщений.\n\nТвой новый лимит: {new_limit} сообщений"
        
        await message.answer(success_message)
        
        # Логируем успешную покупку
        posthog.capture(
            distinct_id=user_id,
            event='successful_payment',
            properties={
                'plan_type': plan_type,
                'new_limit': new_limit,
                'payment_amount': message.successful_payment.total_amount,
                'currency': message.successful_payment.currency,
                'username': message.from_user.username,
                'first_name': message.from_user.first_name
            }
        )
        
    except Exception as e:
        logger.error(f"Ошибка при обработке успешного платежа: {str(e)}")
        await message.answer(
            "Произошла ошибка при обновлении твоего лимита сообщений. "
            "Пожалуйста, напиши в поддержку, мы всё исправим! 🙏"
        )

# Функция для кодирования изображения в base64
def encode_image(image_file: BinaryIO) -> str:
    return b64encode(image_file.read()).decode('utf-8')

# Добавляем новый обработчик для изображений
@router.message(F.content_type == 'photo')
async def handle_image(message: types.Message):
    try:
        user_id = str(message.from_user.id)
        
        # Инициализация данных пользователя
        await initialize_user_data(user_id, message.from_user.first_name)
        
        # Логируем получение изображения
        posthog.capture(
            distinct_id=user_id,
            event='message_received',
            properties={
                'message_type': 'photo',
                'username': message.from_user.username,
                'first_name': message.from_user.first_name,
                'message_count': user_data[user_id].get("message_count", 0),
                'message_limit': user_data[user_id].get("message_limit", 5),
                'has_caption': bool(message.caption)
            }
        )

        # Проверяем премиум доступ
        if not await check_premium_access(message, user_id):
            return

        await bot.send_chat_action(chat_id=message.chat.id, action="typing")
        
        # Обновляем счетчик сообщений
        await update_user_message_count(message, user_id)
        
        # Получаем файл
        file_id = message.photo[-1].file_id  # Берем самое большое разрешение
        local_file_path = f"photo_{message.from_user.id}.jpg"
        file = await bot.get_file(file_id)
        await bot.download_file(file.file_path, local_file_path)
        
        # Читаем изображение для Claude
        with open(local_file_path, "rb") as image_file:
            image_data = image_file.read()

        # Формируем промпт и отправляем запрос в Claude
        caption = message.caption or "Проанализируй этот скриншот переписки"
        
        response = claude.messages.create(
            model="claude-3-opus-20240229",
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"{caption}\nПожалуйста, прочитай текст со скриншота и опиши его содержание. Если это переписка, опиши её суть."
                        },
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": b64encode(image_data).decode('utf-8')
                            }
                        }
                    ]
                }
            ]
        )

        # Получаем текст из изображения
        extracted_text = response.content[0].text

        # Проверяем релевантность
        is_relevant, explanation = await is_psychological_query(extracted_text, user_id)
        if not is_relevant:
            await message.answer("Извините, но я могу помочь только с вопросами, связанными с психологической помощью и ментальным здоровьем. " + 
                               explanation.replace('no', '').strip())
            return

        # Обрабатываем текст через Claude
        response = await process_message(user_id, extracted_text)
        
        # Проверяем, включены ли голосовые сообщения для этого пользователя
        voice_enabled = user_data[user_id].get('voice_enabled', False)
        
        # ИЗМЕНЕНО: Отправляем либо голосовое, либо текстовое сообщение в зависимости от настройки
        if voice_enabled:
            # Отправляем статус записи голосового сообщения
            await bot.send_chat_action(chat_id=message.chat.id, action="record_voice")
            
            try:
                voice_file_path = await generate_voice_message(response)
                if voice_file_path:
                    await send_voice_message(user_id, voice_file_path, response)
                    # Удаляем временный файл
                    try:
                        os.remove(voice_file_path)
                    except Exception as e:
                        logger.error(f"Ошибка при удалении временного файла: {e}")
            except Exception as e:
                logger.error(f"Ошибка при отправке голосового сообщения: {e}", exc_info=True)
                # Если не удалось отправить голосовое, отправляем текстовое как запасной вариант
                await message.answer(response)
        else:
            # Отправляем только текстовый ответ
            await message.answer(response)

    except Exception as e:
        logger.error(f"Ошибка при обработке изображения: {str(e)}", exc_info=True)
        await message.answer("Произошла ошибка при обработке изображения. Пожалуйста, попробуйте позже.")
    finally:
        # Удаляем временный файл
        try:
            if 'local_file_path' in locals():
                os.remove(local_file_path)
        except:
            pass

# Класс состояний для админ-панели
class AdminState(StatesGroup):
    waiting_for_notification_text = State()
    confirm_notification = State()

# Обработчик для административной панели
@router.message(Command('admin'))
async def admin_panel(message: types.Message):
    user_id = str(message.from_user.id)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await message.answer("У вас нет доступа к административной панели.")
        return
    
    # Создаем клавиатуру для админ-панели
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика пользователей", callback_data="user_stats")],
        [InlineKeyboardButton(text="📣 Отправить уведомление всем пользователям", callback_data="send_notification")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_admin")]
    ])
    
    await message.answer("🔐 *Панель администратора*\n\nВыберите действие:", 
                       reply_markup=keyboard, 
                       parse_mode=ParseMode.MARKDOWN)

@router.callback_query(F.data == "send_notification")
async def admin_notification(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик для отправки уведомления всем пользователям"""
    user_id = str(callback.from_user.id)
    
    # Проверяем, является ли пользователь администратором
    if user_id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой функции.")
        return
    
    await callback.answer()
    
    # Устанавливаем состояние ожидания текста уведомления
    await state.set_state(AdminState.waiting_for_notification_text)
    
    # Создаем функцию для обработки текста уведомления
    async def notification_text_handler(message: types.Message, state: FSMContext):
        """Обработчик для текста уведомления"""
        user_id = str(message.from_user.id)
        logger.info(f"Получен текст уведомления от администратора {user_id}: {message.text[:50]}...")
        
        # Проверяем на отмену
        if message.text == '/cancel':
            await state.clear()
            await message.answer("❌ Отправка уведомления отменена.")
            return
        
        # Сохраняем текст уведомления
        await state.update_data(notification_text=message.text)
        
        # Отправляем предпросмотр сообщения
        try:
            await message.answer(
                f"*Предпросмотр уведомления:*\n\n{message.text}",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке предпросмотра: {e}")
            await message.answer(
                "Ошибка при форматировании. Возможно, некорректный Markdown. Попробуйте снова или используйте обычный текст."
            )
            return
        
        # Создаем клавиатуру для подтверждения
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📨 Только текст", callback_data="send_text_only")],
            [InlineKeyboardButton(text="🔊 Только голос", callback_data="send_voice_only")],
            [InlineKeyboardButton(text="📨 + 🔊 Текст + Голос", callback_data="send_text_voice")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_notification")]
        ])
        
        await state.set_state(AdminState.confirm_notification)
        await message.answer("Выберите тип рассылки:", reply_markup=keyboard)
        logger.info(f"Пользователь {user_id} перешел в состояние подтверждения отправки уведомления")
    
    # Устанавливаем разовый обработчик для следующего текстового сообщения от этого пользователя
    dp.message.register(notification_text_handler, lambda msg: msg.from_user.id == int(user_id) and msg.content_type == 'text')
    
    await callback.message.answer(
        "📝 Введите текст уведомления, которое будет отправлено всем пользователям.\n\n"
        "Вы можете использовать Markdown разметку.\n"
        "Для отмены напишите /cancel"
    )

@router.callback_query(F.data == "send_text_only", AdminState.confirm_notification)
async def admin_send_text_only(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик для отправки только текстовых уведомлений"""
    logger.info("Выбрана отправка только текстовых уведомлений")
    await callback.answer()
    
    data = await state.get_data()
    notification_text = data.get("notification_text", "")
    
    # Проверяем, есть ли данные для отправки
    if not notification_text:
        logger.error("Не найден текст уведомления в данных состояния")
        await callback.message.edit_text("❌ Ошибка: текст уведомления не найден. Попробуйте снова.")
        await state.clear()
        return
    
    logger.info(f"Начинаю отправку уведомлений с текстом: {notification_text[:50]}...")
    await callback.message.edit_text("⏳ Начинаю отправку уведомлений...")
    
    # Запускаем отправку уведомлений в фоновом режиме
    asyncio.create_task(
        send_bulk_notification(
            notification_text=notification_text,
            admin_user_id=callback.from_user.id,
            send_voice=False,
            send_text=True
        )
    )
    
    await state.clear()

@router.callback_query(F.data == "send_voice_only", AdminState.confirm_notification)
async def admin_send_voice_only(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик для отправки только голосовых уведомлений"""
    logger.info("Выбрана отправка только голосовых уведомлений")
    await callback.answer()
    
    data = await state.get_data()
    notification_text = data.get("notification_text", "")
    
    # Проверяем, есть ли данные для отправки
    if not notification_text:
        logger.error("Не найден текст уведомления в данных состояния")
        await callback.message.edit_text("❌ Ошибка: текст уведомления не найден. Попробуйте снова.")
        await state.clear()
        return
    
    logger.info(f"Начинаю отправку голосовых уведомлений с текстом: {notification_text[:50]}...")
    await callback.message.edit_text("⏳ Начинаю отправку голосовых уведомлений...")
    
    # Запускаем отправку уведомлений в фоновом режиме
    asyncio.create_task(
        send_bulk_notification(
            notification_text=notification_text,
            admin_user_id=callback.from_user.id,
            send_voice=True,
            send_text=False
        )
    )
    
    await state.clear()

@router.callback_query(F.data == "send_text_voice", AdminState.confirm_notification)
async def admin_send_text_voice(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик для отправки текстовых и голосовых уведомлений"""
    logger.info("Выбрана отправка текстовых и голосовых уведомлений")
    await callback.answer()
    
    data = await state.get_data()
    notification_text = data.get("notification_text", "")
    
    # Проверяем, есть ли данные для отправки
    if not notification_text:
        logger.error("Не найден текст уведомления в данных состояния")
        await callback.message.edit_text("❌ Ошибка: текст уведомления не найден. Попробуйте снова.")
        await state.clear()
        return
    
    logger.info(f"Начинаю отправку уведомлений (текст + голос) с текстом: {notification_text[:50]}...")
    await callback.message.edit_text("⏳ Начинаю отправку уведомлений (текст + голос)...")
    
    # Запускаем отправку уведомлений в фоновом режиме
    asyncio.create_task(
        send_bulk_notification(
            notification_text=notification_text,
            admin_user_id=callback.from_user.id,
            send_voice=True,
            send_text=True
        )
    )
    
    await state.clear()

@router.callback_query(F.data == "cancel_notification", AdminState.confirm_notification)
async def admin_cancel_notification(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик для отмены отправки уведомлений"""
    logger.info("Отмена отправки уведомлений")
    await callback.answer()
    await callback.message.edit_text("❌ Отправка уведомлений отменена.")
    await state.clear()

@router.callback_query(F.data == "cancel_admin")
async def cancel_admin(callback: types.CallbackQuery):
    """Отмена административных действий"""
    await callback.answer()
    await callback.message.edit_text("❌ Административные действия отменены.")

@router.callback_query(F.data == "user_stats")
async def get_user_stats(callback: types.CallbackQuery):
    """Получение статистики пользователей"""
    await callback.answer()
    
    try:
        # Получаем данные о пользователях
        response = supabase.table('users').select('*').execute()
        
        if not response.data:
            await callback.message.answer("⚠️ Пользователи не найдены.")
            return
            
        total_users = len(response.data)
        active_users = sum(1 for user in response.data if user.get('message_count', 0) > 0)
        voice_enabled = sum(1 for user in response.data if user.get('voice_enabled', False))
        
        # Формируем текст статистики
        stats_text = (
            f"📊 *Статистика пользователей*\n\n"
            f"👥 Всего пользователей: {total_users}\n"
            f"💬 Активных пользователей: {active_users}\n"
            f"🔊 С включенными голосовыми сообщениями: {voice_enabled}\n"
        )
        
        await callback.message.answer(stats_text, parse_mode=ParseMode.MARKDOWN)
        
    except Exception as e:
        logger.error(f"Ошибка при получении статистики: {e}")
        await callback.message.answer(f"❌ Произошла ошибка при получении статистики: {str(e)}")

async def send_bulk_notification(notification_text: str, admin_user_id: int, send_voice: bool = False, send_text: bool = True):
    """
    Отправка уведомлений всем пользователям
    
    Args:
        notification_text: Текст уведомления
        admin_user_id: ID администратора, инициировавшего рассылку
        send_voice: Отправлять ли голосовое сообщение
        send_text: Отправлять ли текстовое сообщение
    """
    try:
        logger.info(f"Начинаю массовую рассылку. Параметры: текст={send_text}, голос={send_voice}")
        
        # Получаем список всех пользователей
        response = supabase.table("users").select("user_id").execute()
        
        if not response.data:
            logger.warning("Нет пользователей для отправки уведомлений")
            await bot.send_message(
                chat_id=admin_user_id,
                text="⚠️ Нет пользователей для отправки уведомлений."
            )
            return
            
        users = [user["user_id"] for user in response.data]
        total_users = len(users)
        success_count = 0
        error_count = 0
        
        # Подготавливаем голосовое сообщение, если нужно
        voice_file_path = None
        if send_voice:
            try:
                voice_file_path = await generate_voice_message(notification_text)
                if not voice_file_path:
                    logger.error("Не удалось создать голосовое сообщение")
                    await bot.send_message(
                        chat_id=admin_user_id,
                        text="❌ Ошибка при создании голосового сообщения. Продолжаю отправку только текстовых уведомлений."
                    )
                    send_voice = False
            except Exception as e:
                logger.error(f"Ошибка при создании голосового сообщения: {e}")
                await bot.send_message(
                    chat_id=admin_user_id,
                    text=f"❌ Ошибка при создании голосового сообщения: {str(e)}. Продолжаю отправку только текстовых уведомлений."
                )
                send_voice = False
        
        # Отправляем уведомления всем пользователям
        for i, user_id in enumerate(users):
            try:
                # Проверяем, существует ли чат с пользователем
                if send_text:
                    try:
                        await bot.send_message(
                            chat_id=int(user_id),
                            text=notification_text,
                            parse_mode=ParseMode.MARKDOWN
                        )
                    except Exception as e:
                        logger.error(f"Ошибка при отправке текстового уведомления пользователю {user_id}: {e}")
                        # Пробуем отправить без Markdown, если была ошибка форматирования
                        if "can't parse entities" in str(e):
                            try:
                                await bot.send_message(
                                    chat_id=int(user_id),
                                    text=notification_text
                                )
                            except Exception as e2:
                                logger.error(f"Повторная ошибка при отправке текстового уведомления пользователю {user_id}: {e2}")
                                raise e2
                
                if send_voice and voice_file_path:
                    try:
                        await bot.send_voice(
                            chat_id=int(user_id),
                            voice=types.FSInputFile(voice_file_path)
                        )
                    except Exception as e:
                        logger.error(f"Ошибка при отправке голосового уведомления пользователю {user_id}: {e}")
                        raise e
                
                success_count += 1
                
                # Отправляем промежуточный статус администратору каждые 20 пользователей
                if (i + 1) % 20 == 0 or i == len(users) - 1:
                    progress = round((i + 1) / total_users * 100)
                    await bot.send_message(
                        chat_id=admin_user_id,
                        text=f"📊 Прогресс: {i+1}/{total_users} ({progress}%)\n"
                             f"✅ Успешно: {success_count}\n"
                             f"❌ Ошибки: {error_count}"
                    )
                
                # Задержка, чтобы не превысить лимиты Telegram API
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления пользователю {user_id}: {str(e)}")
                error_count += 1
                continue
        
        # Удаляем временный файл голосового сообщения
        if voice_file_path and os.path.exists(voice_file_path):
            try:
                os.remove(voice_file_path)
            except Exception as e:
                logger.error(f"Ошибка при удалении временного файла голосового сообщения: {e}")
        
        # Отправляем итоговый статус
        await bot.send_message(
            chat_id=admin_user_id,
            text=f"✅ Рассылка завершена!\n\n"
                 f"📊 Всего пользователей: {total_users}\n"
                 f"✅ Успешно отправлено: {success_count}\n"
                 f"❌ Ошибки: {error_count}"
        )
        
        # Логируем результат в PostHog
        posthog.capture(
            distinct_id=str(admin_user_id),
            event='bulk_notification',
            properties={
                'total_users': total_users,
                'success_count': success_count,
                'error_count': error_count,
                'send_text': send_text,
                'send_voice': send_voice,
                'notification_length': len(notification_text)
            }
        )
        
    except Exception as e:
        logger.error(f"Критическая ошибка при массовой рассылке: {str(e)}", exc_info=True)
        await bot.send_message(
            chat_id=admin_user_id,
            text=f"❌ Произошла ошибка при выполнении массовой рассылки: {str(e)}"
        )

async def main():
    try:
        logger.info("Starting bot...")
        global user_data
        
        # Регистрируем роутер раньше, чтобы обработчики корректно инициализировались
        logger.info("Регистрируем обработчики состояний...")
        dp.include_router(router)
        
        # Устанавливаем команды бота для контекстного меню
        logger.info("Настраиваем команды для меню бота...")
        # Основные команды для всех пользователей
        base_commands = [
            types.BotCommand(command="start", description="Начать диалог"),
            types.BotCommand(command="help", description="Показать справку"),
            types.BotCommand(command="balance", description="Проверить баланс сообщений"),
            types.BotCommand(command="buy", description="Купить дополнительные сообщения"),
            types.BotCommand(command="startvoice", description="Включить голосовой режим (только голосовые ответы)"),
            types.BotCommand(command="stopvoice", description="Отключить голосовой режим (только текстовые ответы)"),
        ]
        
        # Устанавливаем базовые команды для всех пользователей
        await bot.set_my_commands(base_commands)
        
        # Дополнительные команды для администраторов
        admin_commands = base_commands + [
            types.BotCommand(command="admin", description="Панель администратора")
        ]
        
        # Устанавливаем админские команды только для администраторов
        for admin_id in ADMIN_IDS:
            await bot.set_my_commands(
                admin_commands,
                scope=types.BotCommandScopeChat(chat_id=int(admin_id))
            )
            
        # Проверяем наличие поля voice_enabled в базе данных
        try:
            logger.info("Проверяем структуру базы данных...")
            # Для Supabase мы не можем напрямую создать столбец, но можем обновить запись
            # с новым полем, и Supabase автоматически добавит его в схему
            test_data = {
                'user_id': 'test_user',
                'name': 'Test User',
                'history': [],
                'message_count': 0,
                'message_limit': 5,
                'voice_enabled': False
            }
            supabase.table('users').upsert(test_data).execute()
            logger.info("Структура базы данных обновлена")
        except Exception as e:
            logger.error(f"Ошибка при проверке структуры базы данных: {str(e)}")
        
        logger.info("Loading user data...")
        user_data = await load_user_data()
        
        # Настраиваем планировщик
        logger.info("Setting up scheduler...")
        scheduler = setup_scheduler(bot, supabase, posthog)
        
        logger.info("Starting polling...")
        try:
            await dp.start_polling(bot, skip_updates=True)
        finally:
            logger.info("Shutting down scheduler...")
            scheduler.shutdown()
            await bot.session.close()
            
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