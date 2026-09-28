"""Централизованная регистрация всех роутеров в Dispatcher."""
from aiogram import Dispatcher

from bot.handlers import admin, broadcast, callbacks, messages, moderation, promo, start


def register_handlers(dp: Dispatcher) -> None:
    # Порядок важен: команды и FSM-состояния должны идти раньше общего
    # обработчика вложений (messages.router), иначе он перехватит их первым.
    dp.include_router(start.router)
    dp.include_router(admin.router)
    dp.include_router(broadcast.router)
    dp.include_router(moderation.router)
    dp.include_router(promo.router)
    dp.include_router(messages.router)
    # callbacks.router последним: в его конце стоит catch-all для
    # неопознанных callback_data.
    dp.include_router(callbacks.router)
