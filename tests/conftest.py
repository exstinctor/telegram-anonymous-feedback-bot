"""Общая настройка тестов: изолированная временная БД + переменные окружения.

Переменные окружения выставляются до любого импорта пакета bot — иначе
bot.core.config упадёт с RuntimeError (BOT_TOKEN не задан), а bot.db.connection
подключится не к тестовой, а к боевой директории.
"""
import os
import random
import tempfile

_TEST_DATA_DIR = tempfile.mkdtemp(prefix="anon_bot_test_")
os.environ["BOT_TOKEN"] = "123456:test-token"
os.environ["MAIN_ADMIN_ID"] = "777"
os.environ["DATA_DIR"] = _TEST_DATA_DIR
os.environ["MESSAGE_COOLDOWN_SECONDS"] = "3"

import pytest  # noqa: E402

from bot.db.schema import init_db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _init_database():
    init_db()
    yield


@pytest.fixture
def uid():
    """Генератор заведомо не пересекающихся ID пользователей на тест.

    БД одна на всю тестовую сессию (см. выше) — чтобы тесты не мешали друг
    другу через общие таблицы, у каждого теста свой диапазон ID вместо
    хрупких SAVEPOINT/ROLLBACK поверх кода, который сам делает conn.commit().
    """
    base = random.randint(10**9, 2 * 10**9)
    counter = {"n": 0}

    def _next() -> int:
        counter["n"] += 1
        return base + counter["n"]

    return _next
