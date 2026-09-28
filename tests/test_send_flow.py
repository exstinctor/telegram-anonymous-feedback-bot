"""Интеграционный тест ключевого сценария: отправка анонимного сообщения и
ответа на него — через реальный FSMContext и поддельные Bot/Message."""
import asyncio
from types import SimpleNamespace

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bot.db import repository as db
from bot.handlers.messages import handle_message


class FakeUser:
    def __init__(self, id, username=None, first_name="U"):
        self.id = id
        self.username = username
        self.first_name = first_name


class FakeBot:
    def __init__(self):
        self.sent = []

    async def _record(self, method, **kwargs):
        self.sent.append((method, kwargs))

    async def send_message(self, **kwargs):
        await self._record("send_message", **kwargs)

    async def send_photo(self, **kwargs):
        await self._record("send_photo", **kwargs)

    async def send_voice(self, **kwargs):
        await self._record("send_voice", **kwargs)

    async def send_sticker(self, **kwargs):
        await self._record("send_sticker", **kwargs)


class FakeMessage:
    def __init__(self, from_user, text=None, **content):
        self.from_user = from_user
        self.text = text
        self.caption = content.get("caption")
        self.photo = content.get("photo")
        self.video = content.get("video")
        self.voice = content.get("voice")
        self.audio = content.get("audio")
        self.animation = content.get("animation")
        self.sticker = content.get("sticker")
        self.document = content.get("document")
        self.answers = []

    async def answer(self, text, **kwargs):
        self.answers.append(text)


def make_state(user_id: int) -> FSMContext:
    return FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=user_id, user_id=user_id))


@pytest.mark.asyncio
async def test_full_send_flow(uid):
    sender_id, recipient_id = uid(), uid()
    db.create_user_link(recipient_id, f"code-{recipient_id}", "recv", "Receiver")

    state = make_state(sender_id)
    await state.update_data(recipient_id=recipient_id)

    bot = FakeBot()
    sender = FakeUser(sender_id, username="anon_sender")
    msg = FakeMessage(sender, text="Привет, это анонимка!")

    await handle_message(msg, state, bot)

    assert msg.answers == ["Сообщение отправлено!"]
    assert len(bot.sent) == 1
    method, kwargs = bot.sent[0]
    assert method == "send_message"
    assert kwargs["chat_id"] == recipient_id
    assert "Привет, это анонимка!" in kwargs["text"]

    # recipient_id должен быть вычищен из состояния после отправки
    data = await state.get_data()
    assert "recipient_id" not in data

    # сообщение реально сохранилось в БД и на него можно ответить
    from bot.db.connection import cursor
    cursor.execute("SELECT message_id FROM messages WHERE sender_id=? AND recipient_id=?", (sender_id, recipient_id))
    message_id = cursor.fetchone()[0]

    reply_state = make_state(recipient_id)
    await reply_state.update_data(replying_to=message_id)
    reply_msg = FakeMessage(FakeUser(recipient_id), text="Спасибо за сообщение!")
    await handle_message(reply_msg, reply_state, bot)

    assert reply_msg.answers == ["Ответ отправлен!"]
    method2, kwargs2 = bot.sent[1]
    assert method2 == "send_message"
    assert kwargs2["chat_id"] == sender_id
    assert "Спасибо за сообщение!" in kwargs2["text"]


@pytest.mark.asyncio
async def test_cooldown_blocks_second_message(uid):
    sender_id, recipient_id = uid(), uid()
    db.create_user_link(recipient_id, f"code-{recipient_id}", "recv2", "Receiver2")

    state = make_state(sender_id)
    await state.update_data(recipient_id=recipient_id)
    bot = FakeBot()
    sender = FakeUser(sender_id)

    msg1 = FakeMessage(sender, text="первое сообщение")
    await handle_message(msg1, state, bot)
    assert msg1.answers == ["Сообщение отправлено!"]

    # второе сообщение сразу после первого — должно упереться в кулдаун
    await state.update_data(recipient_id=recipient_id)
    msg2 = FakeMessage(sender, text="второе сразу же")
    await handle_message(msg2, state, bot)
    assert "Подождите" in msg2.answers[0]
    assert len(bot.sent) == 1  # второе сообщение реально НЕ ушло получателю


@pytest.mark.asyncio
async def test_blocked_recipient_rejects_message(uid):
    sender_id, recipient_id = uid(), uid()
    db.add_block(recipient_id, sender_id, "blocked_sender")

    state = make_state(sender_id)
    await state.update_data(recipient_id=recipient_id)
    bot = FakeBot()
    msg = FakeMessage(FakeUser(sender_id), text="привет?")

    await handle_message(msg, state, bot)
    assert "заблокированы" in msg.answers[0].lower()
    assert bot.sent == []


@pytest.mark.asyncio
async def test_dangerous_document_rejected(uid):
    sender_id, recipient_id = uid(), uid()
    db.create_user_link(recipient_id, f"code-{recipient_id}", "recv3", "R3")

    state = make_state(sender_id)
    await state.update_data(recipient_id=recipient_id)
    bot = FakeBot()
    doc = SimpleNamespace(file_id="D1", file_name="malware.exe")
    msg = FakeMessage(FakeUser(sender_id), document=doc)

    await handle_message(msg, state, bot)
    assert "запрещён" in msg.answers[0]
    assert bot.sent == []


@pytest.mark.asyncio
async def test_globally_banned_sender_rejected(uid):
    sender_id, recipient_id = uid(), uid()
    db.global_ban(sender_id)

    state = make_state(sender_id)
    await state.update_data(recipient_id=recipient_id)
    bot = FakeBot()
    msg = FakeMessage(FakeUser(sender_id), text="привет")

    await handle_message(msg, state, bot)
    assert "заблокированы в этом боте" in msg.answers[0]
    assert bot.sent == []
