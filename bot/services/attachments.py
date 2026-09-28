"""Определение типа вложения сообщения и проверка лимитов длины Telegram.

Вынесено из bot/handlers/messages.py в отдельный сервис, чтобы тем же кодом
могла пользоваться рассылка (bot/handlers/broadcast.py) — раньше это была
приватная функция одного хендлера, теперь общая точка правды для обоих.
"""
from aiogram.types import Message

# Telegram ограничивает текст сообщения 4096 символами, а подпись к медиа —
# 1024. Обёртка вида "У тебя новое сообщение!\n\n...\n\nНажми кнопку ниже для
# ответа" (на любом из двух языков) добавляет к присланному тексту служебные
# символы, так что вплотную к лимиту Telegram отклонил бы уже готовое
# сообщение с непонятной ошибкой. Запас ниже с избытком покрывает обёртку на
# обоих языках (реально ~56-57 символов), проверено на практике.
_WRAPPER_MARGIN = 200
MAX_TEXT_LENGTH = 4096 - _WRAPPER_MARGIN
MAX_CAPTION_LENGTH = 1024 - _WRAPPER_MARGIN


def detect_attachment(message: Message):
    """Определяет тип вложения сообщения.

    Возвращает (msg_type, fields) либо (None, None), если формат не поддержан.
    fields — обычный dict из строк/чисел (file_id и т.п.), пригодный для
    хранения в FSM-данных (важно для Redis-хранилища — оно требует
    JSON-сериализуемости, тогда как сам объект Message таким не является).
    """
    if message.text:
        return "TEXT", {}
    if message.photo:
        return "PHOTO", {"photo_id": message.photo[-1].file_id}
    if message.video:
        return "VIDEO", {"video_id": message.video.file_id}
    if message.voice:
        return "VOICE", {"voice_id": message.voice.file_id}
    if message.audio:
        return "AUDIO", {"audio_id": message.audio.file_id}
    if message.animation:
        return "ANIMATION", {"animation_id": message.animation.file_id}
    if message.sticker:
        return "STICKER", {"sticker_id": message.sticker.file_id}
    if message.document:
        return "DOCUMENT", {"document_id": message.document.file_id, "document_name": message.document.file_name}
    return None, None


def is_supported_content(message: Message) -> bool:
    """Фильтр для роутера: пропускает сообщения с поддерживаемым вложением,
    но НЕ команды (иначе неизвестная команда типа /foo попала бы сюда как
    обычный текст — это была реальная ошибка приоритета операторов в версии
    на python-telegram-bot, здесь воспроизводить её не будем).
    """
    if message.text and message.text.startswith("/"):
        return False
    msg_type, _ = detect_attachment(message)
    return msg_type is not None


def exceeds_length_limit(msg_type: str, text: str) -> bool:
    if msg_type == "TEXT":
        return len(text) > MAX_TEXT_LENGTH
    if msg_type == "STICKER":
        return False  # у стикера нет ни текста, ни подписи
    return len(text) > MAX_CAPTION_LENGTH
