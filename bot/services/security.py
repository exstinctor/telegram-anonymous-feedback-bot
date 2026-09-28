"""Фильтр потенциально опасных вложений."""
import os

# Расширения, которые не пересылаются анонимно из соображений безопасности
# (исполняемые файлы, скрипты, установщики).
DANGEROUS_FILE_EXTENSIONS = {
    ".exe", ".msi", ".bat", ".cmd", ".com", ".scr", ".vbs", ".vbe",
    ".js", ".jse", ".ws", ".wsf", ".ps1", ".psm1", ".apk", ".jar",
    ".sh", ".bash", ".app", ".dmg", ".deb", ".rpm", ".lnk", ".reg",
    ".dll", ".cpl", ".msc", ".scf", ".hta",
}


def is_dangerous_document(file_name) -> bool:
    if not file_name:
        return False
    return os.path.splitext(file_name)[1].lower() in DANGEROUS_FILE_EXTENSIONS
