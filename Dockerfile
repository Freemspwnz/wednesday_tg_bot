# syntax=docker/dockerfile:1

FROM python:3.11-slim

# --- Создаём пользователя ---
RUN adduser --disabled-password --gecos "" app

# --- Рабочая директория ---
WORKDIR /app

# --- Копируем только зависимости сначала (кэш) ---
COPY requirements.txt .

# --- Устанавливаем зависимости ---
RUN pip install --no-cache-dir -r requirements.txt

# --- Копируем весь проект ---
COPY . .

# --- Копируем .env если нужно ---
# COPY .env .   # раскомментируй, если хочешь, чтобы файл был внутри контейнера

# --- Меняем владельца ---
RUN chown -R app:app /app

# --- Запуск от пользователя app ---
USER app

# --- Команда по умолчанию ---
CMD ["python3", "main.py"]
