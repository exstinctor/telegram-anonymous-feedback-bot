"""Тесты транслитерации кириллицы в латиницу для кастомных ссылок и промокодов
(запрошено после того, как в реальном тесте бота код "ДВЕРЬ" отклонился, а
"DOOR" прошёл — теперь кириллица конвертируется автоматически)."""
from bot.core.states import PromoStates
from bot.db import repository as db
from bot.handlers.admin import _parse_and_create_promo
from bot.handlers.start import set_custom_link
from bot.services.utils import is_valid_custom_link, normalize_code, transliterate_to_latin
from tests.test_send_flow import FakeMessage, FakeUser, make_state


def test_transliterate_matches_screenshot_example():
    # ровно тот кейс, который пользователь словил вживую в боте
    assert transliterate_to_latin("ДВЕРЬ") == "DVER"
    assert is_valid_custom_link(transliterate_to_latin("ДВЕРЬ"))


def test_transliterate_mixed_and_punctuation():
    assert transliterate_to_latin("мой_код123") == "moy_kod123"
    assert transliterate_to_latin("привет мир!") == "privetmir"
    assert transliterate_to_latin("DOOR") == "DOOR"  # латиница не трогается


def test_normalize_code_passthrough_for_already_valid():
    code, was_translit = normalize_code("DOOR")
    assert (code, was_translit) == ("DOOR", False)


def test_normalize_code_transliterates_cyrillic():
    code, was_translit = normalize_code("ДВЕРЬ")
    assert code == "DVER"
    assert was_translit is True


async def test_promo_creation_with_cyrillic_input(uid):
    admin_id = uid()
    ok, text = _parse_and_create_promo(["ДВЕРЬ", "90", "5"], admin_id)
    assert ok is True
    assert "DVER" in text
    assert "преобразован из кириллицы" in text
    assert db.get_promo_code("DVER") is not None


async def test_custom_link_creation_with_cyrillic_input(uid):
    user_id = uid()
    db.create_user_link(user_id, f"code-{user_id}", "u", "U")

    state = make_state(user_id)
    from bot.core.states import CustomLinkStates
    await state.set_state(CustomLinkStates.waiting_for_code)

    msg = FakeMessage(FakeUser(user_id), text="ДВЕРЬ")
    await set_custom_link(msg, state)

    assert any("DVER" in a for a in msg.answers)
    assert any("преобразован" in a.lower() or "transliterat" in a.lower() for a in msg.answers)

    links = db.get_links(user_id)
    assert links[1] == "DVER"
