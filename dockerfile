# Используем официальный образ Python
FROM python:3.9-slim-buster

# Устанавливаем рабочую директорию в контейнере
WORKDIR /app

# Копируем файлы проекта в рабочую директорию
COPY . /app

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Запускаем приложение
CMD ["python", "main.py"]