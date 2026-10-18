# Розгортання GenaBot (Docker)

У продакшені бот працює в одному Docker-контейнері. База даних — **Supabase Postgres**
(`DATABASE_URL`), Redis — **Upstash** (`REDIS_URL`). Сервіси `db` і `redis` у
`docker-compose.yml` потрібні лише для локального тестування (профіль `local`) і в продакшені
не запускаються.

Схема бази змінюється тільки через Alembic (`alembic/versions`).

## 1. Підготовка сервера

Потрібні Docker і Docker Compose v2 (команда `docker compose`):
```bash
sudo apt update
sudo apt install docker.io docker-compose-v2 -y
```

## 2. Налаштування

```bash
git clone <URL_РЕПОЗИТОРІЮ>
cd GenaBot
cp .env.example .env
```
Заповніть `.env`: `BOT_TOKEN`, `ADMIN_IDS`, `DATABASE_URL` (Supabase pooler),
`REDIS_URL` (Upstash), ключі погоди та Google Sheets. Файл `google-sheets-key.json`
покладіть у папку `credentials/`.

## 3. Перше розгортання на продакшен-базі (один раз)

Таблиці в Supabase вже існують, а в `alembic_version` записана стара ревізія, якої немає в
репозиторії. Спочатку зробіть резервну копію бази (Supabase Dashboard → Database → Backups
або `pg_dump`), потім:

```bash
docker compose build
# позначити поточну схему як базову (0001), не змінюючи таблиць
docker compose run --rm bot alembic stamp --purge 0001
# застосувати нові міграції (RLS, керування генераторами)
docker compose run --rm bot alembic upgrade head
docker compose up -d
```

`stamp --purge` потрібен лише один раз. Без нього `alembic upgrade head` завершиться помилкою
`Can't locate revision identified by 'f3bd722779d8'`.

## 4. Оновлення

```bash
git pull
./deploy.sh
```
`deploy.sh` збирає образ, застосовує міграції (`alembic upgrade head`) в окремому контейнері і
лише після цього перезапускає бота. Якщо міграція впала, скрипт зупиняється і старий бот
продовжує працювати.

## 5. Локальний тест (своя база і Redis)

Створіть `.env.local` (він у `.gitignore`) — копію `.env` з тестовим токеном бота і
локальними адресами:
```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/genabot
REDIS_URL=redis://redis:6379/0
```
Запуск:
```bash
export BOT_ENV_FILE=.env.local
docker compose --profile local up -d --build db redis
docker compose run --rm bot alembic upgrade head
docker compose --profile local up --build
```
Видалити локальні дані: `docker compose --profile local down -v`.

## 6. Корисні команди

- Логи: `docker compose logs -f bot`
- Поточна ревізія бази: `docker compose run --rm bot alembic current`
- Зупинка: `docker compose down`
