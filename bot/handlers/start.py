"""/start, персональные ссылки и диалог создания кастомной ссылки."""
import uuid

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.core import runtime
from bot.core.states import CustomLinkStates
from bot.db import repository as db
from bot.services.dialog import enter_dialog, has_dialog
from bot.services.filters import not_a_command
from bot.services.permissions import is_admin
from bot.services.telegram_ui import safe_edit_text
from bot.services.utils import is_valid_custom_link, normalize_code

router = Router(name="start")

BANNED_MSG = "🚫 Вы заблокированы в этом боте."


def _link(code: str) -> str:
    return f"https://t.me/{runtime.BOT_USERNAME}?start={code}"


@router.message(CommandStart())
async def start(message: Message, command: CommandObject, state: FSMContext) -> None:
    user = message.from_user
    user_id = user.id

    result = db.get_link_codes(user_id)
    if not result:
        original_code = str(uuid.uuid4())[:8]
        db.create_user_link(user_id, original_code, user.username, user.first_name)

    if db.is_globally_banned(user_id):
        await message.answer(BANNED_MSG)
        return

    payload = command.args
    if payload:
        resolved = db.resolve_recipient(payload)
        if resolved:
            recipient_id, _rec_username, _rec_first_name = resolved

            if db.is_globally_banned(recipient_id):
                await message.answer("🚫 Этот пользователь заблокирован в боте.")
                return

            if db.is_blocked_by(recipient_id, user_id):
                await message.answer("❌ Вы заблокированы у этого пользователя")
                return

            await enter_dialog(state, recipient_id=recipient_id)
            await message.answer(
                "🚀 Здесь можно отправить анонимное сообщение человеку, который опубликовал эту ссылку \n\n"
                "✍️ Напишите сюда всё, что хотите ему передать, и через несколько секунд он получит ваше сообщение, "
                "но не будет знать от кого \n\n"
                "Отправить можно 💬 текст, 📷 фото, 🎥 видео, 🎙 голосовое, 🎵 аудио, 🎞 GIF, стикер или 📄 файл "
                "(с подписью, где это поддерживает Telegram)"
            )
            return

    links = db.get_links(user_id)
    unique_code = links[0]
    custom_code = links[1] if links else None

    link = _link(unique_code)
    custom_link = _link(custom_code) if custom_code else None

    if custom_code:
        keyboard = [
            [InlineKeyboardButton(text="✏️ Создать свою ссылку", callback_data="create_custom_link")],
            [InlineKeyboardButton(text="🔄 Вернуть оригинальную ссылку", callback_data="reset_to_original")]
        ]
    else:
        keyboard = [
            [InlineKeyboardButton(text="✏️ Создать свою ссылку", callback_data="create_custom_link")]
        ]

    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton(text="⚙️ Админ панель", callback_data="admin_users_list_page_0")])

    message_text = f"👉 Ваша персональная ссылка:\n{link}"
    if custom_link:
        message_text += f"\n\n👉 Ваша пользовательская ссылка:\n{custom_link}"
    message_text += "\n\nРазместите эту ссылку в описании своего профиля, чтобы вам могли написать "
    await message.answer(message_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


@router.callback_query(F.data == "create_custom_link")
async def create_custom_link_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(CustomLinkStates.waiting_for_code)
    await callback.message.reply(
        "✏️ Введите желаемое название для вашей ссылки (только латинские буквы, цифры, _ и -, от 3 до 20 символов):\n\n"
        "Пример: my_link или best_page123"
    )


@router.message(CustomLinkStates.waiting_for_code, F.text, not_a_command)
async def set_custom_link(message: Message, state: FSMContext) -> None:
    user = message.from_user

    if db.is_globally_banned(user.id):
        await message.answer(BANNED_MSG)
        await state.clear()
        return

    raw_code = message.text.strip()
    custom_code, was_translit = normalize_code(raw_code)

    if not is_valid_custom_link(custom_code):
        await message.answer(
            "❌ Некорректный формат ссылки. Используйте только латинские буквы, цифры, _ и -, от 3 до 20 символов.\n\n"
            "Попробуйте еще раз или отправьте /cancel для отмены."
        )
        return

    if db.is_code_taken(custom_code):
        await message.answer(
            "❌ Эта ссылка уже занята. Пожалуйста, выберите другую.\n\n"
            "Попробуйте еще раз или отправьте /cancel для отмены."
        )
        return

    db.set_custom_code(user.id, custom_code)
    await state.clear()

    custom_link = _link(custom_code)
    result_text = (
        f"✅ Ваша пользовательская ссылка создана:\n{custom_link}\n\n"
        "Теперь вы можете использовать как эту ссылку, так и оригинальную."
    )
    if was_translit:
        result_text = f"ℹ️ Код «{raw_code}» на кириллице был автоматически преобразован в латиницу: «{custom_code}».\n\n" + result_text
    await message.answer(result_text)


@router.callback_query(F.data == "reset_to_original")
async def reset_to_original(callback: CallbackQuery) -> None:
    await callback.answer()
    user_id = callback.from_user.id

    if db.is_globally_banned(user_id):
        await safe_edit_text(callback.message, BANNED_MSG)
        return

    db.clear_custom_code(user_id)
    unique_code = db.get_links(user_id)[0]
    link = _link(unique_code)

    await safe_edit_text(
        callback.message,
        f"🔄 Вы вернули оригинальную ссылку:\n{link}\n\nРазместите её в соцсетях, чтобы получать анонимные сообщения",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Создать свою ссылку", callback_data="create_custom_link")]
        ])
    )


@router.message(Command("cancel"))
async def cancel_dialog(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None and not has_dialog(await state.get_data()):
        await message.answer("Нечего отменять.")
        return
    await state.clear()
    await message.answer("❌ Действие отменено.")


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    user_id = message.from_user.id

    if db.is_globally_banned(user_id):
        await message.answer(BANNED_MSG)
        return

    text = (
        "ℹ️ Доступные команды:\n\n"
        "/start — получить свою анонимную ссылку\n"
        "/promo КОД — активировать промокод на премиум\n"
        "/blocklist — список заблокированных вами отправителей\n"
        "/unblock — разблокировать отправителя (кнопки в /blocklist)\n"
        "/cancel — отменить текущее действие (создание ссылки, написание сообщения или ответа)"
    )
    if is_admin(user_id):
        text += (
            "\n\nАдминские команды:\n"
            "/admin — панель управления\n"
            "/createpromo КОД ДНИ [ЛИМИТ] — быстро создать промокод\n"
            "/banlist — глобальный бан-лист (кого забанили полностью)\n"
            "/unban ID — снять глобальный бан по Telegram ID\n"
            "/find ЗАПРОС — найти пользователя по ID, @username или имени"
        )
    await message.answer(text)
