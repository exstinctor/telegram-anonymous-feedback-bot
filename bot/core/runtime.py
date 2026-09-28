"""Данные, которые узнаём только после соединения с Telegram (не из .env).

BOT_USERNAME кэшируется один раз при старте (см. main.py), чтобы не дёргать
bot.get_me() на каждое построение ссылки. Импортируйте модуль целиком
(``from bot.core import runtime``) и читайте ``runtime.BOT_USERNAME`` —
``from ... import BOT_USERNAME`` зафиксирует значение None на момент импорта.
"""
BOT_USERNAME: str | None = None


async def init_bot_username(bot) -> None:
    global BOT_USERNAME
    me = await bot.get_me()
    BOT_USERNAME = me.username
