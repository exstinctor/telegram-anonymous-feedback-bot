"""Весь доступ к основной БД бота одним слоем — остальной код SQL не пишет.

Здесь же можно централизованно добавить кэш или сменить БД, не трогая
хендлеры. Функции сгруппированы по доменам: LINKS / MESSAGES / BLOCKS / PROMO CODES.
"""
import sqlite3

from bot.db.connection import conn, cursor

# ---------------------------------------------------------------------------
# LINKS — user_links
# ---------------------------------------------------------------------------


def get_link_codes(user_id: int):
    """(unique_code, original_code) или None, если пользователь не встречался."""
    cursor.execute('SELECT unique_code, original_code FROM user_links WHERE user_id = ?', (user_id,))
    return cursor.fetchone()


def create_user_link(user_id: int, code: str, username, first_name) -> None:
    cursor.execute(
        '''
        INSERT INTO user_links (user_id, unique_code, original_code, username, first_name)
        VALUES (?, ?, ?, ?, ?)
        ''',
        (user_id, code, code, username, first_name)
    )
    conn.commit()


def resolve_recipient(code: str):
    """(user_id, username, first_name) владельца ссылки по unique_code/custom_code."""
    cursor.execute(
        'SELECT user_id, username, first_name FROM user_links WHERE unique_code = ? OR custom_code = ?',
        (code, code)
    )
    return cursor.fetchone()


def get_links(user_id: int):
    """(unique_code, custom_code) для пользователя."""
    cursor.execute('SELECT unique_code, custom_code FROM user_links WHERE user_id = ?', (user_id,))
    return cursor.fetchone()


def is_code_taken(code: str) -> bool:
    cursor.execute('SELECT 1 FROM user_links WHERE custom_code = ? OR unique_code = ?', (code, code))
    return cursor.fetchone() is not None


def set_custom_code(user_id: int, code: str) -> None:
    cursor.execute('UPDATE user_links SET custom_code = ? WHERE user_id = ?', (code, user_id))
    conn.commit()


def clear_custom_code(user_id: int) -> None:
    cursor.execute('UPDATE user_links SET custom_code = NULL WHERE user_id = ?', (user_id,))
    conn.commit()


def get_all_user_ids():
    """Все user_id для рассылки — без username/first_name, они здесь не нужны."""
    cursor.execute('SELECT user_id FROM user_links')
    return [row[0] for row in cursor.fetchall()]


def get_global_ban_user_ids():
    """Множество забаненных user_id — для исключения из рассылки и т.п."""
    cursor.execute('SELECT user_id FROM global_ban_users')
    return {row[0] for row in cursor.fetchall()}


def get_users_page(offset: int, limit: int):
    cursor.execute(
        'SELECT user_id, username, first_name FROM user_links ORDER BY user_id LIMIT ? OFFSET ?',
        (limit, offset)
    )
    return cursor.fetchall()


def count_users() -> int:
    cursor.execute('SELECT COUNT(*) FROM user_links')
    return cursor.fetchone()[0]


def get_user_link_row(user_id: int):
    """(username, first_name, custom_code, unique_code) для карточки пользователя в админке."""
    cursor.execute(
        'SELECT username, first_name, custom_code, unique_code FROM user_links WHERE user_id = ?',
        (user_id,)
    )
    return cursor.fetchone()


SEARCH_QUERY_MAX_LEN = 64


def _search_params(query: str):
    """Нормализует запрос: без пробелов по краям и ведущего '@', в нижнем регистре.

    Возвращает None для пустого запроса. Спецсимволы LIKE (%, _, \\) экранируются,
    чтобы админ, ищущий "a_b", не получил в выдаче "aXb".
    """
    q = (query or "").strip()[:SEARCH_QUERY_MAX_LEN].lstrip("@").strip().casefold()
    if not q:
        return None
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    # user_id — 64-битный INTEGER; более длинные числа не могут быть ID, а
    # передача их в SQLite падает с OverflowError.
    uid = int(q) if q.isdigit() and len(q) <= 18 else None
    return {"q": q, "uid": uid, "like": f"%{escaped}%", "prefix": f"{escaped}%"}


