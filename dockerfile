# Этап 1: Установка зависимостей
FROM python:3.10-slim as builder

# Системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Копируем и устанавливаем зависимости
WORKDIR /app
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# ---
# Этап 2: Финальный образ
FROM python:3.10-slim

# Безопасность
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Создаем пользователя
RUN useradd -m botuser && \
    mkdir -p /app && \
    chown botuser:botuser /app

WORKDIR /app
USER botuser

# Копируем зависимости из builder
COPY --from=builder --chown=botuser /root/.local /home/botuser/.local
COPY --chown=botuser . .

# Точка входа
CMD ["python", "bot.py"]

#RUN useradd -m botuser
#USER botuser
