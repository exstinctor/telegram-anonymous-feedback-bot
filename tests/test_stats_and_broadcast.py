"""Тесты новых админ-фич: статистика и рассылка (найдены как часто
встречающиеся в похожих ботах, но отсутствовавшие в этом проекте)."""
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext

from bot.core.states import BroadcastStates
from bot.db import repository as db
from bot.db.premium import add_or_extend_premium, count_active_premium
from bot.handlers.admin import admin_show_stats
from bot.handlers.broadcast import broadcast_cancel, broadcast_confirm, broadcast_preview, broadcast_start
from tests.test_send_flow import FakeMessage, FakeUser, make_state


class FakeCallback:
    """Минимальный поддельный CallbackQuery для тестов статистики/рассылки."""

    def __init__(self, from_user, data=None, message_text=None):
        self.from_user = from_user
        self.data = data
        self.answers = []
        self.message = FakeCallbackMessage(message_text)

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text or "")


class FakeCallbackMessage:
    def __init__(self, text=None):
        self.text = text
        self.edits = []
        self.replies = []
        self.answers = []

    async def edit_text(self, text, reply_markup=None):
        self.edits.append(text)

    async def reply(self, text, **kwargs):
        self.replies.append(text)

    async def answer(self, text, **kwargs):
        self.answers.append(text)


class BroadcastFakeBot:
    """Поддельный Bot для теста рассылки: часть получателей "заблокировала" бота."""

    def __init__(self, forbidden_user_ids=()):
        self.forbidden = set(forbidden_user_ids)
        self.sent_to = []

    async def send_message(self, chat_id, text, **kwargs):
        if chat_id in self.forbidden:
            raise TelegramForbiddenError(method=None, message="Forbidden: bot was blocked by the user")
        self.sent_to.append(chat_id)


# ---------------------------------------------------------------------------
# Репозиторий: счётчики статистики
# ---------------------------------------------------------------------------


def test_stat_counters_reflect_real_data(uid):
    sender_id, recipient_id = uid(), uid()
    db.create_user_link(sender_id, f"c1-{sender_id}", "s", "S")
    db.create_user_link(recipient_id, f"c2-{recipient_id}", "r", "R")

    before_msgs = db.count_messages()
    before_replies = db.count_replies()

    mid = db.insert_message(sender_id, recipient_id, "s", "S", "hello")
    db.insert_reply(mid, recipient_id, "hi back")

    assert db.count_messages() == before_msgs + 1
    assert db.count_replies() == before_replies + 1

    before_blocked = db.count_blocked_pairs()
    db.add_block(recipient_id, sender_id, "s")
    assert db.count_blocked_pairs() == before_blocked + 1

    before_promo = db.count_promo_codes()
    code = f"STAT{sender_id}"
    db.create_promo_code(code, days=1, max_uses=None, created_by=sender_id)
    assert db.count_promo_codes() == before_promo + 1

    before_redemptions = db.count_promo_redemptions()
    db.redeem_promo_code(code, recipient_id)
    assert db.count_promo_redemptions() == before_redemptions + 1


def test_count_active_premium(uid):
    user_id = uid()
    before = count_active_premium()
    add_or_extend_premium(user_id, 5)
    assert count_active_premium() == before + 1


def test_get_all_user_ids_includes_created_users(uid):
    user_id = uid()
    db.create_user_link(user_id, f"allids-{user_id}", "u", "U")
    assert user_id in db.get_all_user_ids()


async def test_admin_show_stats_renders_numbers(uid, monkeypatch):
    import bot.handlers.admin as admin_module
    monkeypatch.setattr("bot.services.permissions.MAIN_ADMIN_ID", 777)

    callback = FakeCallback(FakeUser(777))
    await admin_show_stats(callback)

    text = callback.message.edits[0]
    assert "Статистика" in text
    assert "Пользователей:" in text
    assert "Активных премиум:" in text
    assert "Промокодов создано:" in text


# ---------------------------------------------------------------------------
# Рассылка
# ---------------------------------------------------------------------------


