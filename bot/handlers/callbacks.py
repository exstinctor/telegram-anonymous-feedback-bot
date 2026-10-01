"""Обработка нажатий inline-кнопок (все, кроме create_custom_link/reset_to_original,
которые остаются в start.py вместе со своей FSM-логикой)."""
from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.core.config import logger
from bot.core.states import AdminPremiumStates
from bot.db import repository as db
from bot.db.premium import add_or_extend_premium, is_premium, remove_premium
from bot.services.permissions import is_admin
from bot.services.telegram_ui import back_markup, safe_edit_caption, safe_edit_text
from bot.services.utils import get_user_loginfo

router = Router(name="callbacks")


async def _require_admin(callback: CallbackQuery, user_id: int) -> bool:
    if not is_admin(user_id):
        await callback.answer("Нет доступа.", show_alert=True)
        return False
    return True


# ---------------------------------------------------------------------------
# Админ-панель
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("admin_premium_list_page_"))
async def admin_premium_list_page(callback: CallbackQuery) -> None:
    if not await _require_admin(callback, callback.from_user.id):
        return
    from bot.handlers.admin import admin_show_premium_list
    page = int(callback.data.split("_")[-1])
    await admin_show_premium_list(callback, page=page)


@router.callback_query(F.data.startswith("admin_users_list_page_"))
async def admin_users_list_page(callback: CallbackQuery) -> None:
    if not await _require_admin(callback, callback.from_user.id):
        return
    from bot.handlers.admin import admin_show_users_list
    page = int(callback.data.split("_")[-1])
    await admin_show_users_list(callback, page=page)


@router.callback_query(F.data.startswith("admin_global_ban_list_page_"))
async def admin_global_ban_list_page(callback: CallbackQuery) -> None:
    if not await _require_admin(callback, callback.from_user.id):
        return
    from bot.handlers.admin import admin_show_global_ban_list
    page = int(callback.data.split("_")[-1])
    await admin_show_global_ban_list(callback, page=page)


@router.callback_query(F.data == "admin_promo_list")
async def admin_promo_list(callback: CallbackQuery) -> None:
    if not await _require_admin(callback, callback.from_user.id):
        return
    from bot.handlers.admin import admin_show_promo_list
    await admin_show_promo_list(callback)


@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery) -> None:
    if not await _require_admin(callback, callback.from_user.id):
        return
    from bot.handlers.admin import admin_show_stats
    await admin_show_stats(callback)


@router.callback_query(F.data == "admin_manage_list")
async def admin_manage_list(callback: CallbackQuery) -> None:
    if not await _require_admin(callback, callback.from_user.id):
        return
    from bot.handlers.admin import admin_show_admins_list
    await admin_show_admins_list(callback)


@router.callback_query(F.data.startswith("admin_user_"))
async def admin_user_panel(callback: CallbackQuery, bot: Bot) -> None:
    if not await _require_admin(callback, callback.from_user.id):
        return
    from bot.handlers.admin import admin_show_user_panel
    await admin_show_user_panel(callback, bot, int(callback.data.split("_")[2]))


@router.callback_query(F.data.startswith("admin_globalban_"))
async def admin_toggle_global_ban(callback: CallbackQuery) -> None:
    if not await _require_admin(callback, callback.from_user.id):
        return
    target_id = int(callback.data.split("_")[2])
    if db.is_globally_banned(target_id):
        db.global_unban(target_id)
        await safe_edit_text(callback.message, "Глобальный бан снят.", reply_markup=None)
    else:
        db.global_ban(target_id)
        await safe_edit_text(callback.message, "Пользователь добавлен в глобальный бан.", reply_markup=None)


@router.callback_query(
    F.data.startswith("admin_premium_add_")
    & ~F.data.contains("days_")
    & ~F.data.contains("manual_")
)
async def admin_premium_add_menu(callback: CallbackQuery) -> None:
    if not await _require_admin(callback, callback.from_user.id):
        return
    from bot.handlers.admin import admin_give_premium_days_menu
    await admin_give_premium_days_menu(callback, int(callback.data.split("_")[3]))


@router.callback_query(F.data.startswith("admin_premium_add_days_"))
async def admin_premium_add_days(callback: CallbackQuery) -> None:
    if not await _require_admin(callback, callback.from_user.id):
        return
    parts = callback.data.split("_")
    target_id, days = int(parts[4]), int(parts[5])
    new_until = add_or_extend_premium(target_id, days)
    await safe_edit_text(
        callback.message,
        f"Премиум выдан пользователю {target_id} до {new_until.strftime('%d.%m.%Y %H:%M')}",
        reply_markup=back_markup(f"admin_user_{target_id}"),
    )


