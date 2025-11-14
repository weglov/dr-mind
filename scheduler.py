import logging
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import random
from posthog import Posthog
from aiogram import Bot
from apscheduler.triggers.cron import CronTrigger
import db

logger = logging.getLogger(__name__)

# Список фраз для рассылки
WEEKLY_MESSAGES = messages = [
    "Привет! 😊 Как твоё настроение сегодня? Если захочешь поговорить — я здесь.",
    "Привет! На связи Минди 🌟 Надеюсь, сегодня у тебя найдётся время на приятные мелочи!",
    "Привет! 📅 Как прошла твоя неделя? Буду рада послушать, если захочешь поделиться.",
    "Как ты там? 🌈 Если нужна поддержка или просто разговор по душам — обращайся!",
    "Надеюсь, у тебя всё хорошо ❤️ Помни, ты всегда можешь обратиться ко мне за советом или поддержкой.",
    "Это Минди 🌺 Напоминаю о важности заботы о себе: отдых и хорошие эмоции нужны каждому.",
    "Просто хочу сказать, что верю в тебя ❤️ Если захочется обсудить что-то важное — я рядом!",
    "Пусть твой день будет спокойным и светлым ☀️ Я здесь, если захочешь поговорить!",
    "Думаю о тебе и надеюсь, что твой день полон хороших моментов 😊"
]


# Список стикеров для рассылки
STICKER_IDS = [
    "CAACAgIAAxkBAAEM1Cdnug3_A9foIEifK7S9itGrD6Mb8AACbgUAAj-VzAqGOtldiLy3NTYE",
    "CAACAgIAAxkBAAEM1C1nug48u60e7B2FIvSYqAE5zo486gACjgYAAvpRRgyWGTCDhkMr4DYE",
    "CAACAgIAAxkBAAEM1Ctnug44D5lryaN2pW27Vu87T7t4yQACCiYAAgPBeUjcZzJU8Ge0tzYE",
    "CAACAgIAAxkBAAEM1Clnug41CBV_N651cNAEixoTNaKM1wAClBgAAvdbgEjPGPx-6kVXrjYE",
    "CAACAgQAAxkBAAEM1C9nug5p5ZsrjjqdpsXnUDPb3I6arwAC2BQAAuiWMFKeUXzNBIgNGzYE",
    "CAACAgQAAxkBAAEM1DFnug56hiAAAacFk0Dg_7bEgO3ziNEAApMUAAKT-TBQTP9P0XAxl-I2BA",
    "CAACAgIAAxkBAAEM1DNnug6MjJ1irrHgAAHU4LLD9Y_n2CcAAnUaAAKQEIlKRjLKTmhNvCE2BA",
    "CAACAgQAAxkBAAEM1Ddnug6lNoe6Qz3JGfYrng9HbnxzVQACVxcAAtJZQFOXH0PCwGC1bTYE",
    "CAACAgQAAxkBAAEM1D9nug8Twpn2CAijRj6EHYPOmFCrSgACGxEAAnu7gFDZ_ClKKc1VZTYE"
]

async def send_weekly_messages(bot: Bot, posthog: Posthog):
    try:
        logger.info("Начинаем еженедельную рассылку сообщений...")
        # Получаем всех пользователей из базы данных
        users = await db.fetch_users_history()
        
        successful_sends = 0
        failed_sends = 0
        
        # Отправляем случайное сообщение и стикер каждому пользователю
        for user in users:
            try:
                user_id = user["user_id"]
                
                logger.info(user_id)

                user_history = user.get("history") or []
                
                message = random.choice(WEEKLY_MESSAGES)
                sticker_id = random.choice(STICKER_IDS)
                
                # Отправляем стикер
                await bot.send_sticker(chat_id=user_id, sticker=sticker_id)
                await asyncio.sleep(0.1)  # Небольшая задержка между отправками
                
                # Отправляем сообщение
                await bot.send_message(chat_id=user_id, text=message)
                await asyncio.sleep(0.1)  # Небольшая задержка между отправками
                
                # Создаем новое сообщение
                new_message = {
                    'user': "",  # Так как это сообщение от бота, поле user будет None
                    'assistant': message,
                    'type': 'weekly_message'
                }
                
                # Проверяем последнее сообщение в истории
                if user_history and user_history[-1].get('type') == 'weekly_message':
                    # Если последнее сообщение еженедельное - заменяем его
                    user_history[-1] = new_message
                    logger.info(f"Обновлено последнее еженедельное сообщение для пользователя {user_id}")
                else:
                    # Если последнее сообщение не еженедельное - добавляем новое
                    user_history.append(new_message)
                    logger.info(f"Добавлено новое еженедельное сообщение для пользователя {user_id}")
                
                # Обновляем историю в базе данных
                await db.update_user_fields(user_id, history=user_history)
                
                successful_sends += 1
                
                # Отправляем событие в PostHog
                posthog.capture(
                    distinct_id=str(user_id),
                    event='weekly_message_sent',
                    properties={
                        'message': message,
                        'sticker_id': sticker_id,
                        'status': 'success'
                    }
                )
            except Exception as e:
                failed_sends += 1
                logger.error(f"Ошибка при отправке еженедельного сообщения пользователю {user_id}: {e}")
                posthog.capture(
                    distinct_id=str(user_id),
                    event='weekly_message_failed',
                    properties={
                        'error': str(e)
                    }
                )

        logger.info(f"Рассылка завершена. Успешно: {successful_sends}, Ошибок: {failed_sends}")
                
    except Exception as e:
        logger.error(f"Ошибка в send_weekly_messages: {e}")

def setup_scheduler(bot: Bot, posthog: Posthog):
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    
    # Запускаем каждую пятницу в 19:00 по московскому времени
    scheduler.add_job(
        send_weekly_messages,
        trigger=CronTrigger(
            day_of_week='fri',  # Пятница
            hour=20,           # 19:00
            minute=00,
            timezone="Europe/Moscow"
        ),
        id='weekly_messages',
        replace_existing=True,
        args=[bot, posthog]
    )
    
    scheduler.start()
    next_run = scheduler.get_job('weekly_messages').next_run_time
    logger.info(f"Планировщик запущен. Следующая рассылка запланирована на: {next_run}")
    
    return scheduler 

