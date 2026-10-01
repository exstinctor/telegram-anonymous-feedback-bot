"""Навигация «Назад» на экранах админ-панели: верхнеуровневые экраны
(статистика, премиум-таблица, бан-лист) возвращают в админ-меню, а не в
случайный другой список."""
from bot.db import repository as db
from bot.handlers import admin as admin_module


def _callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def test_global_ban_list_back_goes_to_admin_menu(uid):
    db.global_ban(uid())
    _text, markup = admin_module._build_global_ban_list_view(0)
    callbacks = _callbacks(markup)
    assert callbacks[-1] == "admin_menu_back"
    assert "admin_users_list_page_0" not in callbacks  # регрессия: раньше «Назад» вёл в список юзеров


def test_global_ban_list_back_stays_last_with_pagination(uid):
    for _ in range(admin_module.BAN_LIST_PAGE_SIZE + 2):
        db.global_ban(uid())
    _text, markup = admin_module._build_global_ban_list_view(0)
    callbacks = _callbacks(markup)
    assert "admin_global_ban_list_page_1" in callbacks  # есть «Далее »
    assert callbacks[-1] == "admin_menu_back"           # «Назад» остаётся последней кнопкой


def test_global_ban_list_empty_back_goes_to_admin_menu(monkeypatch):
    monkeypatch.setattr(db, "count_global_ban_list", lambda: 0)
    text, markup = admin_module._build_global_ban_list_view(0)
    assert "пуст" in text
    assert _callbacks(markup) == ["admin_menu_back"]


# ---------------------------------------------------------------------------
# Итоговые и «пустые» экраны админки не должны быть тупиками: под ними есть
# кнопка возврата — туда, откуда пришёл админ (не всегда в главное меню).
# ---------------------------------------------------------------------------
from types import SimpleNamespace

from bot.core.states import AdminManagementStates, AdminPremiumStates, PromoStates
from bot.handlers import broadcast as broadcast_module
from bot.handlers import callbacks as callbacks_module
from tests.test_admin_search import ReplyMessage
from tests.test_send_flow import FakeUser, make_state

ADMIN_ID = 777  # MAIN_ADMIN_ID из tests/conftest.py


class EditCapture:
    """Поддельное сообщение callback'а: запоминает текст и клавиатуру правки."""

    def __init__(self):
        self.text = None
        self.markup = None

    async def edit_text(self, text, reply_markup=None, **kwargs):
        self.text, self.markup = text, reply_markup


class CbFake:
    def __init__(self, data=None, user_id=ADMIN_ID):
        self.data = data
        self.from_user = FakeUser(user_id)
        self.message = EditCapture()

    async def answer(self, *args, **kwargs):
        pass


async def test_who_blocked_empty_goes_back_to_user_card(uid):
    target = uid()
    cb = CbFake(f"admin_who_blocked_{target}")
    await callbacks_module.admin_who_blocked(cb)
    assert cb.message.text == "Никто не блокировал этого пользователя."
    assert _callbacks(cb.message.markup) == [f"admin_user_{target}"]  # в карточку, а не в меню


async def test_who_blocked_only_non_premium_goes_back_to_user_card(uid):
    target, blocker = uid(), uid()
    db.add_block(blocker, target, "someone")
    cb = CbFake(f"admin_who_blocked_{target}")
    await callbacks_module.admin_who_blocked(cb)
    assert "только пользователи без премиума" in cb.message.text
    assert _callbacks(cb.message.markup) == [f"admin_user_{target}"]


async def test_premium_granted_for_days_goes_back_to_user_card(uid):
    target = uid()
    cb = CbFake(f"admin_premium_add_days_{target}_7")
    await callbacks_module.admin_premium_add_days(cb)
    assert "Премиум выдан" in cb.message.text
    assert _callbacks(cb.message.markup) == [f"admin_user_{target}"]


async def test_premium_removed_goes_back_to_user_card(uid):
    target = uid()
    cb = CbFake(f"admin_premium_remove_{target}")
    await callbacks_module.admin_premium_remove(cb)
    assert "Премиум снят" in cb.message.text
    assert _callbacks(cb.message.markup) == [f"admin_user_{target}"]


async def test_user_not_found_goes_back_to_users_list(uid):
    async def get_me():
        return SimpleNamespace(username="bot")

    cb = CbFake()
    await admin_module.admin_show_user_panel(cb, SimpleNamespace(get_me=get_me), uid())
    assert cb.message.text == "Пользователь не найден."
    assert _callbacks(cb.message.markup) == ["admin_users_list_page_0"]


async def test_manual_premium_result_has_button_to_user_card(uid):
    target = uid()
    state = make_state(ADMIN_ID)
    await state.set_state(AdminPremiumStates.waiting_manual_days)
    await state.update_data(admin_premium_target=target)

    msg = ReplyMessage(FakeUser(ADMIN_ID), text="30")
    await admin_module.admin_set_manual_premium_days(msg, state)
    assert msg.answers[0].startswith("Премиум выдан")
    assert _callbacks(msg.markups[0]) == [f"admin_user_{target}"]


async def test_promo_created_has_button_to_promo_list_but_error_does_not(uid):
    state = make_state(ADMIN_ID)
    await state.set_state(PromoStates.waiting_new_code)

    bad = ReplyMessage(FakeUser(ADMIN_ID), text="только-одно-слово")
    await admin_module.admin_promo_create_finish(bad, state)
    assert bad.markups[0] is None                                   # переспрашиваем — кнопка не нужна
    assert await state.get_state() == PromoStates.waiting_new_code.state

    ok = ReplyMessage(FakeUser(ADMIN_ID), text=f"BACK{uid() % 10**8} 5")
    await admin_module.admin_promo_create_finish(ok, state)
    assert "создан" in ok.answers[0]
    assert _callbacks(ok.markups[0]) == ["admin_promo_list"]
    assert await state.get_state() is None


async def test_admin_appointed_has_button_to_admins_list(uid):
    state = make_state(ADMIN_ID)
    await state.set_state(AdminManagementStates.waiting_new_admin_id)
    msg = ReplyMessage(FakeUser(ADMIN_ID), text=str(uid()))
    await admin_module.admin_manage_add_finish(msg, state)
    assert "назначен админом" in msg.answers[0]
    assert _callbacks(msg.markups[0]) == ["admin_manage_list"]


async def test_broadcast_cancelled_goes_back_to_admin_menu():
    cb = CbFake("admin_broadcast_cancel")
    await broadcast_module.broadcast_cancel(cb, make_state(ADMIN_ID))
    assert cb.message.text == "Рассылка отменена."
    assert _callbacks(cb.message.markup) == ["admin_menu_back"]


async def test_broadcast_lost_state_goes_back_to_admin_menu():
    cb = CbFake("admin_broadcast_confirm")
    await broadcast_module.broadcast_confirm(cb, make_state(ADMIN_ID), bot=None)  # состояния нет → «данные потеряны»
    assert "Данные рассылки потеряны" in cb.message.text
    assert _callbacks(cb.message.markup) == ["admin_menu_back"]
