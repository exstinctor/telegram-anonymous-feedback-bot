"""Разбор исключений Telegram Bot API в понятные пользователю сообщения.

Раньше любая ошибка при отправке (боту заблокировали, файл слишком большой,
Telegram временно ограничил частоту запросов...) сворачивалась в одно и то же
"Ошибка при отправке сообщения" — теперь отвечаем по существу, а в лог всегда
пишем реальный класс исключения для диагностики.
"""
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramEntityTooLarge,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)

from bot.core.config import logger


def describe_send_error(e: Exception, *, context: str) -> str:
    """Возвращает текст для пользователя и логирует исходную ошибку."""
    if isinstance(e, TelegramForbiddenError):
        logger.info(f"{context}: получатель заблокировал бота или удалил аккаунт")
        return "❌ Не удалось доставить: получатель заблокировал бота или удалил аккаунт."

    if isinstance(e, TelegramEntityTooLarge):
        logger.warning(f"{context}: файл слишком большой — {e}")
        return "❌ Файл слишком большой для отправки через Telegram."

    if isinstance(e, TelegramRetryAfter):
        logger.warning(f"{context}: Telegram ограничил частоту запросов, retry_after={e.retry_after}")
        return f"⏳ Telegram временно ограничил отправку. Попробуйте через {e.retry_after} сек."

    if isinstance(e, TelegramBadRequest):
        logger.warning(f"{context}: некорректный запрос к Telegram API — {e}")
        return "❌ Не удалось отправить: Telegram отклонил сообщение (некорректные данные)."

    if isinstance(e, TelegramNetworkError):
        logger.error(f"{context}: сетевая ошибка при обращении к Telegram — {e}")
        return "❌ Проблема с соединением с Telegram. Попробуйте ещё раз чуть позже."

    if isinstance(e, TelegramAPIError):
        logger.error(f"{context}: ошибка Telegram API — {e}")
        return "❌ Ошибка при отправке сообщения (Telegram API)."

    logger.error(f"{context}: непредвиденная ошибка — {e}")
    return "❌ Ошибка при отправке сообщения."
