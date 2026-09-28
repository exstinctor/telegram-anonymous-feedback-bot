"""Обработка входящих сообщений: отправка анонимного сообщения и ответы на них."""
from aiogram import Bot, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.core.config import logger
from bot.db import repository as db
from bot.db.premium import is_premium
from bot.services.antiflood import check_cooldown, mark_action
from bot.services.attachments import MAX_CAPTION_LENGTH, MAX_TEXT_LENGTH
from bot.services.attachments import detect_attachment as _detect_attachment
from bot.services.attachments import exceeds_length_limit as _exceeds_length_limit
from bot.services.attachments import is_supported_content
from bot.services.security import is_dangerous_document
from bot.services.telegram_errors import describe_send_error
from bot.services.utils import get_user_loginfo

router = Router(name="messages")

BANNED_MSG = "🚫 Вы заблокированы в этом боте."
NO_ACTIVE_CONVERSATION_MSG = "Для отправки сообщения используйте ссылку получателя или создайте свою (/start)"
DANGEROUS_FILE_MSG = "❌ Этот тип файла запрещён к отправке из соображений безопасности."
UNSUPPORTED_TYPE_MSG = "Поддерживаются: текст, фото, видео, голосовые, аудио, GIF, стикеры и документы"
TOO_LONG_MSG = "❌ Слишком длинное сообщение. Сократите текст и попробуйте снова."


async def _pop_state_key(state: FSMContext, data: dict, key: str) -> None:
    """Удаляет ключ из FSM-данных. update_data(key=None) НЕ удаляет ключ, а
    лишь перезаписывает его значением None — из-за этого "in data" на
    следующем сообщении продолжил бы находить его."""
    data.pop(key, None)
    await state.set_data(data)


@router.message(is_supported_content)
async def handle_message(message: Message, state: FSMContext, bot: Bot) -> None:
    user = message.from_user
    user_id = user.id

    if db.is_globally_banned(user_id):
        await message.answer(BANNED_MSG)
        return

    data = await state.get_data()

    if "recipient_id" in data:
        await _send_anonymous_message(message, state, data, bot, user)
    elif "replying_to" in data:
        await _send_reply(message, state, data, bot, user)
    else:
        await message.answer(NO_ACTIVE_CONVERSATION_MSG)


