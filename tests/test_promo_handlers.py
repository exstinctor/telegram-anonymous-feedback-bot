"""Тесты хендлеров промокодов: /promo (пользователь) и админская FSM-форма создания."""
import pytest
from aiogram.filters import CommandObject

from bot.core.states import PromoStates
from bot.db import repository as db
from bot.db.premium import is_premium
from bot.handlers.admin import admin_promo_create_finish
from bot.handlers.promo import redeem_promo
from tests.test_send_flow import FakeMessage, FakeUser, make_state


async def test_user_redeems_valid_promo(uid):
    admin_id, user_id = uid(), uid()
    code = f"WELCOME{admin_id}"
    db.create_promo_code(code, days=7, max_uses=None, created_by=admin_id)

    msg = FakeMessage(FakeUser(user_id), text=f"/promo {code}")
    await redeem_promo(msg, CommandObject(command="promo", args=code))

    assert "активирован" in msg.answers[0].lower()
    assert is_premium(user_id) is True


async def test_user_redeems_unknown_promo(uid):
    user_id = uid()
    msg = FakeMessage(FakeUser(user_id), text="/promo NOSUCH")
    await redeem_promo(msg, CommandObject(command="promo", args="NOSUCH"))
    assert "не существует" in msg.answers[0]


async def test_user_redeems_same_promo_twice(uid):
    admin_id, user_id = uid(), uid()
    code = f"ONE{admin_id}"
    db.create_promo_code(code, days=1, max_uses=None, created_by=admin_id)

    msg1 = FakeMessage(FakeUser(user_id), text=f"/promo {code}")
    await redeem_promo(msg1, CommandObject(command="promo", args=code))
    assert "активирован" in msg1.answers[0].lower()

    # Обходим кулдаун между попытками намеренно — здесь проверяем именно
    # логику "уже использован", а не лимитер (он отдельно покрыт
    # test_promo_attempts_are_rate_limited ниже).
    from bot.services import antiflood
    antiflood._last_promo_attempt.pop(user_id, None)

    msg2 = FakeMessage(FakeUser(user_id), text=f"/promo {code}")
    await redeem_promo(msg2, CommandObject(command="promo", args=code))
    assert "уже активировали" in msg2.answers[0]


async def test_promo_without_args():
    msg = FakeMessage(FakeUser(1), text="/promo")
    await redeem_promo(msg, CommandObject(command="promo", args=None))
    assert "Использование" in msg.answers[0]


async def test_admin_creates_promo_via_fsm(uid, monkeypatch):
    import bot.handlers.admin as admin_module
    monkeypatch.setattr("bot.services.permissions.MAIN_ADMIN_ID", 777)

    admin_id = 777
    state = make_state(admin_id)
    await state.set_state(PromoStates.waiting_new_code)

    code = f"FSMCODE{uid()}"
    msg = FakeMessage(FakeUser(admin_id), text=f"{code} 5 20")
    await admin_promo_create_finish(msg, state)

    assert "создан" in msg.answers[0]
    row = db.get_promo_code(code)
    assert row is not None
    assert row[1] == 5   # days
    assert row[2] == 20  # max_uses

    # состояние должно быть очищено после успешного создания
    assert await state.get_state() is None


async def test_admin_promo_bad_format_reprompts(uid, monkeypatch):
    import bot.handlers.admin as admin_module
    monkeypatch.setattr("bot.services.permissions.MAIN_ADMIN_ID", 777)

    admin_id = 777
    state = make_state(admin_id)
    await state.set_state(PromoStates.waiting_new_code)

    msg = FakeMessage(FakeUser(admin_id), text="totally not valid")
    await admin_promo_create_finish(msg, state)

    assert "Формат" in msg.answers[0]
    # состояние НЕ должно быть очищено — даём попробовать ещё раз
    assert await state.get_state() == PromoStates.waiting_new_code.state


async def test_non_admin_cannot_create_promo(uid, monkeypatch):
    import bot.handlers.admin as admin_module
    monkeypatch.setattr("bot.services.permissions.MAIN_ADMIN_ID", 777)

    stranger_id = uid()
    state = make_state(stranger_id)
    await state.set_state(PromoStates.waiting_new_code)

    msg = FakeMessage(FakeUser(stranger_id), text="HACK 999")
    await admin_promo_create_finish(msg, state)

    assert "нет доступа" in msg.answers[0].lower()
    assert db.get_promo_code("HACK") is None


async def test_promo_attempts_are_rate_limited(uid):
    """Раньше /promo не имел вообще никакого ограничения скорости — можно было
    перебирать короткие коды скриптом без задержки. Теперь вторая попытка
    сразу после первой должна упереться в кулдаун, а не дойти до БД."""
    admin_id, user_id = uid(), uid()
    code = f"RATELIMIT{admin_id}"
    db.create_promo_code(code, days=5, max_uses=None, created_by=admin_id)

    msg1 = FakeMessage(FakeUser(user_id), text=f"/promo {code}")
    await redeem_promo(msg1, CommandObject(command="promo", args=code))
    assert "активирован" in msg1.answers[0].lower()

    # сразу вторая попытка (пусть даже неверным кодом) — должна быть отклонена
    # по кулдауну, а не как "уже активировали" или "не существует"
    msg2 = FakeMessage(FakeUser(user_id), text="/promo GUESS2")
    await redeem_promo(msg2, CommandObject(command="promo", args="GUESS2"))
    assert "слишком часто" in msg2.answers[0].lower()


async def test_promo_cooldown_is_per_user(uid):
    """Кулдаун не должен задевать других пользователей — иначе розыгрыш с
    множеством одновременных участников был бы сломан."""
    admin_id, user_a, user_b = uid(), uid(), uid()
    code = f"SHARED{admin_id}"
    db.create_promo_code(code, days=5, max_uses=None, created_by=admin_id)

    msg_a = FakeMessage(FakeUser(user_a), text=f"/promo {code}")
    await redeem_promo(msg_a, CommandObject(command="promo", args=code))
    assert "активирован" in msg_a.answers[0].lower()

    # другой пользователь сразу следом — не должен упереться в чужой кулдаун
    msg_b = FakeMessage(FakeUser(user_b), text=f"/promo {code}")
    await redeem_promo(msg_b, CommandObject(command="promo", args=code))
    assert "активирован" in msg_b.answers[0].lower()