@router.callback_query(F.data.startswith("admin_premium_add_manual_"))
async def admin_premium_add_manual(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _require_admin(callback, callback.from_user.id):
        return
    target_id = int(callback.data.split("_")[4])
    await state.set_state(AdminPremiumStates.waiting_manual_days)
    await state.update_data(admin_premium_target=target_id)
    await callback.message.reply("Введите, на сколько дней выдать премиум (число):")


@router.callback_query(F.data.startswith("admin_premium_remove_"))
async def admin_premium_remove(callback: CallbackQuery) -> None:
    if not await _require_admin(callback, callback.from_user.id):
        return
    target_id = int(callback.data.split("_")[3])
    remove_premium(target_id)
    await safe_edit_text(
        callback.message, f"Премиум снят с пользователя {target_id} (если он был).",
        reply_markup=back_markup(f"admin_user_{target_id}"),
    )


@router.callback_query(F.data.startswith("admin_who_blocked_"))
async def admin_who_blocked(callback: CallbackQuery) -> None:
    if not await _require_admin(callback, callback.from_user.id):
        return
    target_id = int(callback.data.split("_")[3])
    rows = db.get_blockers_of(target_id)
    if not rows:
        await safe_edit_text(
            callback.message, "Никто не блокировал этого пользователя.",
            reply_markup=back_markup(f"admin_user_{target_id}"),
        )
        return

    premium_blockers = [(uid, name) for uid, name in rows if is_premium(uid)]
    if not premium_blockers:
        await safe_edit_text(
            callback.message, "Его блокировали только пользователи без премиума.",
            reply_markup=back_markup(f"admin_user_{target_id}"),
        )
        return

    msg = "Пользователь заблокирован у премиум-пользователей:\n\n"
    keyboard = []
    for uid, blocked_username in premium_blockers:
        msg += f"- ID {uid} (@{blocked_username})\n"
        keyboard.append([InlineKeyboardButton(
            text=f"Разблокировать у {uid}",
            callback_data=f"admin_unblock_for_{uid}_{target_id}"
        )])
    keyboard.append([InlineKeyboardButton(text="Назад", callback_data=f"admin_user_{target_id}")])
    await safe_edit_text(callback.message, msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


@router.callback_query(F.data.startswith("admin_unblock_for_"))
async def admin_unblock_for(callback: CallbackQuery) -> None:
    if not await _require_admin(callback, callback.from_user.id):
        return
    parts = callback.data.split("_")
    owner_id, target_id = int(parts[3]), int(parts[4])
    db.remove_block(owner_id, target_id)
    await safe_edit_text(
        callback.message,
        f"Пользователь {target_id} разоблокирован у пользователя {owner_id}.", reply_markup=None
    )


# ---------------------------------------------------------------------------
# Пользовательские кнопки
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "get_link")
async def get_link(callback: CallbackQuery) -> None:
    from bot.core import runtime
    user_id = callback.from_user.id
    links = db.get_links(user_id)
    unique_code = links[0]
    custom_code = links[1] if links else None

    link = f"https://t.me/{runtime.BOT_USERNAME}?start={unique_code}"
    custom_link = f"https://t.me/{runtime.BOT_USERNAME}?start={custom_code}" if custom_code else None

    message_text = f"Персональная ссылка:\n{link}"
    if custom_link:
        message_text += f"\n\nПользовательская ссылка:\n{custom_link}"

    if custom_code:
        keyboard = [
            [InlineKeyboardButton(text="Создать свою ссылку", callback_data="create_custom_link")],
            [InlineKeyboardButton(text="Вернуть оригинальную ссылку", callback_data="reset_to_original")]
        ]
    else:
        keyboard = [[InlineKeyboardButton(text="Создать свою ссылку", callback_data="create_custom_link")]]

    await safe_edit_text(callback.message, message_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


@router.callback_query(F.data.startswith("reveal_sender_"))
async def reveal_sender(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    message_id = int(callback.data.split("_")[2])
    result = db.get_message_sender_info(message_id)
    if result and result[3] != user_id:
        result = None
    if result and not is_premium(user_id):
        await callback.answer("Доступно только с премиумом", show_alert=True)
        return
    if result:
        sender_username, sender_first_name, sender_id, _recipient_id = result
        keyboard = [
            [InlineKeyboardButton(text="Назад", callback_data=f"go_back_{message_id}")],
            [InlineKeyboardButton(text="Заблокировать", callback_data=f"block_{message_id}")]
        ]
        text = (
            "Информация об отправителе:\n"
            f"Имя: {sender_first_name}\n"
            f"Username: @{sender_username if sender_username else 'нет'}\n"
            f"ID: {sender_id}"
        )
        reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
        if callback.message.text:
            await safe_edit_text(callback.message, text, reply_markup=reply_markup)
        else:
            await safe_edit_caption(callback.message, text, reply_markup=reply_markup)
    else:
        await safe_edit_text(callback.message, "Информация не найдена")


@router.callback_query(F.data.startswith("go_back_"))
async def go_back(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    message_id = int(callback.data.split("_")[2])
    result = db.get_message_for_go_back(message_id)
    if result and result[10] != user_id:
        result = None
    if result:
        (message_text, photo_file_id, video_file_id, voice_file_id, audio_file_id,
         animation_file_id, sticker_file_id, document_file_id,
         sender_username, sender_first_name, _recipient_id) = result

        keyboard = []
        if is_premium(user_id):
            keyboard.append([InlineKeyboardButton(text="Узнать отправителя", callback_data=f"reveal_sender_{message_id}")])
        keyboard.append([InlineKeyboardButton(text="Ответить", callback_data=f"reply_{message_id}")])
        keyboard.append([InlineKeyboardButton(text="Заблокировать", callback_data=f"block_{message_id}")])
        reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

        base_text = (
            f"У тебя новое сообщение!\n\n{message_text} \n\nНажми кнопку ниже для ответа"
            if message_text else "У тебя новое сообщение!\n\nНажми кнопку ниже для ответа"
        )

        has_caption_media = any([
            photo_file_id, video_file_id, voice_file_id,
            audio_file_id, animation_file_id, document_file_id
        ])
        if has_caption_media:
            await safe_edit_caption(callback.message, base_text, reply_markup=reply_markup)
        else:
            await safe_edit_text(callback.message, base_text, reply_markup=reply_markup)
    else:
        await safe_edit_text(callback.message, "Сообщение не найдено")


@router.callback_query(F.data.startswith("block_"))
async def block_sender(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    user = callback.from_user
    try:
        message_id = int(callback.data.split("_")[1])
        msg_row = db.get_message_for_block(message_id)
        if not msg_row or msg_row[3] != user_id:
            await callback.answer("Недостаточно прав", show_alert=True)
            return

        blocked_user_id, sender_username, sender_first_name, _recipient_id = msg_row
        blocked_username = sender_username or sender_first_name or str(blocked_user_id)

        if db.is_blocked_by(user_id, blocked_user_id):
            await safe_edit_text(callback.message, "Пользователь уже заблокирован")
            return

        db.add_block(user_id, blocked_user_id, blocked_username)
        await safe_edit_text(
            callback.message,
            "Пользователь заблокирован\n\n"
            "Он больше не сможет писать вам сообщения\n"
            f"Для разблокировки: /unblock @{blocked_username}"
        )
    except Exception as e:
        logger.error(f"BLOCK_ERROR: {get_user_loginfo(user_id, user.username, user.first_name)}: {str(e)}")
        await safe_edit_text(callback.message, "Ошибка при блокировке")


@router.callback_query(F.data.startswith("send_again_"))
async def send_again(callback: CallbackQuery, state: FSMContext) -> None:
    recipient_id = int(callback.data.split("_")[2])
    await state.update_data(recipient_id=recipient_id)
    await callback.message.reply("Напишите новое сообщение для этого пользователя:")


@router.callback_query(F.data.startswith("reply_"))
async def reply_to_message(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    message_id = int(callback.data.split("_")[1])
    recipient_id = db.get_message_recipient(message_id)
    if recipient_id is None or recipient_id != user_id:
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    await state.update_data(replying_to=message_id)
    await callback.message.reply("Напишите ваш ответ на это сообщение:")


@router.callback_query()
async def unknown_callback(callback: CallbackQuery) -> None:
    """Ловушка для неопознанных callback_data — тихо гасим "часики" на кнопке,
    чтобы не оставлять пользователя с вечной загрузкой при устаревших кнопках
    (например, после перезапуска бота с новым форматом callback_data)."""
    await callback.answer()