async def _send_anonymous_message(message: Message, state: FSMContext, data: dict, bot: Bot, user) -> None:
    user_id = user.id
    username = user.username
    first_name = user.first_name
    recipient_id = data["recipient_id"]

    remaining = check_cooldown(user_id)
    if remaining > 0:
        await message.answer(f"⏳ Подождите {round(remaining)} сек. перед отправкой следующего сообщения.")
        return

    rec_row = db.get_user_link_row(recipient_id)
    rec_username = rec_row[0] if rec_row else None
    rec_first_name = rec_row[1] if rec_row else None

    if db.is_blocked_by(recipient_id, user_id):
        await message.answer("❌ Вы заблокированы у этого пользователя")
        await _pop_state_key(state, data, "recipient_id")
        return

    msg_type, fields = _detect_attachment(message)
    if msg_type == "DOCUMENT" and is_dangerous_document(fields["document_name"]):
        await message.answer(DANGEROUS_FILE_MSG)
        return
    if msg_type is None:
        await message.answer(UNSUPPORTED_TYPE_MSG)
        return

    message_text = message.text or message.caption or ""

    if _exceeds_length_limit(msg_type, message_text):
        await message.answer(TOO_LONG_MSG)
        return

    try:
        # Не логируем содержимое анонимного сообщения (F10 из ревью) — это
        # единственная гарантия анонимности между отправителем и получателем,
        # и утечка текста в stdout/Docker logs/Sentry её бы нарушала. Метаданные
        # (тип вложения, длина) достаточно для отладки без риска для приватности.
        logger.info(
            f"Отправил {msg_type} ({len(message_text)} симв.): "
            f"{get_user_loginfo(user_id, username, first_name)} -> "
            f"{get_user_loginfo(recipient_id, rec_username, rec_first_name)}"
        )

        message_id = db.insert_message(
            user_id, recipient_id, username, first_name, message_text,
            photo_id=fields.get("photo_id"), video_id=fields.get("video_id"),
            voice_id=fields.get("voice_id"), audio_id=fields.get("audio_id"),
            animation_id=fields.get("animation_id"), sticker_id=fields.get("sticker_id"),
            document_id=fields.get("document_id"), document_name=fields.get("document_name"),
        )

        keyboard = []
        if is_premium(recipient_id):
            keyboard.append([InlineKeyboardButton(text="Узнать отправителя", callback_data=f"reveal_sender_{message_id}")])
        keyboard.append([InlineKeyboardButton(text="Ответить", callback_data=f"reply_{message_id}")])
        keyboard.append([InlineKeyboardButton(text="Заблокировать", callback_data=f"block_{message_id}")])
        reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

        caption = (
            f"У тебя новое сообщение!\n\n{message_text} \n\nНажми кнопку ниже для ответа"
            if message_text else "У тебя новое сообщение!\n\nНажми кнопку ниже для ответа"
        )

        if msg_type == "TEXT":
            await bot.send_message(chat_id=recipient_id, text=caption, reply_markup=reply_markup)
        elif msg_type == "PHOTO":
            await bot.send_photo(chat_id=recipient_id, photo=fields["photo_id"], caption=caption, reply_markup=reply_markup)
        elif msg_type == "VIDEO":
            await bot.send_video(chat_id=recipient_id, video=fields["video_id"], caption=caption, reply_markup=reply_markup)
        elif msg_type == "VOICE":
            await bot.send_voice(chat_id=recipient_id, voice=fields["voice_id"], caption=caption, reply_markup=reply_markup)
        elif msg_type == "AUDIO":
            await bot.send_audio(chat_id=recipient_id, audio=fields["audio_id"], caption=caption, reply_markup=reply_markup)
        elif msg_type == "ANIMATION":
            await bot.send_animation(chat_id=recipient_id, animation=fields["animation_id"], caption=caption, reply_markup=reply_markup)
        elif msg_type == "DOCUMENT":
            await bot.send_document(chat_id=recipient_id, document=fields["document_id"], caption=caption, reply_markup=reply_markup)
        elif msg_type == "STICKER":
            # sendSticker не поддерживает caption в Bot API — стикер отдельно,
            # кнопки текстом следом.
            await bot.send_sticker(chat_id=recipient_id, sticker=fields["sticker_id"])
            await bot.send_message(
                chat_id=recipient_id,
                text="У тебя новое сообщение (стикер)!\n\nНажми кнопку ниже для ответа",
                reply_markup=reply_markup
            )

        mark_action(user_id)

        keyboard = [[InlineKeyboardButton(text="Отправить еще", callback_data=f"send_again_{recipient_id}")]]
        await message.answer("Сообщение отправлено!", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    except Exception as e:
        await message.answer(describe_send_error(e, context=f"ANON_SEND {get_user_loginfo(user_id, username, first_name)} -> {recipient_id}"))
    finally:
        await _pop_state_key(state, data, "recipient_id")


async def _send_reply(message: Message, state: FSMContext, data: dict, bot: Bot, user) -> None:
    user_id = user.id
    username = user.username
    first_name = user.first_name

    remaining = check_cooldown(user_id)
    if remaining > 0:
        await message.answer(f"⏳ Подождите {round(remaining)} сек. перед отправкой следующего сообщения.")
        return

    message_id = data["replying_to"]
    sender_id = db.get_message_sender(message_id)
    if sender_id is None:
        await message.answer("Оригинальное сообщение не найдено")
        # F32 из ревью: раньше состояние не чистилось здесь, и следующее
        # сообщение снова упиралось бы в "оригинал не найден".
        await _pop_state_key(state, data, "replying_to")
        return

    msg_type, fields = _detect_attachment(message)
    if msg_type == "DOCUMENT" and is_dangerous_document(fields["document_name"]):
        await message.answer(DANGEROUS_FILE_MSG)
        return
    if msg_type is None:
        await message.answer(UNSUPPORTED_TYPE_MSG)
        return

    reply_text = message.text or message.caption or ""

    if _exceeds_length_limit(msg_type, reply_text):
        await message.answer(TOO_LONG_MSG)
        return

    logger.info(
        f"Ответ {msg_type} ({len(reply_text)} симв.): "
        f"{get_user_loginfo(user_id, username, first_name)} -> {get_user_loginfo(sender_id)}"
    )

    db.insert_reply(
        message_id, user_id, reply_text,
        photo=fields.get("photo_id"), video=fields.get("video_id"),
        voice=fields.get("voice_id"), audio=fields.get("audio_id"),
        animation=fields.get("animation_id"), sticker=fields.get("sticker_id"),
        document=fields.get("document_id"), document_name=fields.get("document_name"),
    )

    try:
        caption = f"Ответ на ваше сообщение:\n\n{reply_text}" if reply_text else "Ответ на ваше сообщение"

        if msg_type == "TEXT":
            await bot.send_message(chat_id=sender_id, text=caption)
        elif msg_type == "PHOTO":
            await bot.send_photo(chat_id=sender_id, photo=fields["photo_id"], caption=caption)
        elif msg_type == "VIDEO":
            await bot.send_video(chat_id=sender_id, video=fields["video_id"], caption=caption)
        elif msg_type == "VOICE":
            await bot.send_voice(chat_id=sender_id, voice=fields["voice_id"], caption=caption)
        elif msg_type == "AUDIO":
            await bot.send_audio(chat_id=sender_id, audio=fields["audio_id"], caption=caption)
        elif msg_type == "ANIMATION":
            await bot.send_animation(chat_id=sender_id, animation=fields["animation_id"], caption=caption)
        elif msg_type == "DOCUMENT":
            await bot.send_document(chat_id=sender_id, document=fields["document_id"], caption=caption)
        elif msg_type == "STICKER":
            await bot.send_sticker(chat_id=sender_id, sticker=fields["sticker_id"])
            await bot.send_message(chat_id=sender_id, text="Ответ на ваше сообщение (стикер)")

        mark_action(user_id)
        await message.answer("Ответ отправлен!")
    except Exception as e:
        await message.answer(describe_send_error(e, context=f"REPLY {get_user_loginfo(user_id, username, first_name)} -> {sender_id}"))
    finally:
        await _pop_state_key(state, data, "replying_to")