_SEARCH_WHERE = r'''
    user_id = :uid
    OR PYLOWER(username) LIKE :like ESCAPE '\'
    OR PYLOWER(first_name) LIKE :like ESCAPE '\'
'''


def search_users(query: str, limit: int = 10):
    """Поиск по Telegram ID (точное совпадение), @username и имени (вхождение).

    Возвращает [(user_id, username, first_name)], сначала самые точные
    совпадения: ID, затем username целиком, затем начало username/имени.
    """
    params = _search_params(query)
    if params is None:
        return []
    cursor.execute(
        f'''
        SELECT user_id, username, first_name FROM user_links
        WHERE {_SEARCH_WHERE}
        ORDER BY CASE
            WHEN user_id = :uid THEN 0
            WHEN PYLOWER(username) = :q THEN 1
            WHEN PYLOWER(username) LIKE :prefix ESCAPE '\\' THEN 2
            WHEN PYLOWER(first_name) LIKE :prefix ESCAPE '\\' THEN 3
            ELSE 4
        END, user_id
        LIMIT :limit
        ''',
        {**params, "limit": limit},
    )
    return cursor.fetchall()


def count_users_matching(query: str) -> int:
    """Сколько всего пользователей подходит под запрос (для «показаны первые N из M»)."""
    params = _search_params(query)
    if params is None:
        return 0
    cursor.execute(f"SELECT COUNT(*) FROM user_links WHERE {_SEARCH_WHERE}", params)
    return cursor.fetchone()[0]


# ---------------------------------------------------------------------------
# MESSAGES — messages, replies
# ---------------------------------------------------------------------------


def insert_message(sender_id, recipient_id, sender_username, sender_first_name, message_text,
                    photo_id=None, video_id=None, voice_id=None, audio_id=None,
                    animation_id=None, sticker_id=None, document_id=None, document_name=None) -> int:
    cursor.execute(
        '''
        INSERT INTO messages
        (sender_id, recipient_id, sender_username, sender_first_name, message_text,
         photo_file_id, video_file_id, voice_file_id, audio_file_id,
         animation_file_id, sticker_file_id, document_file_id, document_file_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            sender_id, recipient_id, sender_username, sender_first_name, message_text,
            photo_id, video_id, voice_id, audio_id, animation_id, sticker_id, document_id, document_name
        )
    )
    conn.commit()
    return cursor.lastrowid


def get_message_sender(message_id: int):
    """sender_id сообщения или None."""
    cursor.execute('SELECT sender_id FROM messages WHERE message_id = ?', (message_id,))
    row = cursor.fetchone()
    return row[0] if row else None


def get_message_recipient(message_id: int):
    """recipient_id сообщения или None (используется для проверки прав на ответ)."""
    cursor.execute('SELECT recipient_id FROM messages WHERE message_id = ?', (message_id,))
    row = cursor.fetchone()
    return row[0] if row else None


def get_message_sender_info(message_id: int):
    """(sender_username, sender_first_name, sender_id, recipient_id) или None."""
    cursor.execute(
        'SELECT sender_username, sender_first_name, sender_id, recipient_id FROM messages WHERE message_id = ?',
        (message_id,)
    )
    return cursor.fetchone()


def get_message_for_go_back(message_id: int):
    cursor.execute(
        '''SELECT message_text, photo_file_id, video_file_id, voice_file_id, audio_file_id,
                  animation_file_id, sticker_file_id, document_file_id,
                  sender_username, sender_first_name, recipient_id
           FROM messages WHERE message_id = ?''',
        (message_id,)
    )
    return cursor.fetchone()


def get_message_for_block(message_id: int):
    """(sender_id, sender_username, sender_first_name, recipient_id) или None."""
    cursor.execute(
        'SELECT sender_id, sender_username, sender_first_name, recipient_id FROM messages WHERE message_id = ?',
        (message_id,)
    )
    return cursor.fetchone()


def insert_reply(original_message_id, replier_id, reply_text,
                  photo=None, video=None, voice=None, audio=None,
                  animation=None, sticker=None, document=None, document_name=None) -> None:
    cursor.execute(
        '''
        INSERT INTO replies
        (original_message_id, replier_id, reply_text, reply_photo_file_id, reply_video_file_id,
         reply_voice_file_id, reply_audio_file_id, reply_animation_file_id,
         reply_sticker_file_id, reply_document_file_id, reply_document_file_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            original_message_id, replier_id, reply_text, photo, video,
            voice, audio, animation, sticker, document, document_name
        )
    )
    conn.commit()


