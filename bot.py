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
                'summary': user.get('summary', ''),
                'message_limit': user.get('message_limit', 5),
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
        
        # Проверяем существование пользователя
        if user_id not in user_data:
            logger.info(f"Инициализация данных для нового пользователя {user_id}")
            user_data[user_id] = {
                "name": message.from_user.first_name,
                "history": [],
                "message_count": 0,
                "message_limit": FREE_MESSAGES
            }

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

# Добавляем фильтр для обычных текстовых сообщений (не команд)
@router.message(F.content_type == 'text', ~F.text.startswith('/'))
async def handle_text(message: types.Message):
    user_id = str(message.from_user.id)
    
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
    
    # Получаем или инициализируем данные пользователя
    if user_id not in user_data:
        user_data[user_id] = {
            "name": message.from_user.first_name,
            "history": [],
            "message_count": 0,
            "message_limit": FREE_MESSAGES
        }
        
        await save_user_data(user_id, user_data)
    
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
        await message.answer("Извините, но я могу помочь только с вопросами, связанными с психологической помощью и ментальным здоровьем. " + 
                           explanation.replace('no', '').strip())
        return
    
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    await update_user_message_count(message, user_id)
    response = await process_message(user_id, message.text)
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
    messages = []
    # Добавляем последние 10 сообщений из истории для контекста
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
🤖 *Доступные команды:*
• /start - Начать диалог
• /help - Показать это сообщение
• /balance - Проверить баланс сообщений
• /buy - Купить дополнительные сообщения

📝 *Я понимаю следующие форматы:*
• Текстовые сообщения 💭
• Голосовые сообщения 🎤
• Скриншоты переписок 📸
• Изображения документом 📄
• Видео-кружки 🎥

Что-то не работает? Обратитесь к нашему боту поддержки: @useSomethingBot
    """
    await message.answer(help_text, parse_mode=ParseMode.MARKDOWN)

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
        current_limit = response.data.get('message_limit', 5) if response.data else 5
        
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

@router.message(Command('buy'))
async def buy_handler(message: types.Message):
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
    
    # Логируем открытие меню покупки
    posthog.capture(
        distinct_id=str(message.from_user.id),
        event='buy_menu_opened',
        properties={
            'username': message.from_user.username,
            'first_name': message.from_user.first_name,
        }
    )

@router.message(Command('balance'))
async def balance_handler(message: types.Message):
    user_id = str(message.from_user.id)
    
    try:
        # Получаем актуальные данные из базы
        response = supabase.table('users').select('message_count, message_limit').eq('user_id', user_id).single().execute()
        if response.data:
            message_count = response.data.get('message_count', 0)
            message_limit = response.data.get('message_limit', 5)
            
            # Обновляем локальные данные
            if user_id not in user_data:
                user_data[user_id] = {}
            user_data[user_id]["message_count"] = message_count
            user_data[user_id]["message_limit"] = message_limit
            
            # Вычисляем оставшиеся сообщения и процент использования
            remaining_messages = max(0, message_limit - message_count)
            percent_used = min(100, int((message_count / message_limit) * 100)) if message_limit > 0 else 100
            
            # Определяем статусное сообщение
            if message_limit == float('inf') or message_limit == 999999:
                status = 'unlimited'
            elif remaining_messages <= 2:
                status = 'critical'
            elif remaining_messages <= 5:
                status = 'low'
            else:
                status = 'good'
            
            # Отправляем сообщение о балансе
            await message.answer(
                BALANCE_MESSAGE.format(
                    remaining_messages=remaining_messages if message_limit != float('inf') else "∞",
                    message_limit=message_limit if message_limit != float('inf') else "∞",
                    percent=percent_used,
                    status_message=BALANCE_STATUS_MESSAGES[status]
                ),
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Логируем проверку баланса
            posthog.capture(
                distinct_id=user_id,
                event='balance_checked',
                properties={
                    'remaining_messages': remaining_messages,
                    'message_limit': message_limit,
                    'percent_used': percent_used,
                    'status': status,
                    'username': message.from_user.username,
                    'first_name': message.from_user.first_name,
                }
            )
            
        else:
            # Если пользователь не найден, создаем запись с дефолтными значениями
            message_limit = 5
            message_count = 0
            await message.answer(
                BALANCE_MESSAGE.format(
                    remaining_messages=message_limit,
                    message_limit=message_limit,
                    percent=0,
                    status_message=BALANCE_STATUS_MESSAGES['good']
                ),
                parse_mode=ParseMode.MARKDOWN
            )
            
    except Exception as e:
        logger.error(f"Ошибка при проверке баланса: {str(e)}")
        await message.answer(
            "Извини, произошла ошибка при проверке баланса. Попробуй позже или напиши мне обычное сообщение 😊"
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