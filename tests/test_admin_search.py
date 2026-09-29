"""Тесты поиска пользователей в админке (кнопка «Найти пользователя» и /find).

БД общая на всю тестовую сессию, поэтому в каждом тесте искомые строки
содержат уникальный маркер из uid() — так чужие пользователи не попадают
в выдачу и не ломают счётчики.
"""
from aiogram.filters import CommandObject

from bot.core.states import AdminSearchStates
from bot.db import repository as db
from bot.handlers.admin import (
    SEARCH_RESULTS_LIMIT,
    admin_find_command,
    admin_search_finish,
    admin_search_start,
    admin_show_users_list,
)
from tests.test_send_flow import FakeUser, make_state
from tests.test_stats_and_broadcast import FakeCallback

ADMIN_ID = 777  # совпадает с MAIN_ADMIN_ID из tests/conftest.py


class ReplyMessage:
    """Сообщение, запоминающее и текст ответа, и клавиатуру (FakeMessage из
    test_send_flow клавиатуру не сохраняет)."""

    def __init__(self, from_user, text=None):
        self.from_user = from_user
        self.text = text
        self.answers = []
        self.markups = []

    async def answer(self, text, reply_markup=None, **kwargs):
        self.answers.append(text)
        self.markups.append(reply_markup)


def _add_user(user_id, username=None, first_name=None):
    db.create_user_link(user_id, f"code-{user_id}", username, first_name)


def _button_callbacks(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row]


# ---------------------------------------------------------------------------
# Репозиторий
# ---------------------------------------------------------------------------


def test_search_by_exact_user_id(uid):
    target = uid()
    _add_user(target, "someone", "Some")
    assert [row[0] for row in db.search_users(str(target))] == [target]


def test_search_by_username_ignores_at_sign_and_case(uid):
    target = uid()
    _add_user(target, f"MixedCase{target}", "Name")
    for query in (f"@mixedcase{target}", f"MIXEDCASE{target}", f"  @MixedCase{target}  "):
        assert [row[0] for row in db.search_users(query)] == [target], query


def test_search_cyrillic_name_is_case_insensitive(uid):
    """Штатный LIKE в SQLite регистронезависим только для ASCII — «иван» не
    находил бы «Иван» без функции PYLOWER."""
    target = uid()
    _add_user(target, None, f"Иван{target}")
    assert [row[0] for row in db.search_users(f"иван{target}")] == [target]
    assert [row[0] for row in db.search_users(f"ИВАН{target}")] == [target]


def test_search_matches_part_of_name(uid):
    target = uid()
    _add_user(target, None, f"Александра{target}")
    assert [row[0] for row in db.search_users(f"ксандра{target}")] == [target]


def test_search_ranks_exact_username_before_partial(uid):
    exact, partial = uid(), uid()
    token = f"rank{exact}"
    _add_user(partial, f"x_{token}_y", "Partial")
    _add_user(exact, token, "Exact")
    ids = [row[0] for row in db.search_users(token)]
    assert ids == [exact, partial]


def test_search_wildcards_are_escaped(uid):
    a, b = uid(), uid()
    _add_user(a, f"qa_b{a}", "Underscore")
    _add_user(b, f"qaXb{a}", "Letter")
    assert [row[0] for row in db.search_users(f"qa_b{a}")] == [a]
    # «%» ищется как обычный символ, а не превращается в «найти всех»:
    # ни у одного тестового пользователя его нет ни в имени, ни в username
    assert db.count_users_matching("%") == 0
    assert db.search_users("%") == []


def test_search_empty_or_whitespace_query_returns_nothing():
    for query in ("", "   ", "@", " @ "):
        assert db.search_users(query) == []
        assert db.count_users_matching(query) == 0


def test_search_huge_number_does_not_overflow():
    assert db.search_users("9" * 40) == []
    assert db.count_users_matching("9" * 40) == 0


def test_search_limit_and_total_count(uid):
    base = uid()
    token = f"many{base}"
    for i in range(SEARCH_RESULTS_LIMIT + 3):
        _add_user(uid(), f"{token}_{i}", "Bulk")
    assert len(db.search_users(token, limit=SEARCH_RESULTS_LIMIT)) == SEARCH_RESULTS_LIMIT
    assert db.count_users_matching(token) == SEARCH_RESULTS_LIMIT + 3


# ---------------------------------------------------------------------------
# Обработчики
# ---------------------------------------------------------------------------


async def test_users_list_has_search_button(uid):
    _add_user(uid(), "listed", "Listed")
    cb = FakeCallback(FakeUser(ADMIN_ID))
    captured = {}

    async def edit_text(text, reply_markup=None):
        captured["markup"] = reply_markup

    cb.message.edit_text = edit_text
    await admin_show_users_list(cb, page=0)
    assert "admin_search_start" in _button_callbacks(captured["markup"])


