import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
    ConversationHandler
)

import uuid
import sqlite3
from datetime import datetime
import re

from premium_db import is_premium, add_or_extend_premium, remove_premium, list_premium_users

MAIN_ADMIN_ID = 0

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

SET_CUSTOM_LINK = 1
SET_GIVE_PREMIUM = 2
SET_REMOVE_PREMIUM = 3
SET_ADMIN_SELECT_USER_FOR_PREMIUM_DAYS = 4

conn = sqlite3.connect('bot_database.db', check_same_thread=False)
cursor = conn.cursor()

cursor.executescript('''
CREATE TABLE IF NOT EXISTS user_links (
    user_id INTEGER PRIMARY KEY,
    unique_code TEXT NOT NULL,
    original_code TEXT NOT NULL,
    custom_code TEXT,
    username TEXT,
    first_name TEXT
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (original_message_id) REFERENCES messages(message_id)
);

CREATE TABLE IF NOT EXISTS global_ban_users (
    user_id INTEGER PRIMARY KEY,
    banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
''')
conn.commit()


def get_user_loginfo(user_id, username=None, first_name=None):
    if username:
        return f"@{username} (ID:{user_id})"
    if first_name:
        return f"{first_name} (ID:{user_id})"
    return f"(ID:{user_id})"


def is_valid_custom_link(link):
    return re.match(r'^[a-zA-Z0-9_-]{3,20}$', link)


def is_globally_banned(user_id: int) -> bool:
    cursor.execute('SELECT 1 FROM global_ban_users WHERE user_id = ?', (user_id,))
    return cursor.fetchone() is not None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    username = user.username
    first_name = user.first_name

    if is_globally_banned(user_id):
        await update.message.reply_text("🚫 Вы заблокированы в этом боте.")
        return

    cursor.execute('SELECT unique_code, original_code FROM user_links WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()

    if not result:
        original_code = str(uuid.uuid4())[:8]
        cursor.execute(
            '''
            INSERT INTO user_links (user_id, unique_code, original_code, username, first_name)
            VALUES (?, ?, ?, ?, ?)
            ''',
            (user_id, original_code, original_code, username, first_name)
        )
        conn.commit()
    else:
        unique_code, original_code = result

    args = context.args
    if args:
        unique_code = args[0]
        cursor.execute(
            'SELECT user_id, username, first_name FROM user_links WHERE unique_code = ? OR custom_code = ?',
            (unique_code, unique_code)
        )
        result = cursor.fetchone()
        if result:
            recipient_id, rec_username, rec_first_name = result

            if is_globally_banned(recipient_id):
                await update.message.reply_text("🚫 Этот пользователь заблокирован в боте.")
                return

            cursor.execute(
                'SELECT 1 FROM blocked_users WHERE user_id = ? AND blocked_user_id = ?',
                (recipient_id, user_id)
            )
            if cursor.fetchone():
                await update.message.reply_text("❌ Вы заблокированы у этого пользователя")
                return

            context.user_data['recipient_id'] = recipient_id
            await update.message.reply_text(
                "🚀 Здесь можно отправить анонимное сообщение человеку, который опубликовал эту ссылку \n\n"
                "✍️ Напишите сюда всё, что хотите ему передать, и через несколько секунд он получит ваше сообщение, "
                "но не будет знать от кого \n\n"
                "Отправить можно 💬 текст, 📷 фото + текст или 🎥 видео + текст"
            )
            return

    cursor.execute('SELECT unique_code, custom_code FROM user_links WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    unique_code = result[0]
    custom_code = result[1] if result else None

    bot_username = context.bot.username
    link = f"https://t.me/{bot_username}?start={unique_code}"
    custom_link = f"https://t.me/{bot_username}?start={custom_code}" if custom_code else None

    if custom_code:
        keyboard = [
            [InlineKeyboardButton("✏️ Создать свою ссылку", callback_data="create_custom_link")],
            [InlineKeyboardButton("🔄 Вернуть оригинальную ссылку", callback_data="reset_to_original")]
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("✏️ Создать свою ссылку", callback_data="create_custom_link")]
        ]

    if user_id == MAIN_ADMIN_ID:
        keyboard.append([InlineKeyboardButton("⚙️ Админ панель", callback_data="admin_users_list")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    message_text = f"👉 Ваша персональная ссылка:\n{link}"
    if custom_link:
        message_text += f"\n\n👉 Ваша пользовательская ссылка:\n{custom_link}"
    message_text += "\n\nРазместите эту ссылку в описании своего профиля, чтобы вам могли написать "
    await update.message.reply_text(message_text, reply_markup=reply_markup)


async def create_custom_link_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "✏️ Введите желаемое название для вашей ссылки (только латинские буквы, цифры, _ и -, от 3 до 20 символов):\n\n"
        "Пример: my_link или best_page123"
    )
    return SET_CUSTOM_LINK


async def set_custom_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if is_globally_banned(user.id):
        await update.message.reply_text("🚫 Вы заблокированы в этом боте.")
        return ConversationHandler.END

    user_id = user.id
    custom_code = update.message.text.strip()

    if not is_valid_custom_link(custom_code):
        await update.message.reply_text(
            "❌ Некорректный формат ссылки. Используйте только латинские буквы, цифры, _ и -, от 3 до 20 символов.\n\n"
            "Попробуйте еще раз или отправьте /cancel для отмены."
        )
        return SET_CUSTOM_LINK

    cursor.execute(
        'SELECT 1 FROM user_links WHERE custom_code = ? OR unique_code = ?',
        (custom_code, custom_code)
    )
    if cursor.fetchone():
        await update.message.reply_text(
            "❌ Эта ссылка уже занята. Пожалуйста, выберите другую.\n\n"
            "Попробуйте еще раз или отправьте /cancel для отмены."
        )
        return SET_CUSTOM_LINK

    cursor.execute(
        '''
        UPDATE user_links
        SET custom_code = ?
        WHERE user_id = ?
        ''',
        (custom_code, user_id)
    )
    conn.commit()

    bot_username = context.bot.username
    custom_link = f"https://t.me/{bot_username}?start={custom_code}"
    await update.message.reply_text(
        f"✅ Ваша пользовательская ссылка создана:\n{custom_link}\n\n"
        "Теперь вы можете использовать как эту ссылку, так и оригинальную."
    )
    return ConversationHandler.END


async def reset_to_original(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if is_globally_banned(user_id):
        await query.edit_message_text("🚫 Вы заблокированы в этом боте.")
        return

    cursor.execute(
        '''
        UPDATE user_links
        SET custom_code = NULL
        WHERE user_id = ?
        ''',
        (user_id,)
    )
    conn.commit()

    cursor.execute('SELECT unique_code FROM user_links WHERE user_id = ?', (user_id,))
    unique_code = cursor.fetchone()[0]

    bot_username = context.bot.username
    link = f"https://t.me/{bot_username}?start={unique_code}"

    await query.edit_message_text(
        f"🔄 Вы вернули оригинальную ссылку:\n{link}\n\n"
        "Разместите её в соцсетях, чтобы получать анонимные сообщения",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("✏️ Создать свою ссылку", callback_data="create_custom_link")]]
        )
    )


