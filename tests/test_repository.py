"""Тесты слоя bot/db/repository.py — весь SQL-доступ бота."""
from bot.db import repository as db


def test_links_lifecycle(uid):
    user_id = uid()
    assert db.get_link_codes(user_id) is None

    db.create_user_link(user_id, "code123", "alice", "Alice")
    assert db.get_link_codes(user_id) == ("code123", "code123")

    resolved = db.resolve_recipient("code123")
    assert resolved == (user_id, "alice", "Alice")

    assert db.is_code_taken("code123") is True
    assert db.is_code_taken("free-code") is False

    db.set_custom_code(user_id, "my-custom")
    assert db.get_links(user_id) == ("code123", "my-custom")
    assert db.resolve_recipient("my-custom")[0] == user_id

    db.clear_custom_code(user_id)
    assert db.get_links(user_id)[1] is None


def test_users_pagination(uid):
    ids = [uid() for _ in range(25)]
    for i, user_id in enumerate(ids):
        db.create_user_link(user_id, f"page-code-{user_id}", f"u{i}", f"U{i}")

    total_before = db.count_users()
    assert total_before >= 25

    page = db.get_users_page(offset=0, limit=10)
    assert len(page) == 10


def test_message_and_reply_roundtrip(uid):
    sender_id, recipient_id = uid(), uid()

    message_id = db.insert_message(
        sender_id, recipient_id, "sender_uname", "Sender", "hello there",
        voice_id="VOICE1"
    )
    assert db.get_message_sender(message_id) == sender_id
    assert db.get_message_recipient(message_id) == recipient_id

    sender_info = db.get_message_sender_info(message_id)
    assert sender_info == ("sender_uname", "Sender", sender_id, recipient_id)

    go_back = db.get_message_for_go_back(message_id)
    assert go_back[0] == "hello there"
    assert go_back[3] == "VOICE1"  # voice_file_id
    assert go_back[10] == recipient_id

    block_info = db.get_message_for_block(message_id)
    assert block_info == (sender_id, "sender_uname", "Sender", recipient_id)

    db.insert_reply(message_id, recipient_id, "hi back", sticker="STICK1")
    # insert_reply не возвращает id — само отсутствие исключения и есть проверка;
    # содержимое реплаев в репозитории наружу не читается (только форвардится).


def test_message_recipient_none_for_missing_id(uid):
    assert db.get_message_sender(999_999_999) is None
    assert db.get_message_recipient(999_999_999) is None
    assert db.get_message_sender_info(999_999_999) is None


def test_blocks(uid):
    owner_id, target_id = uid(), uid()

    assert db.is_blocked_by(owner_id, target_id) is False
    db.add_block(owner_id, target_id, "target_uname")
    assert db.is_blocked_by(owner_id, target_id) is True

    assert db.get_blockers_of(target_id) == [(owner_id, "target_uname")]

    blocklist = db.get_blocklist(owner_id)
    assert len(blocklist) == 1
    assert blocklist[0][0] == "target_uname"

    removed = db.remove_block(owner_id, target_id)
    assert removed == 1
    assert db.is_blocked_by(owner_id, target_id) is False

    # повторное удаление несуществующей блокировки не должно падать
    assert db.remove_block(owner_id, target_id) == 0


def test_remove_block_by_username(uid):
    owner_id, target_id = uid(), uid()
    db.add_block(owner_id, target_id, "some_user")

    assert db.remove_block_by_username(owner_id, "wrong_name") == 0
    assert db.remove_block_by_username(owner_id, "some_user") == 1
    assert db.is_blocked_by(owner_id, target_id) is False


def test_global_ban(uid):
    target_id = uid()
    assert db.is_globally_banned(target_id) is False

    db.global_ban(target_id)
    assert db.is_globally_banned(target_id) is True

    # повторный бан того же пользователя не должен падать (INSERT OR IGNORE)
    db.global_ban(target_id)

    db.global_unban(target_id)
    assert db.is_globally_banned(target_id) is False


def test_global_ban_list_pagination(uid):
    ids = [uid() for _ in range(15)]
    for target_id in ids:
        db.global_ban(target_id)

    total = db.count_global_ban_list()
    assert total >= 15

    page0 = db.get_global_ban_list_page(offset=0, limit=10)
    assert len(page0) == 10
