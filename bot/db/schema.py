"""Схема БД: создание таблиц, индексы и миграция для старых версий базы."""
from bot.db.connection import conn, cursor

_SCHEMA = '''
CREATE TABLE IF NOT EXISTS user_links (
    user_id INTEGER PRIMARY KEY,
    unique_code TEXT NOT NULL,
    original_code TEXT NOT NULL,
    custom_code TEXT,
    username TEXT,
    first_name TEXT,
    language TEXT NOT NULL DEFAULT 'ru'
);

CREATE TABLE IF NOT EXISTS messages (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id INTEGER NOT NULL,
    recipient_id INTEGER NOT NULL,
    sender_username TEXT,
    sender_first_name TEXT,
    message_text TEXT,
    photo_file_id TEXT,
    video_file_id TEXT,
    voice_file_id TEXT,
    audio_file_id TEXT,
    animation_file_id TEXT,
    sticker_file_id TEXT,
    document_file_id TEXT,
    document_file_name TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS blocked_users (
    user_id INTEGER NOT NULL,
    blocked_user_id INTEGER NOT NULL,
    blocked_username TEXT,
    blocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, blocked_user_id)
);

CREATE TABLE IF NOT EXISTS replies (
    reply_id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_message_id INTEGER NOT NULL,
    replier_id INTEGER NOT NULL,
    reply_text TEXT,
    reply_photo_file_id TEXT,
    reply_video_file_id TEXT,
    reply_voice_file_id TEXT,
    reply_audio_file_id TEXT,
    reply_animation_file_id TEXT,
    reply_sticker_file_id TEXT,
    reply_document_file_id TEXT,
    reply_document_file_name TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (original_message_id) REFERENCES messages(message_id)
);

CREATE TABLE IF NOT EXISTS global_ban_users (
    user_id INTEGER PRIMARY KEY,
    banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS promo_codes (
    code TEXT PRIMARY KEY,
    days INTEGER NOT NULL,
    max_uses INTEGER,
    used_count INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS promo_redemptions (
    code TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    redeemed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (code, user_id)
);

CREATE TABLE IF NOT EXISTS admins (
    user_id INTEGER PRIMARY KEY,
    added_by INTEGER NOT NULL,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
'''


def _ensure_columns(table: str, columns: dict) -> None:
    """Идемпотентно добавляет недостающие колонки в уже существующую таблицу.

    Нужно тем, кто обновляет бота поверх старой bot_database.db, созданной до
    появления новых типов вложений — CREATE TABLE IF NOT EXISTS их сам по себе
    не добавит.
    """
    cursor.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cursor.fetchall()}
    for name, col_type in columns.items():
        if name not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {col_type}")
    conn.commit()


def init_db() -> None:
    cursor.executescript(_SCHEMA)
    conn.commit()

    _ensure_columns("messages", {
        "voice_file_id": "TEXT",
        "audio_file_id": "TEXT",
        "animation_file_id": "TEXT",
        "sticker_file_id": "TEXT",
        "document_file_id": "TEXT",
        "document_file_name": "TEXT",
    })
    _ensure_columns("user_links", {
        "language": "TEXT NOT NULL DEFAULT 'ru'",
    })
    _ensure_columns("replies", {
        "reply_voice_file_id": "TEXT",
        "reply_audio_file_id": "TEXT",
        "reply_animation_file_id": "TEXT",
        "reply_sticker_file_id": "TEXT",
        "reply_document_file_id": "TEXT",
        "reply_document_file_name": "TEXT",
    })

    # Индексы под реальные паттерны запросов (см. repository.py):
    # - unique_code / custom_code проверяются на КАЖДЫЙ /start по реферальной
    #   ссылке (WHERE unique_code = ? OR custom_code = ?) — самый горячий путь
    #   в боте, без индекса это full scan таблицы пользователей.
    # - blocked_user_id ищется в admin_who_blocked_ ("кто заблокировал X") —
    #   составной PRIMARY KEY (user_id, blocked_user_id) им не помогает,
    #   т.к. blocked_user_id стоит вторым столбцом ключа.
    cursor.executescript('''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_user_links_unique_code ON user_links(unique_code);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_user_links_custom_code ON user_links(custom_code);
        CREATE INDEX IF NOT EXISTS idx_blocked_users_target ON blocked_users(blocked_user_id);
    ''')
    conn.commit()
