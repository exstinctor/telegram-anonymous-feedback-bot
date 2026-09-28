"""Регрессионный тест на F01 из код-ревью: команды (/cancel и т.п.) должны
прерывать FSM-состояние, а не перехватываться самим FSM-хендлером.

aiogram не даёт Command() приоритета над State-фильтром — побеждает порядок
регистрации хендлеров. Без bot.services.filters.not_a_command на каждом
FSM-состоянии, ожидающем ввод, "/cancel" во время, например, ввода кастомной
ссылки проваливался бы в текстовый обработчик этого состояния (Telegram
кладёт "/cancel" в message.text как обычный текст) и пользователь застревал
в диалоге без возможности выйти. Подтверждено эмпирически через полный
пайплайн aiogram (feed_update), не только через прямой вызов функции —
именно порядок регистрации роутеров и был источником бага.
"""
import time

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, Message, Update, User

from bot.core.states import AdminManagementStates, AdminPremiumStates, BroadcastStates, CustomLinkStates, PromoStates
from bot.db.schema import init_db
from bot.handlers import register_handlers

# aiogram-роутеры прикрепляются к Dispatcher ровно один раз за время жизни
# процесса (повторный include_router того же модуля-роутера кидает
# RuntimeError) — поэтому Dispatcher/Bot собираются один раз на весь модуль,
# а не заново в каждом параметризованном прогоне через фикстуру.
init_db()
_bot = Bot(token="123456:dummy", default=DefaultBotProperties(parse_mode=None))
_dp = Dispatcher(storage=MemoryStorage())
register_handlers(_dp)


@pytest.fixture
def dispatcher_and_bot(monkeypatch):
    monkeypatch.setattr("bot.services.permissions.MAIN_ADMIN_ID", 900001)

    sent = []

    class FakeResult:
        message_id = 999

    async def fake_call(self, method, request_timeout=None):
        sent.append(method)
        return FakeResult()

    monkeypatch.setattr(Bot, "__call__", fake_call)
    return _dp, _bot, sent


@pytest.mark.parametrize("state_obj", [
    CustomLinkStates.waiting_for_code,
    PromoStates.waiting_new_code,
    AdminPremiumStates.waiting_manual_days,
    BroadcastStates.waiting_content,
    AdminManagementStates.waiting_new_admin_id,
])
async def test_cancel_command_escapes_fsm_state(dispatcher_and_bot, uid, state_obj):
    dp, bot, sent = dispatcher_and_bot
    user_id = 900001  # админ — чтобы состояния из admin.py тоже реально попадали в свой хендлер

    key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
    state = FSMContext(storage=dp.storage, key=key)
    await state.set_state(state_obj)

    msg = Message(message_id=1, date=int(time.time()), chat=Chat(id=user_id, type="private"),
                  from_user=User(id=user_id, is_bot=False, first_name="Admin"), text="/cancel")
    update = Update(update_id=uid(), message=msg)

    await dp.feed_update(bot, update)

    final_state = await state.get_state()
    reply_text = getattr(sent[-1], "text", None) if sent else None

    assert final_state is None, f"{state_obj}: состояние не сброшено — /cancel перехвачен FSM-хендлером"
    assert reply_text and "отменено" in reply_text.lower(), f"{state_obj}: /cancel не долетел до cancel_dialog"
