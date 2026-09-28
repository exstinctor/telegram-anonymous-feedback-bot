"""Тесты защиты от превышения лимитов Telegram (4096 для текста, 1024 для
подписей к медиа) с учётом служебной обёртки ("У тебя новое сообщение!..."),
которую бот добавляет к присланному тексту. Без этой проверки сообщение,
присланное близко к лимиту, отклонялось бы самим Telegram с непонятной
ошибкой уже после попытки отправки."""
from types import SimpleNamespace

import pytest
from aiogram.fsm.context import FSMContext

from bot.db import repository as db
from bot.handlers.messages import (
    MAX_CAPTION_LENGTH,
    MAX_TEXT_LENGTH,
    _exceeds_length_limit,
    handle_message,
)
from tests.test_send_flow import FakeBot, FakeMessage, FakeUser, make_state


def test_exceeds_length_limit_text():
    assert _exceeds_length_limit("TEXT", "x" * MAX_TEXT_LENGTH) is False
    assert _exceeds_length_limit("TEXT", "x" * (MAX_TEXT_LENGTH + 1)) is True


def test_exceeds_length_limit_caption_types():
    for msg_type in ("PHOTO", "VIDEO", "VOICE", "AUDIO", "ANIMATION", "DOCUMENT"):
        assert _exceeds_length_limit(msg_type, "x" * MAX_CAPTION_LENGTH) is False
        assert _exceeds_length_limit(msg_type, "x" * (MAX_CAPTION_LENGTH + 1)) is True


def test_exceeds_length_limit_sticker_always_false():
    # у стикера нет ни текста, ни подписи — переполнить нечем
    assert _exceeds_length_limit("STICKER", "x" * 100_000) is False


def test_real_telegram_limit_actually_exceeded_by_wrapped_caption():
    """Ровно тот сценарий, который был найден при ревизии: 1000-символьная
    подпись к фото + служебная обёртка реально превышает лимит Telegram
    в 1024 символа — но наша проверка отклоняет её ДО этого момента."""
    text = "x" * 1000
    wrapped = f"У тебя новое сообщение!\n\n{text} \n\nНажми кнопку ниже для ответа"
    assert len(wrapped) > 1024, "проверка должна была устареть, если это условие больше не выполняется"
    assert _exceeds_length_limit("PHOTO", "x" * 1000) is True


@pytest.mark.asyncio
async def test_too_long_text_rejected_before_delivery(uid):
    sender_id, recipient_id = uid(), uid()
    db.create_user_link(recipient_id, f"code-{recipient_id}", "recv", "R")

    state = make_state(sender_id)
    await state.update_data(recipient_id=recipient_id)

    bot = FakeBot()
    long_text = "x" * (MAX_TEXT_LENGTH + 1)
    msg = FakeMessage(FakeUser(sender_id), text=long_text)

    await handle_message(msg, state, bot)

    assert "длинное" in msg.answers[0].lower()
    assert bot.sent == []  # ничего не ушло получателю

    # и не должно было записаться в БД как "отправленное" сообщение
    from bot.db.connection import cursor
    cursor.execute("SELECT COUNT(*) FROM messages WHERE sender_id=? AND recipient_id=?", (sender_id, recipient_id))
    assert cursor.fetchone()[0] == 0


@pytest.mark.asyncio
async def test_too_long_caption_rejected_before_delivery(uid):
    sender_id, recipient_id = uid(), uid()
    db.create_user_link(recipient_id, f"code-{recipient_id}", "recv2", "R2")

    state = make_state(sender_id)
    await state.update_data(recipient_id=recipient_id)

    bot = FakeBot()
    photo = [SimpleNamespace(file_id="P1")]
    msg = FakeMessage(FakeUser(sender_id), caption="x" * (MAX_CAPTION_LENGTH + 1), photo=photo)

    await handle_message(msg, state, bot)

    assert "длинное" in msg.answers[0].lower()
    assert bot.sent == []


@pytest.mark.asyncio
async def test_message_at_exact_limit_is_accepted(uid):
    """Граничный случай: ровно на пределе — должно пройти, не быть отклонено
    за компанию с превышающими лимит."""
    sender_id, recipient_id = uid(), uid()
    db.create_user_link(recipient_id, f"code-{recipient_id}", "recv3", "R3")

    state = make_state(sender_id)
    await state.update_data(recipient_id=recipient_id)

    bot = FakeBot()
    msg = FakeMessage(FakeUser(sender_id), text="x" * MAX_TEXT_LENGTH)

    await handle_message(msg, state, bot)

    assert msg.answers == ["Сообщение отправлено!"]
    assert len(bot.sent) == 1


@pytest.mark.asyncio
async def test_too_long_reply_rejected(uid):
    sender_id, recipient_id = uid(), uid()
    db.create_user_link(recipient_id, f"code-{recipient_id}", "recv4", "R4")

    # сначала реально отправляем короткое сообщение, чтобы получить message_id для ответа
    send_state = make_state(sender_id)
    await send_state.update_data(recipient_id=recipient_id)
    bot = FakeBot()
    await handle_message(FakeMessage(FakeUser(sender_id), text="hi"), send_state, bot)

    from bot.db.connection import cursor
    cursor.execute("SELECT message_id FROM messages WHERE sender_id=? AND recipient_id=?", (sender_id, recipient_id))
    message_id = cursor.fetchone()[0]

    reply_state = make_state(recipient_id)
    await reply_state.update_data(replying_to=message_id)
    long_reply = FakeMessage(FakeUser(recipient_id), text="y" * (MAX_TEXT_LENGTH + 1))

    await handle_message(long_reply, reply_state, bot)

    assert "длинное" in long_reply.answers[0].lower()
    assert len(bot.sent) == 1  # только первое (короткое) сообщение — ответ не ушёл
