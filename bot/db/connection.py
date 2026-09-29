"""Подключение к основной SQLite-базе бота (bot_database.db)."""
import os
import sqlite3

from bot.core.config import DATA_DIR

DB_PATH = os.path.join(DATA_DIR, "bot_database.db")

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

# LIKE в SQLite регистронезависим только для ASCII: "иван" не найдёт "Иван".
# Для поиска пользователей в админке нужна своя функция приведения к нижнему
# регистру, понимающая Юникод (см. repository.search_users).
conn.create_function(
    "PYLOWER", 1,
    lambda value: value.casefold() if isinstance(value, str) else "",
    deterministic=True,
)

# WAL вместо дефолтного rollback-journal: читатели не блокируются писателем,
# и наоборот, а каждый commit не требует полного fsync всей БД — для бота,
# который часто делает мелкие INSERT/UPDATE, это ощутимо быстрее и меньше
# нагружает диск, чем дефолтные настройки SQLite.
cursor.execute("PRAGMA journal_mode=WAL;")
cursor.execute("PRAGMA synchronous=NORMAL;")
cursor.execute("PRAGMA foreign_keys=ON;")
# Без busy_timeout параллельная запись (например, рассылка вперемешку с
# обычными сообщениями) может словить "database is locked" мгновенно вместо
# того, чтобы просто чуть подождать освобождения блокировки.
cursor.execute("PRAGMA busy_timeout=5000;")
conn.commit()
