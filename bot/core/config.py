"""Конфигурация: переменные окружения, логирование, константы состояний."""
import logging
import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не задан. Скопируйте .env.example в .env и укажите токен бота от BotFather."
    )

try:
    MAIN_ADMIN_ID = int(os.environ.get("MAIN_ADMIN_ID", "0"))
except ValueError:
    raise RuntimeError("MAIN_ADMIN_ID в .env должен быть целым числом (Telegram user ID).")

# Каталог для файлов БД (SQLite). В Docker указывает на смонтированный volume,
# при локальном запуске по умолчанию — текущая директория проекта.
DATA_DIR = os.environ.get("DATA_DIR") or "."
os.makedirs(DATA_DIR, exist_ok=True)

# Простой антифлуд: минимальный интервал между анонимными сообщениями/ответами
# одного пользователя.
try:
    MESSAGE_COOLDOWN_SECONDS = float(os.environ.get("MESSAGE_COOLDOWN_SECONDS", "3"))
except ValueError:
    MESSAGE_COOLDOWN_SECONDS = 3.0

# Хранилище состояний FSM. Если не задано — состояния (ожидание кастомной
# ссылки, ввод дней премиума и т.п.) живут только в памяти процесса и
# теряются при перезапуске бота. С Redis они переживают рестарт/деплой.
REDIS_URL = os.environ.get("REDIS_URL") or None

# DSN для Sentry (опционально). Если не задан — ошибки только в логах, как и
# раньше; ничего никуда не отправляется.
SENTRY_DSN = os.environ.get("SENTRY_DSN") or None

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("anon_bot")

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("aiogram").setLevel(logging.WARNING)
