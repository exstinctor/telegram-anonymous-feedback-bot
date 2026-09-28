"""Мелкие независимые утилиты без побочных эффектов."""
import re

_CYRILLIC_TO_LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def get_user_loginfo(user_id, username=None, first_name=None) -> str:
    if username:
        return f"@{username} (ID:{user_id})"
    if first_name:
        return f"{first_name} (ID:{user_id})"
    return f"(ID:{user_id})"


def is_valid_custom_link(link: str) -> bool:
    return bool(re.match(r'^[a-zA-Z0-9_-]{3,20}$', link))


def transliterate_to_latin(text: str) -> str:
    """Кириллица -> латиница (упрощённая практическая транслитерация).

    Не трогает уже латинские символы, цифры, _ и - — так что смешанный ввод
    вроде "мой_link2" превратится в "moy_link2", а не потеряет часть текста.
    Любые прочие символы (эмодзи, другие алфавиты, пробелы) отбрасываются,
    чтобы результат можно было сразу проверить через is_valid_custom_link.
    """
    result = []
    for ch in text:
        lower = ch.lower()
        if lower in _CYRILLIC_TO_LATIN:
            translit = _CYRILLIC_TO_LATIN[lower]
            result.append(translit.upper() if ch.isupper() and translit else translit)
        elif re.match(r'[a-zA-Z0-9_-]', ch):
            result.append(ch)
        # всё остальное (пробелы, эмодзи, другие алфавиты) молча пропускаем
    return "".join(result)


def normalize_code(raw: str) -> tuple[str, bool]:
    """Готовит пользовательский ввод (кастомная ссылка/промокод) к валидации.

    Возвращает (код, был_ли_транслитерирован). Если исходный текст уже
    проходит is_valid_custom_link — возвращает его как есть. Иначе пробует
    транслитерировать кириллицу в латиницу и возвращает результат (который
    ещё нужно повторно проверить через is_valid_custom_link — транслит не
    гарантирует валидную длину/непустоту).
    """
    if is_valid_custom_link(raw):
        return raw, False
    translit = transliterate_to_latin(raw)
    return translit, translit != raw
