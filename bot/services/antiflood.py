"""Простой антифлуд: минимальный интервал между действиями пользователя.

Состояние в памяти процесса, сбрасывается при перезапуске — так же, как и
context.user_data, уже используемый в проекте. Для одного процесса-бота этого
достаточно; если бот когда-нибудь станет многопроцессным, кулдаун нужно будет
вынести в общее хранилище (например, ту же SQLite или Redis).
"""
import time

from bot.core.config import MESSAGE_COOLDOWN_SECONDS

_last_action_time: dict[int, float] = {}


def check_cooldown(user_id: int) -> float:
    """Возвращает оставшиеся секунды кулдауна (0, если можно отправлять)."""
    last = _last_action_time.get(user_id)
    if last is None:
        return 0.0
    remaining = MESSAGE_COOLDOWN_SECONDS - (time.monotonic() - last)
    return max(0.0, remaining)


def mark_action(user_id: int) -> None:
    _last_action_time[user_id] = time.monotonic()


# Отдельный, более строгий лимитер именно для попыток погасить промокод.
# Раньше /promo вообще не имел ограничения скорости — можно было перебирать
# короткие коды скриптом без всякой задержки. Не объединяю с кулдауном выше:
# это разные по смыслу действия (отправка сообщения vs подбор кода), и общий
# счётчик означал бы, что отправка сообщения "тратит" лимит на попытки промо.
PROMO_ATTEMPT_COOLDOWN_SECONDS = 2
_last_promo_attempt: dict[int, float] = {}


def check_promo_cooldown(user_id: int) -> float:
    last = _last_promo_attempt.get(user_id)
    if last is None:
        return 0.0
    remaining = PROMO_ATTEMPT_COOLDOWN_SECONDS - (time.monotonic() - last)
    return max(0.0, remaining)


def mark_promo_attempt(user_id: int) -> None:
    _last_promo_attempt[user_id] = time.monotonic()
