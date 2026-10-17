# Розгортання GenaBot

## Що потрібно

- Python 3.10 або новіший (перевірено на 3.13).
- PostgreSQL (Supabase) і Redis (Upstash) — вже використовуються.
- Токен бота від @BotFather.
- Ключ Anthropic API (розпізнавання графіка), ключ OpenWeather.
- JSON-ключ сервісного акаунта Google з доступом на читання до таблиці змін.

## 1. Код і залежності

```bash
git clone https://github.com/vitasyk/GenaBot.git
cd GenaBot
python -m venv .venv
# Linux:   source .venv/bin/activate
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Налаштування

```bash
cp .env.example .env
```

Заповніть `.env`. Обов'язкові змінні:

| Змінна | Що це |
|---|---|
| `BOT_TOKEN` | токен бота |
| `ADMIN_IDS` | Telegram ID адмінів, напр. `[123456789]` |
| `ALLOWED_IDS` | ID працівників (білий список) |
| `DATABASE_URL` | `postgresql+asyncpg://...` з Supabase (pooler, порт 6543) |
| `REDIS_URL` | `rediss://...` з Upstash |
| `WEATHER_API_KEY`, `CITY_LAT`, `CITY_LON` | OpenWeather |
| `ANTHROPIC_API_KEY` | ключ Claude API |
| `SCHEDULE_SPREADSHEET_ID` | ID Google-таблиці зі змінами |

Необов'язкові: `SCHEDULE_AI_MODEL` (типово `claude-haiku-5-5`), `QUEUE_NUMBER` (типово `1.1`,
далі змінюється в адмін-панелі), `LOG_LEVEL`.

Ключ Google покладіть у `credentials/google-sheets-key.json` (або вкажіть шлях у
`GOOGLE_CREDENTIALS_PATH`). Тека `credentials/` і `.env` не потрапляють у git.

## 3. База даних (Alembic)

**Наявна база** (бот уже працював на ній) — один раз позначити поточну схему й оновити:

```bash
alembic stamp 0001
alembic upgrade head
```

Перед `upgrade` зупиніть генератори в боті («🛑 Зупинити всі»): міграція `0002` вимикає
GEN-1 і GEN-2 та додає WILSON.

**Нова порожня база:**

```bash
alembic upgrade head
```

Надалі після кожного оновлення коду: `alembic upgrade head`.

## 4. Запуск

```bash
python -m bot
```

У лозі має з'явитися `Bot started and polling...`. Бот повинен працювати в одному екземплярі:
два запущені процеси з одним токеном конфліктують.

### Linux-сервер: автозапуск через systemd

`/etc/systemd/system/genabot.service`:

```ini
[Unit]
Description=GenaBot
After=network-online.target

[Service]
WorkingDirectory=/opt/GenaBot
ExecStart=/opt/GenaBot/.venv/bin/python -m bot
Restart=always
RestartSec=5
User=genabot

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now genabot
journalctl -u genabot -f   # логи
```

### Windows

Запуск вручну: `.venv\Scripts\python -m bot`. Для автозапуску — Планувальник завдань
(тригер «При запуску комп'ютера», дія `.venv\Scripts\python.exe`, аргументи `-m bot`,
робоча тека — тека проєкту).

## 5. Оновлення

```bash
git pull
pip install -r requirements.txt
alembic upgrade head
# перезапуск: sudo systemctl restart genabot
```

## 6. Перевірка після запуску

1. `/start` у боті — з'являється меню.
2. «📉 Графік» — картинка і години для черги під нею. Порівняйте з картинкою.
3. Адмін-панель → «⚙️ Генератори» — активний лише WILSON.
4. Адмін-панель → «🔢 Черга» — стоїть потрібна черга.

## Тести

```bash
pip install -r requirements-dev.txt
pytest
```
