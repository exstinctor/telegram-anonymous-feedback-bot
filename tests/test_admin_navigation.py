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
