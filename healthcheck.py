"""Скрипт для Docker HEALTHCHECK.

У long-polling бота нет HTTP-эндпоинта, поэтому здоровье определяется по
heartbeat-файлу, который main.py обновляет каждые 30 секунд (см.
HEARTBEAT_INTERVAL_SECONDS). Если файл не обновлялся дольше STALE_AFTER_SECONDS
— event loop, скорее всего, завис или процесс упал.

Exit code 0 = healthy, 1 = unhealthy (стандарт Docker HEALTHCHECK).
"""
import os
import sys
import time

STALE_AFTER_SECONDS = 90  # 3 пропущенных heartbeat-интервала (по 30 сек)


def main() -> int:
    data_dir = os.environ.get("DATA_DIR") or "."
    heartbeat_path = os.path.join(data_dir, "heartbeat")

    try:
        with open(heartbeat_path) as f:
            last_beat = float(f.read().strip())
    except (OSError, ValueError):
        # Файла ещё нет (бот только запускается) — Dockerfile даёт на это
        # start-period, так что здесь не паникуем, а сообщаем "не готов".
        return 1

    age = time.time() - last_beat
    if age > STALE_AFTER_SECONDS:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
