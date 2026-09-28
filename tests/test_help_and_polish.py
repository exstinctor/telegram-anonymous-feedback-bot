"""Тесты доработок из ревизии: /help, /createpromo, нормализация промокодов,
и то, что глобальный бан теперь реально "полностью игнорирует" пользователя
во всех пользовательских командах (/promo, /blocklist, /unblock),
как и заявлено в README — раньше эти команды бан не проверяли."""
from aiogram.filters import CommandObject

from bot.db import repository as db
from bot.handlers.admin import create_promo_command, admin_promo_create_finish, _parse_and_create_promo
from bot.handlers.moderation import blocklist, unblock
from bot.handlers.promo import redeem_promo
from bot.handlers.start import help_command
from tests.test_send_flow import FakeMessage, FakeUser, make_state


async def test_help_command_shows_admin_extra_only_to_admin(monkeypatch):
    import bot.handlers.start as start_module
    monkeypatch.setattr("bot.services.permissions.MAIN_ADMIN_ID", 777)

    regular = FakeMessage(FakeUser(1))
    await help_command(regular)
    assert "/start" in regular.answers[0]
    assert "Админские команды" not in regular.answers[0]

    admin_msg = FakeMessage(FakeUser(777))
    await help_command(admin_msg)
    assert "Админские команды" in admin_msg.answers[0]
    assert "/createpromo" in admin_msg.answers[0]


async def test_help_blocked_for_globally_banned_user(uid):
    user_id = uid()
    db.global_ban(user_id)
    msg = FakeMessage(FakeUser(user_id))
    await help_command(msg)
    assert "заблокированы в этом боте" in msg.answers[0]


async def test_promo_code_normalized_to_uppercase(uid):
    admin_id, user_id = uid(), uid()
    code_mixed = f"summer{admin_id}"
    db.create_promo_code(code_mixed.upper(), days=5, max_uses=None, created_by=admin_id)

    msg = FakeMessage(FakeUser(user_id), text=f"/promo {code_mixed}")
    await redeem_promo(msg, CommandObject(command="promo", args=code_mixed))
    assert "активирован" in msg.answers[0].lower()


async def test_promo_blocked_for_globally_banned_user(uid):
    admin_id, user_id = uid(), uid()
    code = f"BANTEST{admin_id}"
    db.create_promo_code(code, days=5, max_uses=None, created_by=admin_id)
    db.global_ban(user_id)

    msg = FakeMessage(FakeUser(user_id), text=f"/promo {code}")
    await redeem_promo(msg, CommandObject(command="promo", args=code))
    assert "заблокированы в этом боте" in msg.answers[0]
    # промокод не должен был погаситься попыткой забаненного пользователя
    ok, _, error = db.redeem_promo_code(code, uid())
    assert ok is True  # код всё ещё свеж для реального (не забаненного) пользователя


async def test_blocklist_and_unblock_blocked_for_globally_banned_user(uid):
    user_id = uid()
    db.global_ban(user_id)

    msg1 = FakeMessage(FakeUser(user_id))
    await blocklist(msg1)
    assert "заблокированы в этом боте" in msg1.answers[0]

    msg2 = FakeMessage(FakeUser(user_id), text="/unblock @someone")
    await unblock(msg2, CommandObject(command="unblock", args="@someone"))
    assert "заблокированы в этом боте" in msg2.answers[0]


async def test_parse_and_create_promo_rejects_zero_max_uses(uid):
    admin_id = uid()
    ok, text = _parse_and_create_promo([f"ZEROTEST{admin_id}", "5", "0"], admin_id)
    assert ok is False
    assert "больше нуля" in text
    assert db.get_promo_code(f"ZEROTEST{admin_id}") is None


async def test_createpromo_command_admin_only(monkeypatch, uid):
    import bot.handlers.admin as admin_module
    monkeypatch.setattr("bot.services.permissions.MAIN_ADMIN_ID", 777)

    stranger_msg = FakeMessage(FakeUser(uid()), text="/createpromo HACK 5")
    await create_promo_command(stranger_msg, CommandObject(command="createpromo", args="HACK 5"))
    assert "нет доступа" in stranger_msg.answers[0].lower()
    assert db.get_promo_code("HACK") is None


async def test_createpromo_command_success(monkeypatch, uid):
    import bot.handlers.admin as admin_module
    monkeypatch.setattr("bot.services.permissions.MAIN_ADMIN_ID", 777)

    code = f"QUICK{uid()}"
    admin_msg = FakeMessage(FakeUser(777), text=f"/createpromo {code} 4 10")
    await create_promo_command(admin_msg, CommandObject(command="createpromo", args=f"{code} 4 10"))
    assert "создан" in admin_msg.answers[0]

    row = db.get_promo_code(code)
    assert row is not None
    assert row[1] == 4    # days
    assert row[2] == 10   # max_uses


async def test_createpromo_and_fsm_share_same_validation(monkeypatch, uid):
    """FSM-форма и команда должны одинаково валидировать вход — проверяем,
    что обе используют один и тот же общий код (_parse_and_create_promo),
    а не разъехавшиеся копии."""
    import bot.handlers.admin as admin_module
    monkeypatch.setattr("bot.services.permissions.MAIN_ADMIN_ID", 777)

    admin_id = 777
    code = f"SHARED{uid()}"

    state = make_state(admin_id)
    from bot.core.states import PromoStates
    await state.set_state(PromoStates.waiting_new_code)
    fsm_msg = FakeMessage(FakeUser(admin_id), text=f"{code} 3 0")
    await admin_promo_create_finish(fsm_msg, state)
    assert "больше нуля" in fsm_msg.answers[0]
    assert db.get_promo_code(code) is None
    # состояние осталось — переспросили, а не отменили попытку
    assert await state.get_state() == PromoStates.waiting_new_code.state