# ---------------------------------------------------------------------------
# BLOCKS — blocked_users, global_ban_users
# ---------------------------------------------------------------------------


def is_blocked_by(owner_id: int, target_id: int) -> bool:
    """True, если owner_id заблокировал target_id."""
    cursor.execute(
        'SELECT 1 FROM blocked_users WHERE user_id = ? AND blocked_user_id = ?',
        (owner_id, target_id)
    )
    return cursor.fetchone() is not None


def add_block(owner_id: int, target_id: int, target_username: str) -> None:
    cursor.execute(
        'INSERT INTO blocked_users (user_id, blocked_user_id, blocked_username) VALUES (?, ?, ?)',
        (owner_id, target_id, target_username)
    )
    conn.commit()


def remove_block(owner_id: int, target_id: int) -> int:
    """Возвращает число удалённых строк (0, если блокировки не было)."""
    cursor.execute('DELETE FROM blocked_users WHERE user_id = ? AND blocked_user_id = ?', (owner_id, target_id))
    conn.commit()
    return cursor.rowcount


def remove_block_by_username(owner_id: int, username: str) -> int:
    cursor.execute(
        'DELETE FROM blocked_users WHERE user_id = ? AND blocked_username = ?',
        (owner_id, username)
    )
    conn.commit()
    return cursor.rowcount


def get_blocklist(owner_id: int):
    cursor.execute(
        'SELECT blocked_username, blocked_at FROM blocked_users WHERE user_id = ? ORDER BY blocked_at DESC',
        (owner_id,)
    )
    return cursor.fetchall()


def get_blockers_of(target_id: int):
    """Кто заблокировал target_id: список (user_id, blocked_username)."""
    cursor.execute(
        'SELECT user_id, blocked_username FROM blocked_users WHERE blocked_user_id = ?',
        (target_id,)
    )
    return cursor.fetchall()


def is_globally_banned(user_id: int) -> bool:
    cursor.execute('SELECT 1 FROM global_ban_users WHERE user_id = ?', (user_id,))
    return cursor.fetchone() is not None


def global_ban(user_id: int) -> None:
    cursor.execute('INSERT OR IGNORE INTO global_ban_users (user_id) VALUES (?)', (user_id,))
    conn.commit()


def global_unban(user_id: int) -> None:
    cursor.execute('DELETE FROM global_ban_users WHERE user_id = ?', (user_id,))
    conn.commit()


def get_global_ban_list_page(offset: int, limit: int):
    """(user_id, username, first_name) для страницы глобально забаненных."""
    cursor.execute(
        '''
        SELECT g.user_id, ul.username, ul.first_name
        FROM global_ban_users g
        LEFT JOIN user_links ul ON ul.user_id = g.user_id
        ORDER BY g.user_id
        LIMIT ? OFFSET ?
        ''',
        (limit, offset)
    )
    return cursor.fetchall()


def count_global_ban_list() -> int:
    cursor.execute('SELECT COUNT(*) FROM global_ban_users')
    return cursor.fetchone()[0]


# ---------------------------------------------------------------------------
# PROMO CODES — promo_codes, promo_redemptions
# ---------------------------------------------------------------------------


