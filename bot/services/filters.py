"""Общие фильтры для роутеров aiogram."""
from aiogram.types import Message


def not_a_command(message: Message) -> bool:
    """True, если сообщение НЕ является командой (текст не начинается с '/').

    Обязателен как дополнительный фильтр на каждом FSM-состоянии, ожидающем
    ввод (кастомная ссылка, промокод, дни премиума, содержимое рассылки,
    добавление админа): без него, например, "/cancel" во время ожидания
    текста перехватывался бы самим FSM-хендлером, а не командой /cancel —
    Telegram кладёт "/cancel" в message.text как обычный текст, а у aiogram
    State-фильтр не имеет приоритета над Command(): побеждает порядок
    регистрации хендлеров, а не "специфичность" фильтра. Подтверждено на
    практике эмпирическим тестом (feed_update с текстом "/cancel" в
    состоянии CustomLinkStates.waiting_for_code реально уходил в
    set_custom_link, а не в cancel_dialog).
    """
    return not (message.text and message.text.startswith("/"))
