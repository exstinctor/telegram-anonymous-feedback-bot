"""Глобальный обработчик ошибок: логирует, не роняет процесс.

Если задан SENTRY_DSN — то же самое исключение дополнительно улетает в
Sentry (см. bot/core/config.py и main.py:_init_sentry). Без него ничего
никуда не отправляется, поведение не отличается от логирования.
"""
from aiogram.types import ErrorEvent

from bot.core.config import SENTRY_DSN, logger
from bot.services.utils import get_user_loginfo


async def handle_error(event: ErrorEvent) -> None:
    try:
        update = event.update
        logger.error(f"UPDATE_ERROR (update_id: {update.update_id}): {event.exception}")

        user = None
        if update.message:
            user = update.message.from_user
        elif update.callback_query:
            user = update.callback_query.from_user

        if user:
            logger.error(f"User info: {get_user_loginfo(user.id, user.username, user.first_name)}")

        if update.message and update.message.text:
            logger.error(f"Message text: {update.message.text}")

        if SENTRY_DSN:
            try:
                import sentry_sdk
                sentry_sdk.capture_exception(event.exception)
            except ImportError:
                pass  # уже предупредили при старте в main.py:_init_sentry
    except Exception as e:
        logger.error(f"ERROR_IN_ERROR_HANDLER: {str(e)}")