def create_promo_code(code: str, days: int, max_uses, created_by: int) -> bool:
    """Создаёт промокод. Возвращает False, если такой код уже существует
    (вместо необработанного sqlite3.IntegrityError наружу)."""
    try:
        cursor.execute(
            'INSERT INTO promo_codes (code, days, max_uses, created_by) VALUES (?, ?, ?, ?)',
            (code, days, max_uses, created_by)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def get_promo_code(code: str):
    """(code, days, max_uses, used_count, created_by) или None."""
    cursor.execute(
        'SELECT code, days, max_uses, used_count, created_by FROM promo_codes WHERE code = ?',
        (code,)
    )
    return cursor.fetchone()


def list_promo_codes():
    cursor.execute(
        'SELECT code, days, max_uses, used_count FROM promo_codes ORDER BY created_at DESC'
    )
    return cursor.fetchall()


def delete_promo_code(code: str) -> int:
    cursor.execute('DELETE FROM promo_codes WHERE code = ?', (code,))
    deleted = cursor.rowcount  # rowcount отражает ПОСЛЕДНИЙ execute — сохраняем
    # его до второго DELETE, иначе для кода без единого погашения (rowcount=0
    # у promo_redemptions) метод всегда возвращал бы 0, даже если код удалился.
    cursor.execute('DELETE FROM promo_redemptions WHERE code = ?', (code,))
    conn.commit()
    return deleted


def redeem_promo_code(code: str, user_id: int):
    """Пытается погасить промокод для пользователя.

    Возвращает (ok, days, error), где error — одна из строк:
    "not_found" / "already_used" / "exhausted" (или None при успехе).
    Между чтением и записью здесь нет await, поэтому две "одновременные"
    попытки одного и того же пользователя не могут провалиться в гонку —
    вся операция выполняется одним куском синхронного кода, не прерываемым
    event loop'ом (см. README, раздел про конкурентность).
    """
    row = get_promo_code(code)
    if not row:
        return False, None, "not_found"
    _code, days, max_uses, used_count, _created_by = row

    cursor.execute('SELECT 1 FROM promo_redemptions WHERE code = ? AND user_id = ?', (code, user_id))
    if cursor.fetchone():
        return False, None, "already_used"

    if max_uses is not None and used_count >= max_uses:
        return False, None, "exhausted"

    cursor.execute('UPDATE promo_codes SET used_count = used_count + 1 WHERE code = ?', (code,))
    cursor.execute('INSERT INTO promo_redemptions (code, user_id) VALUES (?, ?)', (code, user_id))
    conn.commit()
    return True, days, None


# ---------------------------------------------------------------------------
# STATS — для экрана «📊 Статистика» в админке
# ---------------------------------------------------------------------------


def count_messages() -> int:
    cursor.execute('SELECT COUNT(*) FROM messages')
    return cursor.fetchone()[0]


def count_replies() -> int:
    cursor.execute('SELECT COUNT(*) FROM replies')
    return cursor.fetchone()[0]


def count_blocked_pairs() -> int:
    cursor.execute('SELECT COUNT(*) FROM blocked_users')
    return cursor.fetchone()[0]


def count_promo_codes() -> int:
    cursor.execute('SELECT COUNT(*) FROM promo_codes')
    return cursor.fetchone()[0]


def count_promo_redemptions() -> int:
    cursor.execute('SELECT COUNT(*) FROM promo_redemptions')
    return cursor.fetchone()[0]


# ---------------------------------------------------------------------------
# ADMINS — под-админы, назначенные главным администратором (MAIN_ADMIN_ID
# остаётся суперадмином и не хранится в этой таблице — он задан в .env)
# ---------------------------------------------------------------------------


def is_sub_admin(user_id: int) -> bool:
    cursor.execute('SELECT 1 FROM admins WHERE user_id = ?', (user_id,))
    return cursor.fetchone() is not None


def add_admin(user_id: int, added_by: int) -> None:
    cursor.execute('INSERT OR IGNORE INTO admins (user_id, added_by) VALUES (?, ?)', (user_id, added_by))
    conn.commit()


def remove_admin(user_id: int) -> int:
    cursor.execute('DELETE FROM admins WHERE user_id = ?', (user_id,))
    conn.commit()
    return cursor.rowcount


def list_admins():
    """(user_id, added_by, added_at) для всех под-админов."""
    cursor.execute('SELECT user_id, added_by, added_at FROM admins ORDER BY added_at')
    return cursor.fetchall()
