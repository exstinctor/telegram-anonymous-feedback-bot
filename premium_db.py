import sqlite3
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

DB_PATH = "premium_users.db"

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS premium_users (
        user_id INTEGER PRIMARY KEY,
        premium_until TIMESTAMP
    );
    """
)
conn.commit()


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
        now = datetime.now()
        if premium_until > now:
            return True
        cursor.execute("DELETE FROM premium_users WHERE user_id = ?", (user_id,))
        conn.commit()
        return False
    except Exception as e:
        logger.error(f"PREMIUM_DB_CHECK_ERROR for user {user_id}: {e}")
        return False


def add_or_extend_premium(user_id: int, days: int) -> datetime:
    cursor.execute("SELECT premium_until FROM premium_users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    now = datetime.now()
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
