"""Фабрика хранилища состояний FSM.

Redis выбран, только если задан REDIS_URL — без него бот продолжает работать
ровно как раньше (MemoryStorage), никаких новых обязательных зависимостей
для тех, кому персистентность состояний не нужна.
"""
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage

from bot.core.config import REDIS_URL, logger


def build_storage() -> BaseStorage:
    if not REDIS_URL:
        logger.info("REDIS_URL не задан — состояния FSM хранятся в памяти процесса (см. .env.example)")
        return MemoryStorage()

    try:
        from aiogram.fsm.storage.redis import RedisStorage
    except ImportError as e:
        raise RuntimeError(
            "REDIS_URL задан, но пакет redis не установлен. "
            "Добавьте redis>=5.0,<6 в requirements.txt (уже есть) и переустановите зависимости."
        ) from e

    logger.info("Состояния FSM хранятся в Redis (переживают перезапуск бота)")
    return RedisStorage.from_url(REDIS_URL)
