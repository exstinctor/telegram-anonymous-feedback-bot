"""Тесты промокодов на уровне репозитория (bot/db/repository.py)."""
from bot.db import repository as db


def test_create_and_get_promo_code(uid):
    admin_id = uid()
    code = f"PROMO{admin_id}"

    assert db.get_promo_code(code) is None

    created = db.create_promo_code(code, days=7, max_uses=5, created_by=admin_id)
    assert created is True

    row = db.get_promo_code(code)
    assert row == (code, 7, 5, 0, admin_id)


def test_create_duplicate_code_fails_cleanly(uid):
    admin_id = uid()
    code = f"DUP{admin_id}"

    assert db.create_promo_code(code, days=3, max_uses=None, created_by=admin_id) is True
    # повторное создание того же кода не должно кидать sqlite3.IntegrityError наружу
    assert db.create_promo_code(code, days=99, max_uses=None, created_by=admin_id) is False

    # исходные параметры не были перезаписаны второй попыткой
    row = db.get_promo_code(code)
    assert row[1] == 3


def test_redeem_unlimited_code(uid):
    admin_id, user_a, user_b = uid(), uid(), uid()
    code = f"UNLIM{admin_id}"
    db.create_promo_code(code, days=5, max_uses=None, created_by=admin_id)

    ok, days, error = db.redeem_promo_code(code, user_a)
    assert (ok, days, error) == (True, 5, None)

    # второй пользователь тоже может погасить (лимита нет)
    ok2, days2, error2 = db.redeem_promo_code(code, user_b)
    assert (ok2, days2, error2) == (True, 5, None)

    row = db.get_promo_code(code)
    assert row[3] == 2  # used_count


def test_redeem_same_user_twice_rejected(uid):
    admin_id, user_id = uid(), uid()
    code = f"ONCE{admin_id}"
    db.create_promo_code(code, days=3, max_uses=None, created_by=admin_id)

    ok1, _, err1 = db.redeem_promo_code(code, user_id)
    assert ok1 is True and err1 is None

    ok2, days2, err2 = db.redeem_promo_code(code, user_id)
    assert ok2 is False
    assert days2 is None
    assert err2 == "already_used"

    # used_count не должен вырасти от повторной (отклонённой) попытки
    row = db.get_promo_code(code)
    assert row[3] == 1


def test_redeem_respects_max_uses(uid):
    admin_id = uid()
    users = [uid() for _ in range(3)]
    code = f"LIMIT{admin_id}"
    db.create_promo_code(code, days=2, max_uses=2, created_by=admin_id)

    ok1, _, _ = db.redeem_promo_code(code, users[0])
    ok2, _, _ = db.redeem_promo_code(code, users[1])
    ok3, days3, err3 = db.redeem_promo_code(code, users[2])

    assert ok1 is True and ok2 is True
    assert ok3 is False
    assert days3 is None
    assert err3 == "exhausted"


def test_redeem_nonexistent_code(uid):
    user_id = uid()
    ok, days, error = db.redeem_promo_code("NOSUCHCODE123", user_id)
    assert ok is False
    assert days is None
    assert error == "not_found"


def test_list_and_delete_promo_code(uid):
    admin_id = uid()
    code = f"DEL{admin_id}"
    db.create_promo_code(code, days=1, max_uses=10, created_by=admin_id)

    codes = [row[0] for row in db.list_promo_codes()]
    assert code in codes

    deleted = db.delete_promo_code(code)
    assert deleted == 1
    assert db.get_promo_code(code) is None

    # повторное удаление несуществующего кода не падает, просто 0 строк
    assert db.delete_promo_code(code) == 0


def test_delete_promo_code_also_clears_redemptions(uid):
    admin_id, user_id = uid(), uid()
    code = f"CLEAN{admin_id}"
    db.create_promo_code(code, days=1, max_uses=None, created_by=admin_id)
    db.redeem_promo_code(code, user_id)

    db.delete_promo_code(code)

    # код с тем же именем можно создать заново, и старая "уже погашено" запись
    # не должна мешать новому кругу использования
    db.create_promo_code(code, days=9, max_uses=None, created_by=admin_id)
    ok, days, error = db.redeem_promo_code(code, user_id)
    assert (ok, days, error) == (True, 9, None)