async def cancel_custom_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Создание пользовательской ссылки отменено.")
    return ConversationHandler.END


async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user.id != MAIN_ADMIN_ID:
        await update.message.reply_text("❌ У вас нет доступа к админ-меню.")
        return

    keyboard = [
        [InlineKeyboardButton("👥 Пользователи", callback_data="admin_users_list")],
        [InlineKeyboardButton("📋 Премиум-таблица", callback_data="admin_list_premium_old")]
    ]
    await update.message.reply_text("Админ-меню:", reply_markup=InlineKeyboardMarkup(keyboard))


def get_all_users():
    cursor.execute(
        '''
        SELECT user_id, username, first_name FROM user_links
        ORDER BY user_id
        '''
    )
    return cursor.fetchall()


async def admin_show_users_list(query, context: ContextTypes.DEFAULT_TYPE):
    users = get_all_users()
    if not users:
        await query.edit_message_text("В боте пока нет пользователей.")
        return

    keyboard = []
    for user_id, username, first_name in users:
        display = f"{first_name or ''} (@{username})" if username else f"{first_name or ''} (ID:{user_id})"
        keyboard.append(
            [InlineKeyboardButton(display, callback_data=f"admin_user_{user_id}")]
        )

    await query.edit_message_text("Выберите пользователя:", reply_markup=InlineKeyboardMarkup(keyboard))


