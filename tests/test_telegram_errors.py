"""Тесты точной обработки ошибок Telegram API при отправке (bot/services/telegram_errors.py)."""
import pytest
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramEntityTooLarge,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import SendMessage

from bot.db import repository as db
from bot.handlers.messages import handle_message
from tests.test_send_flow import FakeMessage, FakeUser, make_state


def _fake_method_call():
    return SendMessage(chat_id=1, text="x")


class RaisingBot:
    """Поддельный Bot, у которого send_message бросает заданное исключение."""

    def __init__(self, exc: Exception):
        self._exc = exc

    async def send_message(self, **kwargs):
        raise self._exc

    async def send_photo(self, **kwargs):
        raise self._exc


@pytest.mark.parametrize("exc, expected_snippet", [
    (TelegramForbiddenError(_fake_method_call(), "Forbidden: bot was blocked by the user"), "заблокировал бота"),
    (TelegramEntityTooLarge(_fake_method_call(), "Request Entity Too Large"), "слишком большой"),
    (TelegramRetryAfter(_fake_method_call(), "Too Many Requests", retry_after=7), "7 сек"),
    (TelegramBadRequest(_fake_method_call(), "Bad Request: wrong file id"), "некорректные данные"),
    (TelegramNetworkError(_fake_method_call(), "Connection error"), "соединением"),
])
async def test_send_error_gives_precise_message(uid, exc, expected_snippet):
    sender_id, recipient_id = uid(), uid()
    db.create_user_link(recipient_id, f"code-{recipient_id}", "recv", "R")

    state = make_state(sender_id)
    await state.update_data(recipient_id=recipient_id)

    bot = RaisingBot(exc)
    msg = FakeMessage(FakeUser(sender_id), text="привет")

    await handle_message(msg, state, bot)

    assert len(msg.answers) == 1
    assert expected_snippet in msg.answers[0], msg.answers[0]

    # состояние должно быть очищено даже при ошибке доставки
    data = await state.get_data()
    assert "recipient_id" not in data
