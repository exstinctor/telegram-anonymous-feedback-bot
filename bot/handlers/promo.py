"""Пользовательская команда /promo — активация промокода на премиум."""
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.db import repository as db
from bot.db.premium import add_or_extend_premium
from bot.services.antiflood import check_promo_cooldown, mark_promo_attempt

router = Router(name="promo")

BANNED_MSG = "🚫 Вы заблокированы в этом боте."

_ERROR_MESSAGES = {
    "not_found": "❌ Такого промокода не существует.",
    "already_used": "❌ Вы уже активировали этот промокод.",
    "exhausted": "❌ У этого промокода закончился лимит активаций.",
}


@router.message(Command("promo"))
async def redeem_promo(message: Message, command: CommandObject) -> None:
    user_id = message.from_user.id

    if db.is_globally_banned(user_id):
        await message.answer(BANNED_MSG)
        return

    if not command.args:
        await message.answer("Использование: /promo КОД")
        return

    # Отдельный лимитер на попытки, а не только на успешные погашения — иначе
    # подбор кода перебором ничем не сдерживался бы (см. bot/services/antiflood.py).
    remaining = check_promo_cooldown(user_id)
    if remaining > 0:
        await message.answer(f"⏳ Слишком часто. Подождите {round(remaining)} сек. перед следующей попыткой.")
        return
    mark_promo_attempt(user_id)

    code = command.args.strip().split()[0].upper()
    ok, days, error = db.redeem_promo_code(code, user_id)

    if not ok:
        await message.answer(_ERROR_MESSAGES.get(error, "❌ Не удалось активировать промокод."))
        return

    new_until = add_or_extend_premium(user_id, days)
    await message.answer(
        f"✅ Промокод активирован! Премиум выдан на {days} дн., действует до {new_until.strftime('%d.%m.%Y %H:%M')}"
    )
