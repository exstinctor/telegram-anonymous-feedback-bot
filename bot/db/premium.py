"""Премиум-система в отдельной БД (premium_users.db) — как и в исходном проекте."""
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from bot.core.config import DATA_DIR, logger

DB_PATH = os.path.join(DATA_DIR, "premium_users.db")

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

cursor.execute("PRAGMA journal_mode=WAL;")
cursor.execute("PRAGMA synchronous=NORMAL;")
cursor.execute("PRAGMA busy_timeout=5000;")
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS premium_users (
        user_id INTEGER PRIMARY KEY,
        premium_until TIMESTAMP
    );
    """
)
conn.commit()


def _now() -> datetime:
    """"Наивный" datetime, но всегда в UTC — не в локальном времени сервера.

    Раньше здесь был datetime.now() (локальное время): при смене таймзоны
    контейнера/сервера или переходе на летнее/зимнее время уже сохранённые
    метки premium_until сдвигались бы относительно новых. UTC не имеет
    перевода времени и не зависит от таймзоны хоста — единственная причина
    хранить "наивный" (без tzinfo), а не aware datetime: формат хранения в
    БД (TEXT "%Y-%m-%d %H:%M:%S") не хранит tzinfo, а сравнивать naive с
    aware в Python нельзя, будет TypeError.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def is_premium(user_id: int) -> bool:
    try:
        cursor.execute("SELECT premium_until FROM premium_users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            return False
        premium_until_str = row[0]
        if not premium_until_str:
            cursor.execute("DELETE FROM premium_users WHERE user_id = ?", (user_id,))
            conn.commit()
            return False
        premium_until = datetime.strptime(premium_until_str, "%Y-%m-%d %H:%M:%S")
        if premium_until > _now():
            return True
        cursor.execute("DELETE FROM premium_users WHERE user_id = ?", (user_id,))
        conn.commit()
        return False
    except sqlite3.Error as e:
        # Раньше здесь было "except Exception" — любая опечатка в этом же
        # модуле тихо трактовалась бы как "премиума нет", без видимой ошибки
        # (F09 из ревью). Ловим именно ошибки БД, остальное пусть падает.
        logger.error(f"PREMIUM_DB_CHECK_ERROR user={user_id}: {e}", exc_info=True)
        return False


def add_or_extend_premium(user_id: int, days: int) -> datetime:
    if days <= 0:
        # Раньше отрицательное число дней тихо УКОРАЧИВАЛО премиум вместо
        # выдачи (F08 из ревью) — например, опечатка "-30" в админке.
        raise ValueError(f"days должно быть положительным, получено {days}")

    cursor.execute("SELECT premium_until FROM premium_users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    now = _now()
    if row and row[0]:
        try:
            current_until = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            current_until = now
    else:
        current_until = now
    if current_until < now:
        current_until = now
    new_until = current_until + timedelta(days=days)
    cursor.execute(
        """
        INSERT INTO premium_users (user_id, premium_until)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET premium_until=excluded.premium_until
        """,
        (user_id, new_until.strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit()
    return new_until


def remove_premium(user_id: int) -> None:
    cursor.execute("DELETE FROM premium_users WHERE user_id = ?", (user_id,))
    conn.commit()


def list_premium_users():
    cursor.execute("SELECT user_id, premium_until FROM premium_users ORDER BY premium_until DESC")
    return cursor.fetchall()


def count_all_premium_records() -> int:
    cursor.execute("SELECT COUNT(*) FROM premium_users")
    return cursor.fetchone()[0]


def get_premium_page(offset: int, limit: int):
    cursor.execute(
        "SELECT user_id, premium_until FROM premium_users ORDER BY premium_until DESC LIMIT ? OFFSET ?",
        (limit, offset)
    )
    return cursor.fetchall()


def get_user_premium_until(user_id: int):
    """Сырое значение premium_until для одного пользователя, или None.

    Отдельно от is_premium(): та возвращает bool и попутно чистит просроченные
    записи, здесь — просто чтение для отображения в карточке пользователя,
    без побочных эффектов и без сканирования всей таблицы (см. F14 в ревью —
    раньше карточка админа проходила list_premium_users() целиком в цикле)."""
    cursor.execute("SELECT premium_until FROM premium_users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else None


def count_active_premium() -> int:
    cursor.execute(
        "SELECT COUNT(*) FROM premium_users WHERE premium_until > ?",
        (_now().strftime("%Y-%m-%d %H:%M:%S"),)
    )
    return cursor.fetchone()[0]


def get_active_premium_user_ids():
    cursor.execute(
        "SELECT user_id FROM premium_users WHERE premium_until > ?",
        (_now().strftime("%Y-%m-%d %H:%M:%S"),)
    )
    return [row[0] for row in cursor.fetchall()]
