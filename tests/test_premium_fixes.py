"""Тесты фиксов F02 (UTC вместо local time), F08 (валидация days>0),
F09 (except sqlite3.Error вместо голого except Exception) в bot/db/premium.py."""
from datetime import datetime, timedelta, timezone

import pytest

from bot.db.premium import _now, add_or_extend_premium, is_premium


def test_now_returns_utc_not_local():
    """F02: _now() должна быть привязана к UTC, а не к таймзоне сервера —
    иначе смена TZ контейнера сдвигала бы уже сохранённые метки."""
    utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
    our_now = _now()
    # Разница должна быть в пределах пары секунд (время выполнения теста),
    # а не часов — иначе _now() всё ещё берёт локальное время сервера.
    assert abs((our_now - utc_now).total_seconds()) < 5


def test_add_or_extend_premium_rejects_zero_and_negative_days(uid):
    """F08: раньше отрицательные/нулевые дни тихо принимались и could
    укоротить премиум вместо явной ошибки."""
    user_id = uid()
    with pytest.raises(ValueError):
        add_or_extend_premium(user_id, 0)
    with pytest.raises(ValueError):
        add_or_extend_premium(user_id, -30)

    # премиум не должен был активироваться этими вызовами
    assert is_premium(user_id) is False


def test_add_or_extend_premium_accepts_positive_days(uid):
    user_id = uid()
    new_until = add_or_extend_premium(user_id, 5)
    assert new_until > _now()
    assert is_premium(user_id) is True


def test_is_premium_catches_only_sqlite_errors(monkeypatch, uid):
    """F09: подмена cursor непосредственно-несвязанной с БД ошибкой
    (например, опечаткой в самом модуле) должна падать наружу, а не тихо
    трактоваться как 'премиума нет'."""
    import bot.db.premium as premium_module

    class BrokenCursor:
        def execute(self, *args, **kwargs):
            raise TypeError("это не sqlite3.Error — программная ошибка")

    monkeypatch.setattr(premium_module, "cursor", BrokenCursor())

    with pytest.raises(TypeError):
        is_premium(uid())
