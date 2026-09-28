FROM python:3.12-slim

# Чистый Python-проект без шагов компиляции — многостадийная сборка не нужна
# (см. self-hosted-deploy: она нужна только когда есть отдельный build-этап).

WORKDIR /app

# Слой зависимостей отдельно от кода — пересборка при правке main.py
# не будет каждый раз переустанавливать aiogram заново.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Файлы БД живут в volume, а не в слое образа — см. docker-compose.yml.
ENV DATA_DIR=/app/data
RUN mkdir -p /app/data

# Непривилегированный пользователь: бот получает только исходящие HTTPS-запросы
# к api.telegram.org, работать от root ему незачем.
RUN useradd --create-home --uid 1000 botuser \
    && chown -R botuser:botuser /app
USER botuser

# Бот сам ничего не слушает (long polling наружу), поэтому здоровье меряем по
# heartbeat-файлу, который main.py обновляет раз в 30 сек — см. healthcheck.py.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python3 healthcheck.py || exit 1

CMD ["python", "main.py"]