async def test_broadcast_full_flow_with_some_blocked_users(uid, monkeypatch):
    import bot.handlers.broadcast as broadcast_module
    monkeypatch.setattr("bot.services.permissions.MAIN_ADMIN_ID", 777)
    monkeypatch.setattr(broadcast_module, "BROADCAST_DELAY_SECONDS", 0)  # без реальных задержек в тесте

    admin_id = 777
    live_users = [uid(), uid()]
    blocked_user = uid()
    for i, u in enumerate(live_users + [blocked_user]):
        db.create_user_link(u, f"bc-{u}", f"u{i}", f"U{i}")

    state = make_state(admin_id)

    # шаг 1: старт рассылки -> экран выбора аудитории, состояние ещё не выставлено
    start_cb = FakeCallback(FakeUser(admin_id))
    await broadcast_module.broadcast_start(start_cb, state)
    assert await state.get_state() is None
    assert "Кому разослать" in start_cb.message.edits[0]

    # шаг 2: выбор аудитории -> экран выбора звука
    audience_cb = FakeCallback(FakeUser(admin_id), data="admin_broadcast_audience_all")
    await broadcast_module.broadcast_audience_chosen(audience_cb, state)
    assert (await state.get_data())["audience"] == "all"
    assert "звук" in audience_cb.message.edits[0].lower()

    # шаг 3: выбор звука -> состояние переходит в waiting_content
    silent_cb = FakeCallback(FakeUser(admin_id), data="admin_broadcast_silent_no")
    await broadcast_module.broadcast_silent_chosen(silent_cb, state)
    assert await state.get_state() == BroadcastStates.waiting_content.state
    assert (await state.get_data())["silent"] is False

    # шаг 4: админ присылает контент -> предпросмотр с кнопками
    preview_msg = FakeMessage(FakeUser(admin_id), text="Важное объявление всем!")
    await broadcast_preview(preview_msg, state)
    assert "Важное объявление" in preview_msg.answers[0]
    assert await state.get_state() is None  # состояние снято, но данные ещё живы

    data = await state.get_data()
    assert data["content_text"] == "Важное объявление всем!"
    assert data["msg_type"] == "TEXT"

    # шаг 5: подтверждение — реально разослать
    bot = BroadcastFakeBot(forbidden_user_ids={blocked_user})
    confirm_cb = FakeCallback(FakeUser(admin_id))
    await broadcast_confirm(confirm_cb, state, bot)

    assert set(live_users).issubset(bot.sent_to)
    assert blocked_user not in bot.sent_to
    result_text = confirm_cb.message.answers[0]
    assert "доставлено" in result_text
    assert "не доставлено" in result_text

    # состояние должно быть полностью очищено после рассылки
    assert await state.get_data() == {}


async def test_broadcast_cancel_clears_state(uid, monkeypatch):
    import bot.handlers.broadcast as broadcast_module
    monkeypatch.setattr("bot.services.permissions.MAIN_ADMIN_ID", 777)

    admin_id = 777
    state = make_state(admin_id)
    await state.set_state(BroadcastStates.waiting_content)
    await state.update_data(broadcast_text="черновик")

    cancel_cb = FakeCallback(FakeUser(admin_id))
    await broadcast_cancel(cancel_cb, state)

    assert await state.get_state() is None
    assert await state.get_data() == {}
    assert "отменена" in cancel_cb.message.edits[0].lower()


async def test_broadcast_denied_for_non_admin(uid, monkeypatch):
    import bot.handlers.broadcast as broadcast_module
    monkeypatch.setattr("bot.services.permissions.MAIN_ADMIN_ID", 777)

    stranger_id = uid()
    state = make_state(stranger_id)
    cb = FakeCallback(FakeUser(stranger_id))
    await broadcast_start(cb, state)

    assert await state.get_state() is None  # ничего не запустилось
    assert "Нет доступа" in cb.answers[0]


async def test_broadcast_confirm_without_text_does_not_crash(uid, monkeypatch):
    """Если данные из FSM почему-то потерялись (например, между шагами
    прошло слишком много времени с MemoryStorage при рестарте) — подтверждение
    не должно падать с KeyError, а вежливо сообщить об этом."""
    import bot.handlers.broadcast as broadcast_module
    monkeypatch.setattr("bot.services.permissions.MAIN_ADMIN_ID", 777)

    admin_id = 777
    state = make_state(admin_id)  # ничего не клали в state.data

    bot = BroadcastFakeBot()
    confirm_cb = FakeCallback(FakeUser(admin_id))
    await broadcast_confirm(confirm_cb, state, bot)

    assert "потерян" in confirm_cb.message.edits[0]
    assert bot.sent_to == []


