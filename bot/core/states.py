"""Состояния диалогов (FSM aiogram) — замена ConversationHandler-констант PTB."""
from aiogram.fsm.state import State, StatesGroup


class CustomLinkStates(StatesGroup):
    waiting_for_code = State()


class AdminPremiumStates(StatesGroup):
    waiting_give_premium = State()       # "user_id дни" одной строкой
    waiting_remove_premium = State()     # только user_id
    waiting_manual_days = State()        # только число дней, target уже выбран кнопкой


class PromoStates(StatesGroup):
    waiting_new_code = State()  # ввод "КОД ДНИ [ЛИМИТ]" одной строкой


class BroadcastStates(StatesGroup):
    waiting_content = State()  # текст или медиа с подписью; подтверждение через inline-кнопки


class AdminSearchStates(StatesGroup):
    waiting_query = State()  # ID, @username или часть имени для поиска пользователя


class AdminManagementStates(StatesGroup):
    waiting_new_admin_id = State()  # ввод Telegram ID нового под-админа
