"""Точка входа: собрать Bot/Dispatcher, зарегистрировать роутеры, запустить polling."""
import asyncio
import os
import time

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from bot.core import runtime
from bot.core.config import BOT_TOKEN, DATA_DIR, SENTRY_DSN, logger
from bot.core.storage import build_storage
from bot.db.schema import init_db
from bot.errors import handle_error
from bot.handlers import register_handlers

HEARTBEAT_PATH = os.path.join(DATA_DIR, "heartbeat")
HEARTBEAT_INTERVAL_SECONDS = 30


def _init_sentry() -> None:
    """Опционально: если задан SENTRY_DSN, ошибки дублируются в Sentry —
    без него всё работает как раньше, только через локальные логи."""
    if not SENTRY_DSN:
        return
    try:
        import sentry_sdk
    except ImportError:
        logger.warning("SENTRY_DSN задан, но пакет sentry-sdk не установлен — пропускаю инициализацию Sentry.")
        return
    sentry_sdk.init(dsn=SENTRY_DSN, traces_sample_rate=0.0)
    logger.info("Sentry включён")


async def _heartbeat_loop() -> None:
    """Раз в HEARTBEAT_INTERVAL_SECONDS подтверждает, что event loop жив —
    это единственный практичный сигнал здоровья для long-polling бота без
    HTTP-эндпоинта. Проверяется скриптом healthcheck.py из Dockerfile."""
    while True:
        try:
            with open(HEARTBEAT_PATH, "w") as f:
                f.write(str(time.time()))
        except OSError as e:
            logger.warning(f"HEARTBEAT_WRITE_FAILED: {e}")
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)


async def main() -> None:
    _init_sentry()
    init_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=None))
    dp = Dispatcher(storage=build_storage())

    register_handlers(dp)
    dp.errors.register(handle_error)

    await runtime.init_bot_username(bot)

    logger.info(f"Bot started as @{runtime.BOT_USERNAME}")
    await bot.delete_webhook(drop_pending_updates=True)

    heartbeat_task = asyncio.create_task(_heartbeat_loop())
    try:
        await dp.start_polling(bot)
    finally:
        heartbeat_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
