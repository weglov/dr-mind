import logging
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import random
from posthog import Posthog
from supabase import Client
from aiogram import Bot
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

# Список фраз для рассылки
WEEKLY_MESSAGES = [
    "Привет, как дела? 😊",
    "Привет, как ты? 🌟",
    "Привет, как прошла неделя? 📅",
    "Привет, как ты там? 🌈",
    "Привет, Надеюсь, у тебя всё хорошо! ❤️",
    "Не забывай заботиться о себе! 🌺",
    "Вы имеете право, но не имеете лево",
    "Если я вдруг стану тебе нужен, то я там же, где и был, когда был не нужен."
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

async def send_weekly_messages(bot: Bot, supabase: Client, posthog: Posthog):
    try:
        logger.info("Начинаем еженедельную рассылку сообщений...")
        # Получаем всех пользователей из базы данных
        response = supabase.table('users').select('user_id').execute()
        users = [(user['user_id'],) for user in response.data]
        
        successful_sends = 0
        failed_sends = 0
        
        # Отправляем случайное сообщение и стикер каждому пользователю
        for user in users:
            try:
                message = random.choice(WEEKLY_MESSAGES)
                sticker_id = random.choice(STICKER_IDS)
                
                # Отправляем стикер
                await bot.send_sticker(chat_id=user[0], sticker=sticker_id)
                await asyncio.sleep(0.1)  # Небольшая задержка между отправками
                
                # Отправляем сообщение
                await bot.send_message(chat_id=user[0], text=message)
                await asyncio.sleep(0.1)  # Небольшая задержка между отправками
                
                successful_sends += 1
                
                # Отправляем событие в PostHog
                posthog.capture(
                    distinct_id=str(user[0]),
                    event='weekly_message_sent',
                    properties={
                        'message': message,
                        'sticker_id': sticker_id,
                        'status': 'success'
                    }
                )
            except Exception as e:
                failed_sends += 1
                logger.error(f"Ошибка при отправке еженедельного сообщения пользователю {user[0]}: {e}")
                posthog.capture(
                    distinct_id=str(user[0]),
                    event='weekly_message_failed',
                    properties={
                        'error': str(e)
                    }
                )

        logger.info(f"Рассылка завершена. Успешно: {successful_sends}, Ошибок: {failed_sends}")
                
    except Exception as e:
        logger.error(f"Ошибка в send_weekly_messages: {e}")

def setup_scheduler(bot: Bot, supabase: Client, posthog: Posthog):
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    
    # Запускаем каждую пятницу в 19:00 по московскому времени
    scheduler.add_job(
        send_weekly_messages,
        trigger=CronTrigger(
            day_of_week='fri',  # Пятница
            hour=20,           # 19:00
            minute=0,
            timezone="Europe/Moscow"
        ),
        id='weekly_messages',
        replace_existing=True,
        args=[bot, supabase, posthog]
    )
    
    scheduler.start()
    next_run = scheduler.get_job('weekly_messages').next_run_time
    logger.info(f"Планировщик запущен. Следующая рассылка запланирована на: {next_run}")
    
    return scheduler 