async def test_broadcast_retries_once_after_rate_limit(monkeypatch):
    """F16 из ревью: TelegramRetryAfter раньше считался обычной неудачей без
    единой попытки повтора. Теперь после первого RetryAfter ждём и пробуем
    ещё раз; если рейт-лимит повторился — сдаёмся."""
    import bot.handlers.broadcast as broadcast_module
    from aiogram.exceptions import TelegramRetryAfter
    monkeypatch.setattr(broadcast_module.asyncio, "sleep", _instant_sleep)

    calls = {"n": 0}

    class FlakyBot:
        async def send_message(self, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise TelegramRetryAfter(method=None, message="Too Many Requests", retry_after=1)
            # вторая попытка — успех

    ok = await broadcast_module._send_one(FlakyBot(), 12345, "TEXT", {}, "привет", False)
    assert ok is True
    assert calls["n"] == 2  # реально была одна повторная попытка


async def test_broadcast_gives_up_after_second_rate_limit(monkeypatch):
    import bot.handlers.broadcast as broadcast_module
    from aiogram.exceptions import TelegramRetryAfter
    monkeypatch.setattr(broadcast_module.asyncio, "sleep", _instant_sleep)

    class AlwaysLimitedBot:
        async def send_message(self, **kwargs):
            raise TelegramRetryAfter(method=None, message="Too Many Requests", retry_after=1)

    ok = await broadcast_module._send_one(AlwaysLimitedBot(), 12345, "TEXT", {}, "привет", False)
    assert ok is False  # сдались после одного повтора, а не зависли в бесконечном цикле


async def _instant_sleep(_seconds):
    return None


async def test_premium_list_pagination(uid, monkeypatch):
    """F13 из ревью: премиум-таблица раньше выводилась одним экраном без
    пагинации, как список пользователей до соответствующего фикса."""
    import bot.handlers.admin as admin_module
    monkeypatch.setattr("bot.services.permissions.MAIN_ADMIN_ID", 777)

    for _ in range(15):
        add_or_extend_premium(uid(), 5)

    cb = FakeCallback(FakeUser(777))
    await admin_module.admin_show_premium_list(cb, page=0)
    text0 = cb.message.edits[0]
    assert "Страница 1/" in text0

    cb2 = FakeCallback(FakeUser(777))
    await admin_module.admin_show_premium_list(cb2, page=1)
    text1 = cb2.message.edits[0]
    assert "Страница 2/" in text1
    assert text0 != text1  # разные страницы показывают разные записи


async def test_admin_banlist_command(uid, monkeypatch):
    """Новая админская /banlist (глобальный бан-лист) — не путать с
    пользовательским /blocklist (личные блокировки, moderation.py)."""
    import bot.handlers.admin as admin_module
    monkeypatch.setattr("bot.services.permissions.MAIN_ADMIN_ID", 777)

    target_id = uid()
    db.global_ban(target_id)

    msg = FakeMessage(FakeUser(777))
    await admin_module.admin_banlist_command(msg)
    # БД общая на всю тестовую сессию — банов от других тестов может быть
    # уже больше одной страницы, так что конкретный target_id не обязан
    # попасть именно на первую страницу. Проверяем сам факт бана в БД,
    # а не его присутствие в тексте конкретной страницы.
    assert "Глобально забаненные" in msg.answers[0]
    assert db.is_globally_banned(target_id) is True


async def test_admin_banlist_command_denied_for_non_admin(uid, monkeypatch):
    import bot.handlers.admin as admin_module
    monkeypatch.setattr("bot.services.permissions.MAIN_ADMIN_ID", 777)

    msg = FakeMessage(FakeUser(uid()))
    await admin_module.admin_banlist_command(msg)
    assert "нет доступа" in msg.answers[0].lower()


async def test_admin_unban_command_removes_global_ban(uid, monkeypatch):
    import bot.handlers.admin as admin_module
    monkeypatch.setattr("bot.services.permissions.MAIN_ADMIN_ID", 777)

    target_id = uid()
    db.global_ban(target_id)
    assert db.is_globally_banned(target_id) is True

    msg = FakeMessage(FakeUser(777), text=f"/unban {target_id}")
    await admin_module.admin_unban_command(msg, CommandObject(command="unban", args=str(target_id)))

    assert "снят" in msg.answers[0].lower()
    assert db.is_globally_banned(target_id) is False


async def test_admin_unban_command_rejects_non_numeric_args(monkeypatch):
    import bot.handlers.admin as admin_module
    monkeypatch.setattr("bot.services.permissions.MAIN_ADMIN_ID", 777)

    msg = FakeMessage(FakeUser(777), text="/unban @someone")
    await admin_module.admin_unban_command(msg, CommandObject(command="unban", args="@someone"))
    assert "Использование" in msg.answers[0]


async def test_admin_unban_command_denied_for_non_admin(uid, monkeypatch):
    import bot.handlers.admin as admin_module
    monkeypatch.setattr("bot.services.permissions.MAIN_ADMIN_ID", 777)

    target_id = uid()
    db.global_ban(target_id)
    stranger_id = uid()

    msg = FakeMessage(FakeUser(stranger_id), text=f"/unban {target_id}")
    await admin_module.admin_unban_command(msg, CommandObject(command="unban", args=str(target_id)))

    assert "нет доступа" in msg.answers[0].lower()
    assert db.is_globally_banned(target_id) is True  # бан не должен был сняться
