"""Личные блокировки пользователя: /unblock и /blocklist.

Названы отдельно от /unban и /banlist (которые теперь заняты админскими
командами для ГЛОБАЛЬНОГО бана — bot/handlers/admin.py) — раньше оба набора
команд назывались одинаково, что путало и пользователей, и админов: /unban
на личную блокировку выглядел как админская модерация.
"""
from datetime import datetime

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.db import repository as db

router = Router(name="moderation")

BANNED_MSG = "🚫 Вы заблокированы в этом боте."


@router.message(Command("unblock"))
async def unblock(message: Message, command: CommandObject) -> None:
    user_id = message.from_user.id

    if db.is_globally_banned(user_id):
        await message.answer(BANNED_MSG)
        return

    if not command.args:
        await message.answer("Использование: /unblock @username")
        return

    target_username = command.args.strip().split()[0].lstrip('@')
    if not target_username:
        await message.answer("Укажите username (например: /unblock @username)")
        return

    removed = db.remove_block_by_username(user_id, target_username)
    if removed > 0:
        await message.answer(f"@{target_username} разблокирован")
    else:
        await message.answer(f"@{target_username} не найден в вашем списке блокировок")


@router.message(Command("blocklist"))
async def blocklist(message: Message) -> None:
    user_id = message.from_user.id

    if db.is_globally_banned(user_id):
        await message.answer(BANNED_MSG)
        return

    blocked_users = db.get_blocklist(user_id)

    if not blocked_users:
        await message.answer("У вас нет заблокированных пользователей")
        return

    message_txt = "Ваш список заблокированных пользователей:\n\n"
    for idx, (username_b, blocked_at) in enumerate(blocked_users, 1):
        try:
            blocked_time = datetime.strptime(blocked_at, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M")
        except (ValueError, TypeError):
            # F25 из ревью: одна битая запись не должна ронять весь /blocklist.
            blocked_time = str(blocked_at)
        message_txt += f"{idx}. @{username_b}\n {blocked_time}\n /unblock @{username_b}\n\n"

    await message.answer(message_txt)
