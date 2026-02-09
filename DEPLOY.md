# Інструкція з розгортання GenaBot на VPS (Docker)

Ця інструкція допоможе вам розгорнути бота на сервері разом із базою даних PostgreSQL та Redis за допомогою Docker Compose.

## 1. Підготовка сервера

Переконайтеся, що на вашому VPS встановлено **Docker** та **Docker Compose**.

Якщо ні, встановіть їх:
```bash
sudo apt update
sudo apt install docker.io docker-compose -y
```

## 2. Копіювання проекту

Клонуйте репозиторій або скопіюйте файли проекту на сервер:
```bash
git clone <URL_ВАШОГО_РЕПОЗИТОРІЮ>
cd GenaBot
```

## 3. Налаштування

1.  **Створіть файл `.env`** (на основі `.env.example`):
    ```bash
    cp .env.example .env
    ```
    Відредагуйте його:
    -   `BOT_TOKEN`: Токен вашого бота.
    -   `ADMIN_IDS`: Список ID адміністраторів.
    -   `DATABASE_URL`: `postgresql+asyncpg://postgres:postgres@db:5432/genabot` (для Docker).
    -   `REDIS_URL`: `redis://redis:6379/0` (для Docker).
    -   Інші налаштування (Weather API, Google Sheets ID тощо).

2.  **Зайдіть у папку `credentials`** та додайте туди файл `google-sheets-key.json`.

## 4. Запуск

Запустіть всі сервіси в фоновому режимі:
```bash
docker-compose up -d --build
```

Бот автоматично створить необхідні таблиці в базі даних при першому запуску (через `alembic` або `init.sql`).

## 5. Міграція бази даних (Перенесення даних)

Якщо у вас є дані в старій базі (наприклад, на Supabase) і ви хочете перенести їх у Docker на сервері:

1.  Переконайтеся, що в `.env` параметр `DATABASE_URL` веде на **стару** базу (Source).
2.  Запустіть скрипт міграції:
    ```bash
    # Зовні докера (якщо встановлені залежності):
    python migrate_db.py "postgresql+asyncpg://postgres:postgres@localhost:5432/genabot"

    # АБО всередині контейнера:
    docker exec -it gena_bot python migrate_db.py "postgresql+asyncpg://postgres:postgres@db:5432/genabot"
    ```
3. Після успішної міграції змініть `DATABASE_URL` у `.env` назад на адресу Docker-бази (`db:5432`) та перезапустіть бота:
    ```bash
    docker-compose restart bot
    ```

## 6. Корисні команди

-   **Перегляд логів**: `docker logs -f gena_bot`
-   **Зупинка**: `docker-compose down`
-   **Оновлення**: `git pull && docker-compose up -d --build`
