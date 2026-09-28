"""Проверка прав администратора.

Главный админ (MAIN_ADMIN_ID из .env) — единственный, кто может назначать и
снимать под-админов; он не хранится в таблице admins, а всегда считается
администратором по определению. Под-админы из таблицы admins получают доступ
к остальной админ-панели наравне с ним, кроме управления самими админами.
"""
from bot.core.config import MAIN_ADMIN_ID
from bot.db import repository as db


def is_super_admin(user_id: int) -> bool:
    """Только главный админ — может добавлять/удалять под-админов."""
    return user_id == MAIN_ADMIN_ID


def is_admin(user_id: int) -> bool:
    """Главный админ или любой назначенный им под-админ."""
    return user_id == MAIN_ADMIN_ID or db.is_sub_admin(user_id)
