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
    "Приветик, как ты? 🌟",
    "Привет, как прошла неделя? 📅",
    "Привет, как настроение? 🌈",
    "Привет, как твои успехи? 💪",
    "Надеюсь, у тебя всё хорошо! ❤️",
    "Не забывай заботиться о себе! 🌺"
]

# Список стикеров для рассылки
STICKER_IDS = [
    "AAMCAgADGQEAAgLVZ7g5nT8Kc5GhyjhVDCRCTDns8TwAApQYAAL3W4BIzxj8fupFV64BAAdtAAM2BA",  # Cute cat
    "AAMCAgADGQEAAgLXZ7g50IfihU71O9pqBFV2CwjDmhsAAt4ZAAK1y5hLPzilJtt0YuwBAAdtAAM2BA",  # Happy fox
    "AAMCBAADGQEAAgLZZ7g6AmXWYL_29dXmVRlQbcwzXZ4AAiIdAAJRfQABUG82Yd1QWKOlAQAHbQADNgQ",  # Lovely panda
    "AAMCBAADGQEAAgLbZ7g6Hfd-9QozTogyNLM0B9F0jfwAAlcXAALSWUBTlx9DwsBgtW0BAAdtAAM2BA",  # Cheerful dog
    "AAMCBAADGQEAAgLbZ7g6Hfd-9QozTogyNLM0B9F0jfwAAlcXAALSWUBTlx9DwsBgtW0BAAdtAAM2BA"   # Sweet bunny
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
            hour=19,           # 19:00
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