"""Обёртки над Telegram-вызовами, устойчивые к частым не-ошибкам.

Telegram отвечает 400 "message is not modified", если редактируемое
сообщение получает точно тот же текст/подпись и разметку — это происходит
при двойном клике по кнопке или повторном показе того же экрана, и не
является реальной ошибкой. Без этой обёртки пользователь видел общее
"Ошибка" от глобального error-хендлера на совершенно безобидное действие
(F05 из ревью).
"""
from aiogram.exceptions import TelegramBadRequest


async def safe_edit_text(message, text, reply_markup=None, **kwargs) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup, **kwargs)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise


async def safe_edit_caption(message, caption, reply_markup=None, **kwargs) -> None:
    try:
        await message.edit_caption(caption=caption, reply_markup=reply_markup, **kwargs)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise
