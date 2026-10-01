"""Рассылка сообщения пользователям бота — админ-функция.

Мастер из трёх шагов: аудитория (все/только премиум) -> звук (со звуком/без)
-> содержимое (текст или медиа с подписью, как обычное сообщение) -> предпросмотр
с подтверждением. Глобально забаненные исключаются из любой аудитории всегда.
"""
import asyncio

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.core.config import logger
from bot.core.states import BroadcastStates
from bot.db import repository as db
from bot.db.premium import get_active_premium_user_ids
from bot.services.attachments import detect_attachment, exceeds_length_limit
from bot.services.filters import not_a_command
from bot.services.permissions import is_admin
from bot.services.telegram_ui import back_markup

router = Router(name="broadcast")

# Bot API официально ограничивает ~30 сообщений/сек в разные чаты — берём
# заметный запас, чтобы не словить TelegramRetryAfter посреди рассылки.
BROADCAST_DELAY_SECONDS = 0.05

_AUDIENCE_LABELS = {"all": "Все пользователи", "premium": "Только премиум"}


def _resolve_recipients(audience: str) -> list[int]:
    """Список получателей для выбранной аудитории, БЕЗ глобально забаненных —
    рассылка не должна доставать тех, кого админ явно заблокировал в боте."""
    banned = db.get_global_ban_user_ids()
    if audience == "premium":
        ids = get_active_premium_user_ids()
    else:
        ids = db.get_all_user_ids()
    return [uid for uid in ids if uid not in banned]


@router.callback_query(F.data == "admin_broadcast_start")
async def broadcast_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await callback.answer()
    await state.update_data(audience=None, silent=False)

    keyboard = [
        [InlineKeyboardButton(text="Все пользователи", callback_data="admin_broadcast_audience_all")],
        [InlineKeyboardButton(text="Только премиум", callback_data="admin_broadcast_audience_premium")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_broadcast_cancel")],
    ]
    await callback.message.edit_text(
        "Кому разослать?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )


@router.callback_query(F.data.startswith("admin_broadcast_audience_"))
async def broadcast_audience_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    audience = callback.data[len("admin_broadcast_audience_"):]
    await callback.answer()
    await state.update_data(audience=audience)

    count = len(_resolve_recipients(audience))
    keyboard = [
        [InlineKeyboardButton(text="🔔 Со звуком", callback_data="admin_broadcast_silent_no")],
        [InlineKeyboardButton(text="🔕 Без звука", callback_data="admin_broadcast_silent_yes")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_broadcast_cancel")],
    ]
    await callback.message.edit_text(
        f"Аудитория: {_AUDIENCE_LABELS.get(audience, audience)} ({count} чел.)\n\nУведомление со звуком или без?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )


@router.callback_query(F.data.startswith("admin_broadcast_silent_"))
async def broadcast_silent_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    silent = callback.data[len("admin_broadcast_silent_"):] == "yes"
    await callback.answer()
    await state.update_data(silent=silent)
    await state.set_state(BroadcastStates.waiting_content)

    await callback.message.edit_text(
        "Настройки готовы. Теперь пришлите содержимое рассылки одним сообщением — "
        "текст, фото, видео, аудио, GIF, документ (со стикером звук/аудитория тоже работают, "
        "но подписи к нему Telegram не разрешает).\n\n/cancel — отменить."
    )


@router.message(BroadcastStates.waiting_content, not_a_command)
async def broadcast_preview(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа.")
        await state.clear()
        return

    msg_type, fields = detect_attachment(message)
    if msg_type is None:
        await message.answer("Этот тип содержимого не поддерживается для рассылки. Пришлите текст или медиа ещё раз.")
        return

    content_text = message.text or message.caption or ""
    if exceeds_length_limit(msg_type, content_text):
        await message.answer("❌ Слишком длинное сообщение для рассылки. Сократите текст.")
        return

    data = await state.get_data()
    audience = data.get("audience", "all")
    silent = data.get("silent", False)
    recipients = _resolve_recipients(audience)

    # msg_type/fields/content_text — простые строки, безопасно кладутся в
    # FSM-данные (в том числе под Redis, который требует JSON-сериализуемости).
    await state.update_data(msg_type=msg_type, fields=fields, content_text=content_text)
    await state.set_state(None)

    preview = content_text if msg_type == "TEXT" else f"[{msg_type}] {content_text}".strip()
    keyboard = [
        [InlineKeyboardButton(text=f"✅ Отправить ({len(recipients)})", callback_data="admin_broadcast_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_broadcast_cancel")],
    ]
    await message.answer(
        f"Предпросмотр рассылки:\n\n{preview}\n\n"
        f"Аудитория: {_AUDIENCE_LABELS.get(audience, audience)} ({len(recipients)} чел.)\n"
        f"Звук: {'выключен' if silent else 'включён'}\n\nОтправить?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )


@router.callback_query(F.data == "admin_broadcast_cancel")
async def broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await callback.answer()
    await state.clear()
    await callback.message.edit_text("Рассылка отменена.", reply_markup=back_markup("admin_menu_back", "Назад в меню"))


async def _send_one(bot: Bot, user_id: int, msg_type: str, fields: dict, content_text: str, silent: bool) -> bool:
    """Отправляет одно сообщение рассылки. True — доставлено, False — нет
    (пользователь заблокировал бота и т.п.; исключения наружу не пробрасывает,
    кроме как логированием — иначе одна неудача обрывала бы всю рассылку)."""
async def _send_one(bot: Bot, user_id: int, msg_type: str, fields: dict, content_text: str, silent: bool) -> bool:
    """Отправляет одно сообщение рассылки. True — доставлено, False — нет
    (пользователь заблокировал бота и т.п.; исключения наружу не пробрасывает,
    кроме как логированием — иначе одна неудача обрывала бы всю рассылку).

    TelegramRetryAfter (Telegram временно ограничил частоту запросов) —
    единственный случай, где имеет смысл подождать и повторить: без этого
    при рассылке на большую аудиторию один rate-limit пометил бы почти всех
    оставшихся получателей как "не доставлено", хотя сообщение им реально
    не пытались доставить повторно.
    """
    for attempt in range(2):  # сама попытка + один повтор после RetryAfter
        try:
            if msg_type == "TEXT":
                await bot.send_message(chat_id=user_id, text=content_text, disable_notification=silent)
            elif msg_type == "PHOTO":
                await bot.send_photo(chat_id=user_id, photo=fields["photo_id"], caption=content_text or None, disable_notification=silent)
            elif msg_type == "VIDEO":
                await bot.send_video(chat_id=user_id, video=fields["video_id"], caption=content_text or None, disable_notification=silent)
            elif msg_type == "VOICE":
                await bot.send_voice(chat_id=user_id, voice=fields["voice_id"], caption=content_text or None, disable_notification=silent)
            elif msg_type == "AUDIO":
                await bot.send_audio(chat_id=user_id, audio=fields["audio_id"], caption=content_text or None, disable_notification=silent)
            elif msg_type == "ANIMATION":
                await bot.send_animation(chat_id=user_id, animation=fields["animation_id"], caption=content_text or None, disable_notification=silent)
            elif msg_type == "DOCUMENT":
                await bot.send_document(chat_id=user_id, document=fields["document_id"], caption=content_text or None, disable_notification=silent)
            elif msg_type == "STICKER":
                await bot.send_sticker(chat_id=user_id, sticker=fields["sticker_id"], disable_notification=silent)
            return True
        except TelegramForbiddenError:
            return False  # ожидаемо для рассылки — не логируем как ошибку
        except TelegramRetryAfter as e:
            if attempt == 0:
                logger.info(f"BROADCAST_RATE_LIMITED: жду {e.retry_after} сек. и повторяю для user={user_id}")
                await asyncio.sleep(e.retry_after)
                continue
            logger.warning(f"BROADCAST_SEND_FAILED user={user_id}: повторный RetryAfter, сдаюсь")
            return False
        except TelegramAPIError as e:
            logger.warning(f"BROADCAST_SEND_FAILED user={user_id}: {e}")
            return False
    return False


@router.callback_query(F.data == "admin_broadcast_confirm")
async def broadcast_confirm(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    data = await state.get_data()
    msg_type = data.get("msg_type")
    await state.clear()

    if not msg_type:
        await callback.answer()
        await callback.message.edit_text(
            "Данные рассылки потеряны (истекло состояние) — начните заново через /admin.",
            reply_markup=back_markup("admin_menu_back", "Назад в меню"),
        )
        return

    fields = data.get("fields", {})
    content_text = data.get("content_text", "")
    audience = data.get("audience", "all")
    silent = data.get("silent", False)

    await callback.answer()
    await callback.message.edit_text("⏳ Рассылка началась...")

    recipients = _resolve_recipients(audience)
    sent, failed = 0, 0
    for user_id in recipients:
        ok = await _send_one(bot, user_id, msg_type, fields, content_text, silent)
        sent += ok
        failed += not ok
        await asyncio.sleep(BROADCAST_DELAY_SECONDS)

    await callback.message.answer(f"✅ Рассылка завершена: {sent} доставлено, {failed} не доставлено.")