async def test_search_start_sets_state_for_admin(uid):
    state = make_state(ADMIN_ID)
    cb = FakeCallback(FakeUser(ADMIN_ID))
    await admin_search_start(cb, state)
    assert await state.get_state() == AdminSearchStates.waiting_query.state
    assert cb.message.replies  # подсказка отправлена


async def test_search_start_denied_for_regular_user(uid):
    user = uid()
    state = make_state(user)
    cb = FakeCallback(FakeUser(user))
    await admin_search_start(cb, state)
    assert await state.get_state() is None
    assert not cb.message.replies


async def test_search_finish_shows_results_and_clears_state(uid):
    target = uid()
    _add_user(target, f"found{target}", "Найденный")
    state = make_state(ADMIN_ID)
    await state.set_state(AdminSearchStates.waiting_query)

    msg = ReplyMessage(FakeUser(ADMIN_ID), text=f"@found{target}")
    await admin_search_finish(msg, state)

    assert "Найдено: 1" in msg.answers[0]
    callbacks = _button_callbacks(msg.markups[0])
    assert f"admin_user_{target}" in callbacks       # ведёт в обычную карточку пользователя
    assert "admin_search_start" in callbacks         # «Искать ещё»
    assert "admin_users_list_page_0" in callbacks    # «К списку»
    assert await state.get_state() is None


async def test_search_finish_no_results_keeps_state_for_retry(uid):
    state = make_state(ADMIN_ID)
    await state.set_state(AdminSearchStates.waiting_query)

    msg = ReplyMessage(FakeUser(ADMIN_ID), text=f"нет-такого-{uid()}")
    await admin_search_finish(msg, state)

    assert "Никого не нашёл" in msg.answers[0]
    assert await state.get_state() == AdminSearchStates.waiting_query.state


async def test_search_finish_empty_text_keeps_state(uid):
    state = make_state(ADMIN_ID)
    await state.set_state(AdminSearchStates.waiting_query)

    msg = ReplyMessage(FakeUser(ADMIN_ID), text=None)  # например, прислали фото
    await admin_search_finish(msg, state)

    assert "Отправьте текст" in msg.answers[0]
    assert await state.get_state() == AdminSearchStates.waiting_query.state


async def test_search_finish_denied_for_non_admin(uid):
    user = uid()
    target = uid()
    _add_user(target, f"secret{target}", "Secret")
    state = make_state(user)
    await state.set_state(AdminSearchStates.waiting_query)

    msg = ReplyMessage(FakeUser(user), text=f"secret{target}")
    await admin_search_finish(msg, state)

    assert msg.answers == ["❌ У вас нет доступа."]
    assert msg.markups == [None]
    assert await state.get_state() is None


async def test_search_finish_reports_when_results_truncated(uid):
    token = f"trunc{uid()}"
    for i in range(SEARCH_RESULTS_LIMIT + 2):
        _add_user(uid(), f"{token}_{i}", "Bulk")
    state = make_state(ADMIN_ID)
    await state.set_state(AdminSearchStates.waiting_query)

    msg = ReplyMessage(FakeUser(ADMIN_ID), text=token)
    await admin_search_finish(msg, state)

    assert f"Найдено: {SEARCH_RESULTS_LIMIT + 2}" in msg.answers[0]
    assert f"показаны первые {SEARCH_RESULTS_LIMIT}" in msg.answers[0]


async def test_find_command_usage_without_args():
    msg = ReplyMessage(FakeUser(ADMIN_ID))
    await admin_find_command(msg, CommandObject(command="find", args=None), make_state(ADMIN_ID))
    assert msg.answers[0].startswith("Использование: /find")


async def test_find_command_returns_results(uid):
    target = uid()
    _add_user(target, f"cmd{target}", "Cmd")
    msg = ReplyMessage(FakeUser(ADMIN_ID))
    await admin_find_command(msg, CommandObject(command="find", args=f"cmd{target}"), make_state(ADMIN_ID))
    assert f"admin_user_{target}" in _button_callbacks(msg.markups[0])


async def test_find_command_clears_pending_input_state(uid):
    """/find посреди другого ввода не должен оставлять старое ожидание висеть."""
    target = uid()
    _add_user(target, f"clr{target}", "Clr")
    state = make_state(ADMIN_ID)
    await state.set_state(AdminSearchStates.waiting_query)

    msg = ReplyMessage(FakeUser(ADMIN_ID))
    await admin_find_command(msg, CommandObject(command="find", args=f"clr{target}"), state)
    assert await state.get_state() is None


async def test_find_command_denied_for_regular_user(uid):
    user = uid()
    msg = ReplyMessage(FakeUser(user))
    await admin_find_command(msg, CommandObject(command="find", args="anyone"), make_state(user))
    assert msg.answers == ["❌ У вас нет доступа."]
