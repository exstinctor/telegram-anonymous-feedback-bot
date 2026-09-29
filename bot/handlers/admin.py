"""Админ-панель: список пользователей, премиум, глобальный бан-лист.

Обработчики команды /admin и текстового ввода дней премиума ("вручную") живут
здесь; сама регистрация callback-кнопок — в callbacks.py (там же ссылки на
admin_show_users_list / admin_show_global_ban_list / admin_show_user_panel /
admin_give_premium_days_menu, определённые ниже).
"""
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.core.config import logger
from bot.core.states import AdminManagementStates, AdminPremiumStates, AdminSearchStates, PromoStates
from bot.db import repository as db
from bot.db.premium import add_or_extend_premium, count_active_premium, count_all_premium_records, get_premium_page, get_user_premium_until
from bot.services.filters import not_a_command
from bot.services.permissions import is_admin, is_super_admin
from bot.services.telegram_ui import safe_edit_caption, safe_edit_text
from bot.services.utils import is_valid_custom_link, normalize_code

router = Router(name="admin")

USERS_PAGE_SIZE = 10
BAN_LIST_PAGE_SIZE = 10
PREMIUM_PAGE_SIZE = 10
SEARCH_RESULTS_LIMIT = 10


@router.message(Command("admin"))
async def admin_menu(message: Message) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа к админ-меню.")
        return

    keyboard = [
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users_list_page_0")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast_start")],
        [InlineKeyboardButton(text="📋 Премиум-таблица", callback_data="admin_premium_list_page_0")],
        [InlineKeyboardButton(text="🎁 Промокоды", callback_data="admin_promo_list")],
        [InlineKeyboardButton(text="🚫 Глобальный бан-лист", callback_data="admin_global_ban_list_page_0")]
    ]
    if is_super_admin(message.from_user.id):
        keyboard.append([InlineKeyboardButton(text="👤 Админы", callback_data="admin_manage_list")])
    await message.answer("Админ-меню:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


def _pagination_row(base_callback: str, page: int, total: int, page_size: int):
    row = []
    if page > 0:
        row.append(InlineKeyboardButton(text="« Назад", callback_data=f"{base_callback}_{page - 1}"))
    if (page + 1) * page_size < total:
        row.append(InlineKeyboardButton(text="Далее »", callback_data=f"{base_callback}_{page + 1}"))
    return row


async def admin_show_users_list(callback: CallbackQuery, page: int = 0) -> None:
    total = db.count_users()
    if total == 0:
        await safe_edit_text(callback.message, "В боте пока нет пользователей.")
        return

    max_page = (total - 1) // USERS_PAGE_SIZE
    page = max(0, min(page, max_page))

    users = db.get_users_page(offset=page * USERS_PAGE_SIZE, limit=USERS_PAGE_SIZE)

    keyboard = [[InlineKeyboardButton(text="🔍 Найти пользователя", callback_data="admin_search_start")]]
    for user_id, username, first_name in users:
        display = f"{first_name or ''} (@{username})" if username else f"{first_name or ''} (ID:{user_id})"
        keyboard.append([InlineKeyboardButton(text=display, callback_data=f"admin_user_{user_id}")])

    nav_row = _pagination_row("admin_users_list_page", page, total, USERS_PAGE_SIZE)
    if nav_row:
        keyboard.append(nav_row)

    total_pages = max(1, -(-total // USERS_PAGE_SIZE))
    header = f"Выберите пользователя (стр. {page + 1}/{total_pages}, всего {total}):"
    await safe_edit_text(callback.message, header, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


async def admin_show_stats(callback: CallbackQuery) -> None:
    text = (
        "📊 Статистика бота:\n\n"
        f"👥 Пользователей: {db.count_users()}\n"
        f"💬 Отправлено анонимных сообщений: {db.count_messages()}\n"
        f"↩️ Отправлено ответов: {db.count_replies()}\n"
        f"⭐ Активных премиум: {count_active_premium()}\n"
        f"⛔ Личных блокировок: {db.count_blocked_pairs()}\n"
        f"🚫 В глобальном бане: {db.count_global_ban_list()}\n"
        f"🎁 Промокодов создано: {db.count_promo_codes()} (погашений: {db.count_promo_redemptions()})"
    )
    keyboard = [[InlineKeyboardButton(text="Назад", callback_data="admin_menu_back")]]
    await safe_edit_text(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


async def admin_show_premium_list(callback: CallbackQuery, page: int = 0) -> None:
    total = count_all_premium_records()

    keyboard = [[InlineKeyboardButton(text="Назад", callback_data="admin_menu_back")]]
    if total == 0:
        await safe_edit_text(callback.message, 
            "Список премиум-пользователей пуст.", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        return

    max_page = (total - 1) // PREMIUM_PAGE_SIZE
    page = max(0, min(page, max_page))

    rows = get_premium_page(offset=page * PREMIUM_PAGE_SIZE, limit=PREMIUM_PAGE_SIZE)

    lines = ["Премиум-пользователи:\n"]
    for idx, (user_id, until_str) in enumerate(rows, page * PREMIUM_PAGE_SIZE + 1):
        try:
            until_fmt = datetime.strptime(until_str, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M")
        except (ValueError, TypeError):
            until_fmt = until_str
        lines.append(f"{idx}. ID: {user_id}\n   до: {until_fmt}\n")

    nav_row = _pagination_row("admin_premium_list_page", page, total, PREMIUM_PAGE_SIZE)
    if nav_row:
        keyboard.insert(-1, nav_row)

    total_pages = max(1, -(-total // PREMIUM_PAGE_SIZE))
    lines.append(f"\nСтраница {page + 1}/{total_pages}")
    await safe_edit_text(callback.message, "\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


def _build_global_ban_list_view(page: int = 0):
    """(текст, клавиатура) для экрана глобального бан-листа — общая логика
    для callback-кнопки (edit) и команды /banlist (answer), чтобы не
    дублировать пагинацию и форматирование в двух местах."""
    total = db.count_global_ban_list()
    keyboard = [[InlineKeyboardButton(text="Назад", callback_data="admin_users_list_page_0")]]
    if total == 0:
        return "Глобальный бан-лист пуст.", InlineKeyboardMarkup(inline_keyboard=keyboard)

    max_page = (total - 1) // BAN_LIST_PAGE_SIZE
    page = max(0, min(page, max_page))

    rows = db.get_global_ban_list_page(offset=page * BAN_LIST_PAGE_SIZE, limit=BAN_LIST_PAGE_SIZE)

    lines = ["🚫 Глобально забаненные пользователи:\n"]
    for target_id, ban_username, ban_first_name in rows:
        label = f"@{ban_username}" if ban_username else (ban_first_name or f"ID:{target_id}")
        lines.append(f"- {label} (ID:{target_id})")
        keyboard.insert(-1, [InlineKeyboardButton(text=f"Снять бан: {label}", callback_data=f"admin_globalban_{target_id}")])

    nav_row = _pagination_row("admin_global_ban_list_page", page, total, BAN_LIST_PAGE_SIZE)
    if nav_row:
        keyboard.insert(-1, nav_row)

    total_pages = max(1, -(-total // BAN_LIST_PAGE_SIZE))
    lines.append(f"\nСтраница {page + 1}/{total_pages}")
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=keyboard)


async def admin_show_global_ban_list(callback: CallbackQuery, page: int = 0) -> None:
    text, keyboard = _build_global_ban_list_view(page)
    await safe_edit_text(callback.message, text, reply_markup=keyboard)


@router.message(Command("banlist"))
async def admin_banlist_command(message: Message) -> None:
    """Глобальный бан-лист — админская команда. Не путать с личным
    /blocklist пользователя (bot/handlers/moderation.py) — раньше обе команды
    назывались одинаково и путали и админов, и пользователей."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа.")
        return
    text, keyboard = _build_global_ban_list_view(0)
    await message.answer(text, reply_markup=keyboard)


@router.message(Command("unban"))
async def admin_unban_command(message: Message, command: CommandObject) -> None:
    """Снять ГЛОБАЛЬНЫЙ бан по Telegram ID — админская команда. Личная
    разблокировка отправителя пользователем — /unblock (bot/handlers/moderation.py)."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа.")
        return
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Использование: /unban ID — Telegram ID пользователя (число)")
        return
    target_id = int(command.args.strip())
    if not db.is_globally_banned(target_id):
        await message.answer(f"Пользователь {target_id} не находится в глобальном бане.")
        return
    db.global_unban(target_id)
    await message.answer(f"✅ Глобальный бан снят с пользователя {target_id}.")


def _search_button_text(user_id: int, username, first_name) -> str:
    name = first_name or "Без имени"
    return f"{name} (@{username}) · {user_id}" if username else f"{name} · {user_id}"


def _build_search_results(query: str):
    """(текст, клавиатура) с результатами поиска или None, если ничего не найдено.

    Нажатие на результат ведёт в ту же карточку пользователя (admin_user_<id>),
    что и обычный список, — отдельной логики управления пользователем нет.
    """
    users = db.search_users(query, limit=SEARCH_RESULTS_LIMIT)
    if not users:
        return None

    total = db.count_users_matching(query)
    text = f"🔍 Найдено: {total}"
    if total > len(users):
        text += f" (показаны первые {len(users)}, уточните запрос)"

    keyboard = [
        [InlineKeyboardButton(text=_search_button_text(*user), callback_data=f"admin_user_{user[0]}")]
        for user in users
    ]
    keyboard.append([InlineKeyboardButton(text="🔍 Искать ещё", callback_data="admin_search_start")])
    keyboard.append([InlineKeyboardButton(text="« К списку", callback_data="admin_users_list_page_0")])
    return text, InlineKeyboardMarkup(inline_keyboard=keyboard)


SEARCH_PROMPT = (
    "Введите Telegram ID, @username или часть имени пользователя.\n\n"
    "/cancel — отменить."
)


@router.callback_query(F.data == "admin_search_start")
async def admin_search_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await callback.answer()
    await state.set_state(AdminSearchStates.waiting_query)
    await callback.message.reply(SEARCH_PROMPT)


@router.message(AdminSearchStates.waiting_query, not_a_command)
async def admin_search_finish(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа.")
        await state.clear()
        return

    query = (message.text or "").strip()
    if not query:
        await message.answer("Отправьте текст: ID, @username или часть имени. /cancel — отменить.")
        return

    result = _build_search_results(query)
    if result is None:
        # Состояние не сбрасываем: опечатку можно исправить, не нажимая кнопку заново.
        await message.answer("Никого не нашёл. Попробуйте другой запрос или /cancel для отмены.")
        return

    await state.clear()
    text, keyboard = result
    await message.answer(text, reply_markup=keyboard)


@router.message(Command("find"))
async def admin_find_command(message: Message, command: CommandObject, state: FSMContext) -> None:
    """Быстрый поиск без кнопок: /find ID | @username | часть имени."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа.")
        return
    if not command.args or not command.args.strip():
        await message.answer("Использование: /find ID, @username или часть имени")
        return

    result = _build_search_results(command.args)
    if result is None:
        await message.answer("Никого не нашёл.")
        return

    await state.clear()  # не оставляем висящим прежнее ожидание ввода
    text, keyboard = result
    await message.answer(text, reply_markup=keyboard)


def _get_user_full_info(user_id: int, bot_username: str):
    row = db.get_user_link_row(user_id)
    if not row:
        return None
    username, first_name, custom_code, unique_code = row

    direct_link = f"https://t.me/{username}" if username else f"tg://user?id={user_id}"

    premium_until = "нет"
    raw_until = get_user_premium_until(user_id)
    if raw_until:
        try:
            premium_until = datetime.strptime(raw_until, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M")
        except ValueError:
            premium_until = raw_until

    return {
        "user_id": user_id,
        "username": username,
        "first_name": first_name,
        "direct_link": direct_link,
        "premium_until": premium_until,
        "unique_link": f"https://t.me/{bot_username}?start={unique_code}",
        "custom_link": f"https://t.me/{bot_username}?start={custom_code}" if custom_code else "нет",
    }


async def admin_show_user_panel(callback: CallbackQuery, bot: Bot, target_id: int) -> None:
    me = await bot.get_me()
    info = _get_user_full_info(target_id, me.username)
    if not info:
        await safe_edit_text(callback.message, "Пользователь не найден.")
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

    g_banned = db.is_globally_banned(target_id)
    keyboard = [
        [InlineKeyboardButton(
            text="Глобально заблокировать" if not g_banned else "Снять глобальный бан",
            callback_data=f"admin_globalban_{target_id}"
        )],
        [
            InlineKeyboardButton(text="Добавить премиум", callback_data=f"admin_premium_add_{target_id}"),
            InlineKeyboardButton(text="Убрать премиум", callback_data=f"admin_premium_remove_{target_id}")
        ],
        [InlineKeyboardButton(text="Кто его блокировал", callback_data=f"admin_who_blocked_{target_id}")],
        [InlineKeyboardButton(text="Назад к списку", callback_data="admin_users_list_page_0")]
    ]
    await safe_edit_text(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


async def admin_give_premium_days_menu(callback: CallbackQuery, target_id: int) -> None:
    keyboard = [
        [
            InlineKeyboardButton(text="+1 день", callback_data=f"admin_premium_add_days_{target_id}_1"),
            InlineKeyboardButton(text="+3 дня", callback_data=f"admin_premium_add_days_{target_id}_3")
        ],
        [
            InlineKeyboardButton(text="+5 дней", callback_data=f"admin_premium_add_days_{target_id}_5"),
            InlineKeyboardButton(text="+7 дней", callback_data=f"admin_premium_add_days_{target_id}_7")
        ],
        [InlineKeyboardButton(text="Ввести вручную", callback_data=f"admin_premium_add_manual_{target_id}")],
        [InlineKeyboardButton(text="Назад", callback_data=f"admin_user_{target_id}")]
    ]
    await safe_edit_text(callback.message, 
        "Выберите, на сколько дней добавить премиум:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )


@router.message(AdminPremiumStates.waiting_manual_days, not_a_command)
async def admin_set_manual_premium_days(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа.")
        await state.clear()
        return

    data = await state.get_data()
    target_id = data.get("admin_premium_target")
    if target_id is None:
        await message.answer("Не выбран пользователь.")
        await state.clear()
        return

    text = (message.text or "").strip()
    if not text.isdigit() or int(text) <= 0:
        await message.answer("Введите целое число дней, больше нуля.")
        return

    days = int(text)
    try:
        new_until = add_or_extend_premium(target_id, days)
        await message.answer(f"Премиум выдан пользователю {target_id} до {new_until.strftime('%d.%m.%Y %H:%M')}")
    except Exception as e:
        logger.error(f"ADMIN_MANUAL_PREMIUM_ERROR: {e}")
        await message.answer("Ошибка при выдаче премиума.")

    await state.clear()


# ---------------------------------------------------------------------------
# Промокоды
# ---------------------------------------------------------------------------


async def admin_show_promo_list(callback: CallbackQuery) -> None:
    codes = db.list_promo_codes()

    keyboard = [
        [InlineKeyboardButton(text="➕ Создать промокод", callback_data="admin_promo_create")],
        [InlineKeyboardButton(text="Назад", callback_data="admin_menu_back")],
    ]

    if not codes:
        await safe_edit_text(callback.message, 
            "Промокодов пока нет.", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        return

    lines = ["🎁 Промокоды:\n"]
    for code, days, max_uses, used_count in codes:
        limit_txt = f"{used_count}/{max_uses}" if max_uses is not None else f"{used_count}/∞"
        lines.append(f"- «{code}» — {days} дн., использован {limit_txt}")
        keyboard.insert(-2, [InlineKeyboardButton(text=f"❌ Удалить {code}", callback_data=f"admin_promo_delete_{code}")])

    await safe_edit_text(callback.message, "\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


@router.callback_query(F.data == "admin_promo_create")
async def admin_promo_create_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await callback.answer()
    await state.set_state(PromoStates.waiting_new_code)
    await callback.message.reply(
        "Введите промокод одной строкой в формате:\n"
        "КОД ДНИ [ЛИМИТ]\n\n"
        "Например: SUMMER25 7 100 (7 дней премиума, максимум 100 активаций)\n"
        "или WELCOME 3 (без лимита активаций).\n\n"
        "Код: латинские буквы, цифры, _ и -, от 3 до 20 символов.\n"
        "/cancel — отменить."
    )


def _parse_and_create_promo(parts: list, admin_id: int):
    """Общая логика создания промокода — используется и из FSM-формы
    («➕ Создать промокод»), и из прямой команды /createpromo.

    Возвращает (ok, text): ok=False значит "переспроси" (формат/лимит),
    ok=True значит готовый ответ (успех или "уже существует")."""
    if len(parts) not in (2, 3) or not parts[1].isdigit() or (len(parts) == 3 and not parts[2].isdigit()):
        return False, (
            "Формат: КОД ДНИ [ЛИМИТ], например SUMMER25 7 100 или WELCOME 3.\n"
            "Попробуйте ещё раз или /cancel для отмены."
        )

    raw_code = parts[0]
    code, was_translit = normalize_code(raw_code)
    code = code.upper()
    days = int(parts[1])
    max_uses = int(parts[2]) if len(parts) == 3 else None

    if not is_valid_custom_link(code):
        return False, (
            "❌ Некорректный код: только латинские буквы, цифры, _ и -, от 3 до 20 символов "
            "(кириллица автоматически транслитерируется, но результат должен быть такой же длины).\n"
            "Попробуйте ещё раз или /cancel для отмены."
        )

    if days <= 0:
        return False, "Количество дней должно быть больше нуля. Попробуйте ещё раз."

    if max_uses is not None and max_uses <= 0:
        return False, "Лимит активаций должен быть больше нуля (или не указывайте его вовсе). Попробуйте ещё раз."

    created = db.create_promo_code(code, days=days, max_uses=max_uses, created_by=admin_id)
    translit_note = f" (код «{raw_code}» преобразован из кириллицы)" if was_translit else ""
    if not created:
        return True, f"❌ Промокод «{code}»{translit_note} уже существует."

    limit_txt = f"максимум {max_uses} активаций" if max_uses is not None else "без лимита активаций"
    return True, f"✅ Промокод «{code}»{translit_note} создан: {days} дн. премиума, {limit_txt}."


@router.message(PromoStates.waiting_new_code, not_a_command)
async def admin_promo_create_finish(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа.")
        await state.clear()
        return

    parts = (message.text or "").strip().split()
    ok, text = _parse_and_create_promo(parts, message.from_user.id)
    await message.answer(text)
    if ok:
        await state.clear()
    # ok=False значит "переспроси" — состояние остаётся, чтобы можно было
    # ввести ещё раз без повторного нажатия кнопки.


@router.message(Command("createpromo"))
async def create_promo_command(message: Message, command: CommandObject) -> None:
    """Быстрый способ создать промокод одной командой, без похода в меню:
    /createpromo КОД ДНИ [ЛИМИТ]"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа.")
        return

    if not command.args:
        await message.answer(
            "Использование: /createpromo КОД ДНИ [ЛИМИТ]\n"
            "Например: /createpromo SUMMER25 7 100"
        )
        return

    parts = command.args.strip().split()
    _ok, text = _parse_and_create_promo(parts, message.from_user.id)
    await message.answer(text)


@router.callback_query(F.data.startswith("admin_promo_delete_"))
async def admin_promo_delete(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    code = callback.data[len("admin_promo_delete_"):]
    deleted = db.delete_promo_code(code)
    if deleted:
        await callback.answer(f"Промокод {code} удалён.")
    else:
        await callback.answer("Уже удалён.")
    await admin_show_promo_list(callback)


# ---------------------------------------------------------------------------
# Управление под-админами (только для главного админа — MAIN_ADMIN_ID)
# ---------------------------------------------------------------------------


async def admin_show_admins_list(callback: CallbackQuery) -> None:
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Только главный администратор может управлять админами.", show_alert=True)
        return

    admins = db.list_admins()
    keyboard = [
        [InlineKeyboardButton(text="➕ Добавить админа", callback_data="admin_manage_add")],
        [InlineKeyboardButton(text="Назад", callback_data="admin_menu_back")],
    ]

    if not admins:
        await safe_edit_text(callback.message, 
            "Под-админов пока нет — только вы (главный администратор).",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        return

    lines = ["👤 Под-админы:\n"]
    for user_id, added_by, added_at in admins:
        lines.append(f"- ID {user_id}")
        keyboard.insert(-2, [InlineKeyboardButton(text=f"❌ Снять {user_id}", callback_data=f"admin_manage_remove_{user_id}")])

    await safe_edit_text(callback.message, "\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


@router.callback_query(F.data == "admin_manage_add")
async def admin_manage_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Только главный администратор может управлять админами.", show_alert=True)
        return
    await callback.answer()
    await state.set_state(AdminManagementStates.waiting_new_admin_id)
    await callback.message.reply(
        "Пришлите Telegram ID пользователя, которого нужно сделать админом (число).\n"
        "Узнать ID можно, например, у @userinfobot.\n\n/cancel — отменить."
    )


@router.message(AdminManagementStates.waiting_new_admin_id, not_a_command)
async def admin_manage_add_finish(message: Message, state: FSMContext) -> None:
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ У вас нет доступа.")
        await state.clear()
        return

    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("ID должен быть числом. Попробуйте ещё раз или /cancel для отмены.")
        return

    new_admin_id = int(text)
    await state.clear()

    if new_admin_id == message.from_user.id:
        await message.answer("Вы и так главный администратор.")
        return

    db.add_admin(new_admin_id, added_by=message.from_user.id)
    await message.answer(f"✅ Пользователь {new_admin_id} назначен админом.")


@router.callback_query(F.data.startswith("admin_manage_remove_"))
async def admin_manage_remove(callback: CallbackQuery) -> None:
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Только главный администратор может управлять админами.", show_alert=True)
        return
    target_id = int(callback.data[len("admin_manage_remove_"):])
    removed = db.remove_admin(target_id)
    await callback.answer(f"Админ {target_id} снят." if removed else "Уже не админ.")
    await admin_show_admins_list(callback)


@router.callback_query(F.data == "admin_menu_back")
async def admin_menu_back(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    keyboard = [
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users_list_page_0")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast_start")],
        [InlineKeyboardButton(text="📋 Премиум-таблица", callback_data="admin_premium_list_page_0")],
        [InlineKeyboardButton(text="🎁 Промокоды", callback_data="admin_promo_list")],
        [InlineKeyboardButton(text="🚫 Глобальный бан-лист", callback_data="admin_global_ban_list_page_0")]
    ]
    if is_super_admin(callback.from_user.id):
        keyboard.append([InlineKeyboardButton(text="👤 Админы", callback_data="admin_manage_list")])
    await safe_edit_text(callback.message, "Админ-меню:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