def get_user_full_info(user_id: int, bot_username: str):
    cursor.execute('SELECT username, first_name, custom_code, unique_code FROM user_links WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if not row:
        return None
    username, first_name, custom_code, unique_code = row

    if username:
        direct_link = f"https://t.me/{username}"
    else:
        direct_link = f"tg://user?id={user_id}"

    premium_rows = list_premium_users()
    premium_until = "нет"
    for uid, until_str in premium_rows:
        if uid == user_id and until_str:
            try:
                dt = datetime.strptime(until_str, "%Y-%m-%d %H:%M:%S")
                premium_until = dt.strftime("%d.%m.%Y %H:%M")
            except Exception:
                premium_until = until_str
            break

    unique_link = f"https://t.me/{bot_username}?start={unique_code}"
    custom_link = f"https://t.me/{bot_username}?start={custom_code}" if custom_code else "нет"

    return {
        "user_id": user_id,
        "username": username,
        "first_name": first_name,
        "direct_link": direct_link,
        "premium_until": premium_until,
        "unique_link": unique_link,
        "custom_link": custom_link,
    }


async def admin_show_user_panel(query, context: ContextTypes.DEFAULT_TYPE, target_id: int):
    info = get_user_full_info(target_id, context.bot.username)
    if not info:
        await query.edit_message_text("Пользователь не найден.")
        return

    text = (
        f"Пользователь:\n"
        f"ID: {info['user_id']}\n"
        f"Имя: {info['first_name']}\n"
        f"Username: @{info['username'] if info['username'] else 'нет'}\n"
        f"Прямая ссылка: {info['direct_link']}\n\n"
        f"Персональная ссылка: {info['unique_link']}\n"
        f"Кастомная ссылка: {info['custom_link']}\n\n"
        f"Премиум до: {info['premium_until']}\n"
    )

    g_banned = is_globally_banned(target_id)

    keyboard = [
        [
            InlineKeyboardButton("Глобально заблокировать" if not g_banned else "Снять глобальный бан",
                                 callback_data=f"admin_globalban_{target_id}")
        ],
        [
            InlineKeyboardButton("Добавить премиум", callback_data=f"admin_premium_add_{target_id}"),
            InlineKeyboardButton("Убрать премиум", callback_data=f"admin_premium_remove_{target_id}")
        ],
        [
            InlineKeyboardButton("Кто его блокировал", callback_data=f"admin_who_blocked_{target_id}")
        ],
        [
            InlineKeyboardButton("Назад к списку", callback_data="admin_users_list")
        ]
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def admin_give_premium_days_menu(query, target_id: int):
    keyboard = [
        [
            InlineKeyboardButton("+1 день", callback_data=f"admin_premium_add_days_{target_id}_1"),
            InlineKeyboardButton("+3 дня", callback_data=f"admin_premium_add_days_{target_id}_3")
        ],
        [
            InlineKeyboardButton("+5 дней", callback_data=f"admin_premium_add_days_{target_id}_5"),
            InlineKeyboardButton("+7 дней", callback_data=f"admin_premium_add_days_{target_id}_7")
        ],
        [
            InlineKeyboardButton("Ввести вручную", callback_data=f"admin_premium_add_manual_{target_id}")
        ],
        [
            InlineKeyboardButton("Назад", callback_data=f"admin_user_{target_id}")
        ]
    ]
    await query.edit_message_text("Выберите, на сколько дней добавить премиум:", reply_markup=InlineKeyboardMarkup(keyboard))


async def admin_set_manual_premium_days(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if user.id != MAIN_ADMIN_ID:
        await update.message.reply_text("❌ У вас нет доступа.")
        return ConversationHandler.END

    if 'admin_premium_target' not in context.user_data:
        await update.message.reply_text("Не выбран пользователь.")
        return ConversationHandler.END

    target_id = context.user_data['admin_premium_target']
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("Введите целое число дней.")
        return SET_ADMIN_SELECT_USER_FOR_PREMIUM_DAYS

    days = int(text)
    try:
        new_until = add_or_extend_premium(target_id, days)
        await update.message.reply_text(
            f"Премиум выдан пользователю {target_id} до {new_until.strftime('%d.%m.%Y %H:%M')}"
        )
    except Exception as e:
        logger.error(f"ADMIN_MANUAL_PREMIUM_ERROR: {e}")
        await update.message.reply_text("Ошибка при выдаче премиума.")

    context.user_data.pop('admin_premium_target', None)
    return ConversationHandler.END


async def admin_give_premium_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if user.id != MAIN_ADMIN_ID:
        await update.message.reply_text("❌ У вас нет доступа.")
        return ConversationHandler.END

    text = update.message.text.strip()
    parts = text.split()
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        await update.message.reply_text("Формат: user_id количество_дней\nПример: 123456789 30")
        return SET_GIVE_PREMIUM

    target_id = int(parts[0])
    days = int(parts[1])

    try:
        new_until = add_or_extend_premium(target_id, days)
        await update.message.reply_text(
            f"Премиум выдан пользователю {target_id} до {new_until.strftime('%d.%m.%Y %H:%M')}"
        )
    except Exception as e:
        logger.error(f"ADMIN_GIVE_PREMIUM_ERROR: {e}")
        await update.message.reply_text("Ошибка при выдаче премиума.")

    return ConversationHandler.END


async def admin_remove_premium_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if user.id != MAIN_ADMIN_ID:
        await update.message.reply_text("❌ У вас нет доступа.")
        return ConversationHandler.END

    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("Введите только user_id (число).")
        return SET_REMOVE_PREMIUM

    target_id = int(text)

    try:
        remove_premium(target_id)
        await update.message.reply_text(f"Премиум снят с пользователя {target_id} (если он был).")
    except Exception as e:
        logger.error(f"ADMIN_REMOVE_PREMIUM_ERROR: {e}")
        await update.message.reply_text("Ошибка при снятии премиума.")

    return ConversationHandler.END


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    username = user.username
    first_name = user.first_name

    if is_globally_banned(user_id):
        await update.message.reply_text("🚫 Вы заблокированы в этом боте.")
        return

    if 'recipient_id' in context.user_data:
        recipient_id = context.user_data['recipient_id']

        cursor.execute('SELECT username, first_name FROM user_links WHERE user_id = ?', (recipient_id,))
        rec_data = cursor.fetchone()
        rec_username = rec_data[0] if rec_data else None
        rec_first_name = rec_data[1] if rec_data else None

        cursor.execute(
            'SELECT 1 FROM blocked_users WHERE user_id = ? AND blocked_user_id = ?',
            (recipient_id, user_id)
        )
        if cursor.fetchone():
            await update.message.reply_text("❌ Вы заблокированы у этого пользователя")
            del context.user_data['recipient_id']
            return

        try:
            if update.message.text:
                message_text = update.message.text
                msg_type = "TEXT"
                content = None
            elif update.message.photo:
                message_text = update.message.caption or ""
                msg_type = "PHOTO"
                content = update.message.photo[-1].file_id
            elif update.message.video:
                message_text = update.message.caption or ""
                msg_type = "VIDEO"
                content = update.message.video.file_id
            else:
                await update.message.reply_text("Поддерживаются только: текст, фото или видео")
                return

            log_msg = f"Отправил {msg_type}: {get_user_loginfo(user_id, username, first_name)} -> {get_user_loginfo(recipient_id, rec_username, rec_first_name)}: "
            logger.info(log_msg + (message_text[:100] + '...' if len(message_text) > 100 else message_text))

            cursor.execute(
                '''
                INSERT INTO messages
                (sender_id, recipient_id, sender_username, sender_first_name, message_text, photo_file_id, video_file_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    user_id, recipient_id, username, first_name,
                    message_text,
                    content if msg_type == "PHOTO" else None,
                    content if msg_type == "VIDEO" else None
                )
            )
            conn.commit()

            message_id = cursor.lastrowid

            keyboard = []
            if is_premium(recipient_id):
                keyboard.append([InlineKeyboardButton("Узнать отправителя", callback_data=f"reveal_sender_{message_id}")])
            keyboard.append([InlineKeyboardButton("Ответить", callback_data=f"reply_{message_id}")])
            keyboard.append([InlineKeyboardButton("Заблокировать", callback_data=f"block_{user_id}_{username or first_name}")])
            reply_markup = InlineKeyboardMarkup(keyboard)

            if msg_type == "TEXT":
                await context.bot.send_message(
                    chat_id=recipient_id,
                    text=f"У тебя новое сообщение!\n\n{message_text} \n\nНажми кнопку ниже для ответа",
                    reply_markup=reply_markup
                )
            elif msg_type == "PHOTO":
                await context.bot.send_photo(
                    chat_id=recipient_id,
                    photo=content,
                    caption=f"У тебя новое сообщение!\n\n{message_text} \n\nНажми кнопку ниже для ответа" if message_text else "У тебя новое сообщение!\n\nНажми кнопку ниже для ответа",
                    reply_markup=reply_markup
                )
            elif msg_type == "VIDEO":
                await context.bot.send_video(
                    chat_id=recipient_id,
                    video=content,
                    caption=f"У тебя новое сообщение!\n\n{message_text} \n\nНажми кнопку ниже для ответа" if message_text else "У тебя новое сообщение!\n\nНажми кнопку ниже для ответа",
                    reply_markup=reply_markup
                )

            keyboard = [[InlineKeyboardButton("Отправить еще", callback_data=f"send_again_{recipient_id}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Сообщение отправлено!", reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"ERROR: {get_user_loginfo(user_id, username, first_name)}: {str(e)}")
            await update.message.reply_text("Ошибка при отправке сообщения")
        finally:
            if 'recipient_id' in context.user_data:
                del context.user_data['recipient_id']

    elif 'replying_to' in context.user_data:
        message_id = context.user_data['replying_to']
        cursor.execute('SELECT sender_id FROM messages WHERE message_id = ?', (message_id,))
        result = cursor.fetchone()
        if not result:
            await update.message.reply_text("Оригинальное сообщение не найдено")
            return

        sender_id = result[0]

        if update.message.text:
            reply_text = update.message.text
            reply_photo = None
            reply_video = None
            msg_type = "TEXT"
        elif update.message.photo:
            reply_text = update.message.caption or ""
            reply_photo = update.message.photo[-1].file_id
            reply_video = None
            msg_type = "PHOTO"
        elif update.message.video:
            reply_text = update.message.caption or ""
            reply_photo = None
            reply_video = update.message.video.file_id
            msg_type = "VIDEO"
        else:
            await update.message.reply_text("Поддерживаются только: текст, фото или видео")
            return

        logger.info(
            f"Ответ: {get_user_loginfo(user_id, username, first_name)} -> {get_user_loginfo(sender_id)}: "
            f"{reply_text[:100]}{'...' if len(reply_text) > 100 else ''}"
        )

        cursor.execute(
            '''
            INSERT INTO replies
            (original_message_id, replier_id, reply_text, reply_photo_file_id, reply_video_file_id)
            VALUES (?, ?, ?, ?, ?)
            ''',
            (message_id, user_id, reply_text, reply_photo, reply_video)
        )
        conn.commit()

        try:
            if msg_type == "TEXT":
                await context.bot.send_message(
                    chat_id=sender_id,
                    text=f"Ответ на ваше сообщение:\n\n{reply_text}"
                )
            elif msg_type == "PHOTO":
                await context.bot.send_photo(
                    chat_id=sender_id,
                    photo=reply_photo,
                    caption=f"Ответ на ваше сообщение:\n\n{reply_text}" if reply_text else "Ответ на ваше сообщение"
                )
            elif msg_type == "VIDEO":
                await context.bot.send_video(
                    chat_id=sender_id,
                    video=reply_video,
                    caption=f"Ответ на ваше сообщение:\n\n{reply_text}" if reply_text else "Ответ на ваше сообщение"
                )
            await update.message.reply_text("Ответ отправлен!")
        except Exception as e:
            await update.message.reply_text("Не удалось отправить ответ. Пользователь мог заблокировать бота.")
            logger.error(f"REPLY_ERROR: {str(e)}")
        finally:
            del context.user_data['replying_to']
    else:
        await update.message.reply_text("Для отправки сообщения используйте ссылку получателя или создайте свою (/start)")


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = query.from_user
    user_id = user.id
    username = user.username
    first_name = user.first_name

    if query.data == "admin_list_premium_old":
        if user_id != MAIN_ADMIN_ID:
            await query.edit_message_text("Нет доступа.")
            return

        rows = list_premium_users()
        if not rows:
            await query.edit_message_text("Список премиум-пользователей пуст.")
            return

        msg = "Премиум-пользователи:\n\n"
        for idx, (uid, until_str) in enumerate(rows, 1):
            try:
                dt = datetime.strptime(until_str, "%Y-%m-%d %H:%M:%S")
                until_fmt = dt.strftime("%d.%m.%Y %H:%M")
            except Exception:
                until_fmt = until_str
            msg += f"{idx}. ID: {uid}\n   до: {until_fmt}\n\n"

        await query.edit_message_text(msg)
        return

    if query.data == "admin_users_list":
        if user_id != MAIN_ADMIN_ID:
            await query.edit_message_text("Нет доступа.")
            return
        await admin_show_users_list(query, context)
        return

    if query.data.startswith("admin_user_"):
        if user_id != MAIN_ADMIN_ID:
            await query.edit_message_text("Нет доступа.")
            return
        target_id = int(query.data.split("_")[2])
        await admin_show_user_panel(query, context, target_id)
        return

    if query.data.startswith("admin_globalban_"):
        if user_id != MAIN_ADMIN_ID:
            await query.edit_message_text("Нет доступа.")
            return
        target_id = int(query.data.split("_")[2])
        if is_globally_banned(target_id):
            cursor.execute('DELETE FROM global_ban_users WHERE user_id = ?', (target_id,))
            conn.commit()
            await query.edit_message_text("Глобальный бан снят.", reply_markup=None)
        else:
            cursor.execute('INSERT OR IGNORE INTO global_ban_users (user_id) VALUES (?)', (target_id,))
            conn.commit()
            await query.edit_message_text("Пользователь добавлен в глобальный бан.", reply_markup=None)
        return

    if query.data.startswith("admin_premium_add_") and "days_" not in query.data and "manual_" not in query.data:
        if user_id != MAIN_ADMIN_ID:
            await query.edit_message_text("Нет доступа.")
            return
        target_id = int(query.data.split("_")[3])
        await admin_give_premium_days_menu(query, target_id)
        return

    if query.data.startswith("admin_premium_add_days_"):
        if user_id != MAIN_ADMIN_ID:
            await query.edit_message_text("Нет доступа.")
            return
        parts = query.data.split("_")
        target_id = int(parts[4])
        days = int(parts[5])
        new_until = add_or_extend_premium(target_id, days)
        await query.edit_message_text(
            f"Премиум выдан пользователю {target_id} до {new_until.strftime('%d.%m.%Y %H:%M')}"
        )
        return

    if query.data.startswith("admin_premium_add_manual_"):
        if user_id != MAIN_ADMIN_ID:
            await query.edit_message_text("Нет доступа.")
            return
        target_id = int(query.data.split("_")[4])
        context.user_data['admin_premium_target'] = target_id
        await query.message.reply_text("Введите, на сколько дней выдать премиум (число):")
        return

    if query.data.startswith("admin_premium_remove_"):
        if user_id != MAIN_ADMIN_ID:
            await query.edit_message_text("Нет доступа.")
            return
        target_id = int(query.data.split("_")[3])
        remove_premium(target_id)
        await query.edit_message_text(f"Премиум снят с пользователя {target_id} (если он был).")
        return

    if query.data.startswith("admin_who_blocked_"):
        if user_id != MAIN_ADMIN_ID:
            await query.edit_message_text("Нет доступа.")
            return
        target_id = int(query.data.split("_")[3])
        cursor.execute(
            '''
            SELECT user_id, blocked_username
            FROM blocked_users
            WHERE blocked_user_id = ?
            ''',
            (target_id,)
        )
        rows = cursor.fetchall()
        if not rows:
            await query.edit_message_text("Никто не блокировал этого пользователя.")
            return

        premium_blockers = []
        for uid, blocked_username in rows:
            if is_premium(uid):
                premium_blockers.append((uid, blocked_username))

        if not premium_blockers:
            await query.edit_message_text("Его блокировали только пользователи без премиума.")
            return

        msg = "Пользователь заблокирован у премиум-пользователей:\n\n"
        keyboard = []
        for uid, blocked_username in premium_blockers:
            msg += f"- ID {uid} (@{blocked_username})\n"
            keyboard.append(
                [InlineKeyboardButton(f"Разблокировать у {uid}", callback_data=f"admin_unblock_for_{uid}_{target_id}")]
            )
        keyboard.append(
            [InlineKeyboardButton("Назад", callback_data=f"admin_user_{target_id}")]
        )

        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if query.data.startswith("admin_unblock_for_"):
        if user_id != MAIN_ADMIN_ID:
            await query.edit_message_text("Нет доступа.")
            return
        parts = query.data.split("_")
        owner_id = int(parts[3])
        target_id = int(parts[4])

        cursor.execute(
            'DELETE FROM blocked_users WHERE user_id = ? AND blocked_user_id = ?',
            (owner_id, target_id)
        )
        conn.commit()
        await query.edit_message_text(
            f"Пользователь {target_id} разоблокирован у пользователя {owner_id}.",
            reply_markup=None
        )
        return

    if query.data == "get_link":
        cursor.execute('SELECT unique_code, custom_code FROM user_links WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        unique_code = result[0]
        custom_code = result[1] if result else None

        bot_username = context.bot.username
        link = f"https://t.me/{bot_username}?start={unique_code}"
        custom_link = f"https://t.me/{bot_username}?start={custom_code}" if custom_code else None

        message_text = f"Персональная ссылка:\n{link}"
        if custom_link:
            message_text += f"\n\nПользовательская ссылка:\n{custom_link}"

        if custom_code:
            keyboard = [
                [InlineKeyboardButton("Создать свою ссылку", callback_data="create_custom_link")],
                [InlineKeyboardButton("Вернуть оригинальную ссылку", callback_data="reset_to_original")]
            ]
        else:
            keyboard = [
                [InlineKeyboardButton("Создать свою ссылку", callback_data="create_custom_link")]
            ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message_text, reply_markup=reply_markup)
        return

    elif query.data == "create_custom_link":
        await create_custom_link_start(update, context)
        return

    elif query.data == "reset_to_original":
        await reset_to_original(update, context)
        return

    elif query.data.startswith("reveal_sender_"):
        message_id = int(query.data.split("_")[2])
        cursor.execute('SELECT sender_username, sender_first_name, sender_id FROM messages WHERE message_id = ?', (message_id,))
        result = cursor.fetchone()
        if result:
            sender_username, sender_first_name, sender_id = result
            keyboard = [
                [InlineKeyboardButton("Назад", callback_data=f"go_back_{message_id}")],
                [InlineKeyboardButton("Заблокировать", callback_data=f"block_{sender_id}_{sender_username or sender_first_name}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            text = (
                "Информация об отправителе:\n"
                f"Имя: {sender_first_name}\n"
                f"Username: @{sender_username if sender_username else 'нет'}\n"
                f"ID: {sender_id}"
            )
            if query.message.text:
                await query.edit_message_text(text, reply_markup=reply_markup)
            else:
                await query.edit_message_caption(caption=text, reply_markup=reply_markup)
        else:
            await query.edit_message_text("Информация не найдена")

    elif query.data.startswith("go_back_"):
        message_id = int(query.data.split("_")[2])
        cursor.execute('SELECT message_text, photo_file_id, video_file_id, sender_username, sender_first_name FROM messages WHERE message_id = ?', (message_id,))
        result = cursor.fetchone()
        if result:
            message_text, photo_file_id, video_file_id, sender_username, sender_first_name = result
            keyboard = []
            if is_premium(user_id):
                keyboard.append([InlineKeyboardButton("Узнать отправителя", callback_data=f"reveal_sender_{message_id}")])
            keyboard.append([InlineKeyboardButton("Ответить", callback_data=f"reply_{message_id}")])
            keyboard.append([InlineKeyboardButton("Заблокировать", callback_data=f"block_{message_id}_{sender_username or sender_first_name}")])
            reply_markup = InlineKeyboardMarkup(keyboard)

            base_text = (
                f"У тебя новое сообщение!\n\n{message_text} \n\nНажми кнопку ниже для ответа"
                if message_text else "У тебя новое сообщение!\n\nНажми кнопку ниже для ответа"
            )

            if message_text and not photo_file_id and not video_file_id:
                await query.edit_message_text(
                    base_text,
                    reply_markup=reply_markup
                )
            elif photo_file_id:
                await query.edit_message_caption(
                    caption=base_text,
                    reply_markup=reply_markup
                )
            elif video_file_id:
                await query.edit_message_caption(
                    caption=base_text,
                    reply_markup=reply_markup
                )
            else:
                await query.edit_message_text("Сообщение не найдено")

    elif query.data.startswith("block_"):
        try:
            parts = query.data.split("_")
            blocked_user_id = int(parts[1])
            blocked_username = "_".join(parts[2:])

            cursor.execute(
                'SELECT 1 FROM blocked_users WHERE user_id = ? AND blocked_user_id = ?',
                (user_id, blocked_user_id)
            )
            if cursor.fetchone():
                await query.edit_message_text("Пользователь уже заблокирован")
                return

            cursor.execute(
                '''
                INSERT INTO blocked_users (user_id, blocked_user_id, blocked_username)
                VALUES (?, ?, ?)
                ''',
                (user_id, blocked_user_id, blocked_username)
            )
            conn.commit()

            await query.edit_message_text(
                "Пользователь заблокирован\n\n"
                "Он больше не сможет писать вам сообщения\n"
                f"Для разблокировки: /unban @{blocked_username}"
            )
        except Exception as e:
            logger.error(f"BLOCK_ERROR: {get_user_loginfo(user_id, username, first_name)}: {str(e)}")
            await query.edit_message_text("Ошибка при блокировке")

    elif query.data.startswith("send_again_"):
        recipient_id = int(query.data.split("_")[2])
        context.user_data['recipient_id'] = recipient_id
        await query.message.reply_text("Напишите новое сообщение для этого пользователя:")

    elif query.data.startswith("reply_"):
        message_id = int(query.data.split("_")[1])
        context.user_data['replying_to'] = message_id
        await query.message.reply_text("Напишите ваш ответ на это сообщение:")


async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id

    if not context.args:
        await update.message.reply_text("Использование: /unban @username")
        return

    target_username = context.args[0].lstrip('@')
    if not target_username:
        await update.message.reply_text("Укажите username (например: /unban @username)")
        return

    cursor.execute(
        'DELETE FROM blocked_users WHERE user_id = ? AND blocked_username = ?',
        (user_id, target_username)
    )
    conn.commit()

    if cursor.rowcount > 0:
        await update.message.reply_text(f"@{target_username} разблокирован")
    else:
        await update.message.reply_text(f"@{target_username} не найден в вашем списке блокировок")


async def banlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id

    cursor.execute(
        '''
        SELECT blocked_username, blocked_at
        FROM blocked_users
        WHERE user_id = ?
        ORDER BY blocked_at DESC
        ''',
        (user_id,)
    )
    blocked_users = cursor.fetchall()

    if not blocked_users:
        await update.message.reply_text("У вас нет заблокированных пользователей")
        return

    message_txt = "Ваш список заблокированных пользователей:\n\n"
    for idx, (username_b, blocked_at) in enumerate(blocked_users, 1):
        blocked_time = datetime.strptime(blocked_at, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M")
        message_txt += (
            f"{idx}. @{username_b}\n"
            f" {blocked_time}\n"
            f" /unban @{username_b}\n\n"
        )

    await update.message.reply_text(message_txt, parse_mode="HTML")


async def error(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        update_id = update.update_id if update else "N/A"
        error_msg = str(context.error) if context.error else "Unknown error"
        logger.error(f"UPDATE_ERROR (update_id: {update_id}): {error_msg}")

        if update and update.effective_user:
            user_info = get_user_loginfo(
                update.effective_user.id,
                update.effective_user.username,
                update.effective_user.first_name
            )
            logger.error(f"User info: {user_info}")

        if update and update.effective_message:
            logger.error(f"Message text: {update.effective_message.text}")
    except Exception as e:
        logger.error(f"ERROR_IN_ERROR_HANDLER: {str(e)}")


def main() -> None:
    application = Application.builder().token("YOUR_BOT_TOKEN_HERE").build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(create_custom_link_start, pattern="^create_custom_link$")],
        states={
            SET_CUSTOM_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_custom_link)],
        },
        fallbacks=[CommandHandler('cancel', cancel_custom_link)],
    )

    admin_conv_handler = ConversationHandler(
        entry_points=[],
        states={
            SET_GIVE_PREMIUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_give_premium_input)],
            SET_REMOVE_PREMIUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_remove_premium_input)],
            SET_ADMIN_SELECT_USER_FOR_PREMIUM_DAYS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_set_manual_premium_days)
            ],
        },
        fallbacks=[],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("unban", unban))
    application.add_handler(CommandHandler("banlist", banlist))
    application.add_handler(CommandHandler("admin", admin_menu))

    application.add_handler(conv_handler)
    application.add_handler(admin_conv_handler)

    application.add_handler(MessageHandler(
        filters.TEXT | filters.PHOTO | filters.VIDEO & ~filters.COMMAND,
        handle_message
    ))
    application.add_handler(CallbackQueryHandler(button_callback))

    application.add_error_handler(error)

    logger.info("Bot started")
    application.run_polling()


if __name__ == "__main__":
    main()
