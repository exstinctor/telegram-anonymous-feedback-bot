"""Тесты safe_edit_text/safe_edit_caption (F05 из ревью): Telegram отвечает
400 "message is not modified" при повторном показе того же текста/подписи
(двойной клик по кнопке) — это не реальная ошибка и не должна всплывать."""
import pytest
from aiogram.exceptions import TelegramBadRequest

from bot.services.telegram_ui import safe_edit_caption, safe_edit_text


class FakeMethod:
    pass


class FakeMessageOK:
    async def edit_text(self, text, reply_markup=None, **kwargs):
        return None

    async def edit_caption(self, caption, reply_markup=None, **kwargs):
        return None


class FakeMessageNotModified:
    async def edit_text(self, text, reply_markup=None, **kwargs):
        raise TelegramBadRequest(method=FakeMethod(), message="Bad Request: message is not modified")

    async def edit_caption(self, caption, reply_markup=None, **kwargs):
        raise TelegramBadRequest(method=FakeMethod(), message="Bad Request: message is not modified")


class FakeMessageOtherError:
    async def edit_text(self, text, reply_markup=None, **kwargs):
        raise TelegramBadRequest(method=FakeMethod(), message="Bad Request: chat not found")

    async def edit_caption(self, caption, reply_markup=None, **kwargs):
        raise TelegramBadRequest(method=FakeMethod(), message="Bad Request: chat not found")


async def test_safe_edit_text_normal_case_passes_through():
    await safe_edit_text(FakeMessageOK(), "новый текст")  # не должно кидать


async def test_safe_edit_text_swallows_not_modified():
    await safe_edit_text(FakeMessageNotModified(), "тот же текст")  # не должно кидать


async def test_safe_edit_text_reraises_other_errors():
    with pytest.raises(TelegramBadRequest, match="chat not found"):
        await safe_edit_text(FakeMessageOtherError(), "текст")


async def test_safe_edit_caption_swallows_not_modified():
    await safe_edit_caption(FakeMessageNotModified(), "та же подпись")


async def test_safe_edit_caption_reraises_other_errors():
    with pytest.raises(TelegramBadRequest, match="chat not found"):
        await safe_edit_caption(FakeMessageOtherError(), "подпись")
