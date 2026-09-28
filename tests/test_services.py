"""Тесты доменной логики: bot/services/*."""
import time

from bot.services.antiflood import check_cooldown, mark_action
from bot.services.security import is_dangerous_document
from bot.services.utils import get_user_loginfo, is_valid_custom_link


def test_dangerous_document():
    assert is_dangerous_document("virus.exe") is True
    assert is_dangerous_document("setup.MSI") is True  # регистронезависимо
    assert is_dangerous_document("report.pdf") is False
    assert is_dangerous_document("archive.tar.gz") is False
    assert is_dangerous_document(None) is False
    assert is_dangerous_document("") is False


def test_cooldown(uid):
    user_id = uid()
    assert check_cooldown(user_id) == 0.0

    mark_action(user_id)
    remaining = check_cooldown(user_id)
    assert 0 < remaining <= 3.0

    time.sleep(3.1)
    assert check_cooldown(user_id) == 0.0


def test_get_user_loginfo():
    assert get_user_loginfo(1, "bob", "Bob") == "@bob (ID:1)"
    assert get_user_loginfo(1, None, "Bob") == "Bob (ID:1)"
    assert get_user_loginfo(1, None, None) == "(ID:1)"


def test_is_valid_custom_link():
    assert is_valid_custom_link("my_link") is True
    assert is_valid_custom_link("best-page123") is True
    assert is_valid_custom_link("ab") is False  # короче 3 символов
    assert is_valid_custom_link("a" * 21) is False  # длиннее 20
    assert is_valid_custom_link("bad link") is False  # пробел
    assert is_valid_custom_link("bad!link") is False  # спецсимвол
