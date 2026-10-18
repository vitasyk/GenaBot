# GenaBot: старт для ШІ-агента

Прочитайте цей файл перед будь-якою роботою з репозиторієм. Стандарти коду описані в
[`.agent/AGENT.MD`](.agent/AGENT.MD), розгортання для людини в [`DEPLOY.md`](DEPLOY.md).

**Відповідайте власнику українською.** Пріоритет: слова власника > цей файл > `.agent/AGENT.MD` > скіли > ponytail.

## 1. Що це

Це Telegram-бот (aiogram 3, Python 3.11) для команди, яка обслуговує дизельні генератори.
Він вміє:
- запускати і зупиняти генератори;
- вести склад пального;
- керувати сесіями заправки з нагадуваннями;
- розпізнавати графік відключень (HOE, скріншот через Claude API або ручний ввід);
- показувати SOS-інструкції з фото і PDF;
- брати чергових із Google Sheets.

| Компонент | Прод | Локальний тест |
|---|---|---|
| Бот | `@gena_diesel_bot`, сервер `/opt/GenaBot`, Docker | `@powershell_status_bot`, Docker на ПК |
| БД | Supabase Postgres (pooler) | `db` (postgres:15) з `docker compose --profile local` |
| FSM / налаштування | Upstash Redis | `redis` з профілю `local` |
| env-файл | `.env` (лише на сервері) | `.env.local` (у `.gitignore`) |

Гілки:
- `master` — це прод: сервер робить `git pull` саме з нього.
- `main` — старий знімок, з ним не працюйте.
- Фічі робіть у `feat/...` або `fix/...`, потім зливайте в `master`.

## 2. Перші кроки в новій сесії

1. `git fetch && git status`: переконайтесь, що ви на гілці від `origin/master`.
2. Перевірте, що підключено (розділ 3): скіли, плагін ponytail, Supabase MCP.
3. Перевірте, що є `.env.local` з **тестовим** токеном. Якщо файлу немає, попросіть його у власника.
4. Перед змінами прогоніть тести (розділ 5), щоб знати вихідний стан.

## 3. Скіли, плагіни, MCP

### Скіли проєкту (`.claude/skills/`)
Claude Code підхоплює їх сам. Інші агенти мають прочитати потрібний `SKILL.md` перед роботою.

| Завдання | Завантажити |
|---|---|
| Хендлери, роутери, FSM, клавіатури, middleware, планувальник | `aiogram3-bot` |
| Моделі, репозиторії, транзакції, міграції Alembic | `sqlalchemy-async-alembic` |
| Тести | `pytest-asyncio-bot` |
| Баг або тест падає: спершу причина, потім фікс | `systematic-debugging` |
| Нова логіка або фікс бага (спочатку тест, що падає) | `test-driven-development` |
| Нова фіча: ідея → план → виконання | `brainstorming`, `writing-plans`, `executing-plans` |
| Індекси, швидкість запитів, схема, RLS | `postgres-best-practices` |
| Доступи (`ADMIN_IDS` / `ALLOWED_IDS`), секрети | `api-security-best-practices` |

### Плагіни (`.claude/settings.json`)
- **ponytail** — найменша повна зміна. Команди: `/ponytail:ponytail-review` перед комітом,
  `/ponytail:ponytail-audit` для аудиту, `/ponytail:ponytail-debt`. Власник просить працювати через ponytail.
- **andrej-karpathy-skills** — той самий підхід, тож обидва вантажити не обов'язково.
- Якщо плагінів немає: `/plugin` → маркетплейси вже прописані в `.claude/settings.json` → увімкнути → `/reload-plugins`.
- Вбудовані команди: `/code-review`, `/simplify`, `/security-review` (перед релізом).

### Supabase MCP (`.mcp.json`)
- Це прод-база, підключена **тільки на читання** (`read_only=true`).
- Перший запуск: `/mcp` → `supabase` → Authenticate (логін власника в браузері).
- Можна: `list_tables`, `execute_sql` (SELECT), `get_advisors`, `query_logs`.
- **Нічого не змінюйте в проді через MCP.** Схема змінюється тільки міграцією Alembic,
  яку власник сам застосовує на сервері.

## 4. Секрети і токени: червоні лінії

- **Ніколи не запускайте локального бота з прод-токеном.** Два процеси на одному токені
  ламають прод. Перед запуском перевірте, якому боту належить токен:
  ```bash
  docker compose run --rm bot python -c "import asyncio;from aiogram import Bot;from bot.config import config;b=Bot(config.BOT_TOKEN.get_secret_value());print(asyncio.run(b.get_me()).username)"
  ```
  Має бути `powershell_status_bot`.
- Не виводьте значення секретів. У звітах про env показуйте лише назви ключів і стан (є / нема / формат).
- Секрети, які колись потрапили в історію git, власник свідомо лишив як є. Не ротуйте їх без запиту.
- `credentials/google-sheets-key.json` у git не потрапляє. Сервісний акаунт:
  `genabot-reader@outline-a48.iam.gserviceaccount.com`, таблиця має бути відкрита для нього на читання.
- Повний список змінних дивіться в `bot/config.py` і `.env.example`.

## 5. Тестування (тільки в Docker)

Python на ПК власника 3.13, а закріплені залежності під нього не збираються. Тому все запускайте в образі
(Windows + Git Bash: `MSYS_NO_PATHCONV=1` і `$(pwd -W)` обов'язкові).

```bash
# один раз або після зміни requirements: образ бота + dev-залежності
docker compose build bot
printf 'FROM genabot-bot\nRUN pip install --no-cache-dir pytest pytest-asyncio ruff\n' | docker build -t genabot:dev -

# юніт-тести і лінтер
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W):/app" -w /app genabot:dev pytest -q
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W):/app" -w /app genabot:dev ruff check .
```

Інтеграційні тести працюють на локальному Postgres. Без змінної `INTEGRATION_DATABASE_URL` вони пропускаються.
```bash
export BOT_ENV_FILE=.env.local
docker compose --profile local up -d db redis
docker compose run --rm bot alembic upgrade head
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W):/app" -w /app --network genabot_default \
  -e INTEGRATION_DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/genabot genabot:dev pytest -q
```

Ручна перевірка на тестовому боті:
```bash
export BOT_ENV_FILE=.env.local
docker compose --profile local up -d --build
docker compose logs -f bot
docker compose --profile local down        # зупинити; додайте -v, щоб стерти локальні дані
```
Попросіть власника «проклацати» сценарій у `@powershell_status_bot`, потім перевірте логи.
Після перевірки зупиніть тестового бота.

Правила тестів:
- новий баг починається з тесту, що його відтворює;
- `pytest.ini` уже містить `asyncio_mode = auto` і `pythonpath = .`;
- фейки Redis і env лежать у `tests/conftest.py`.

## 6. Коміт, пуш, деплой

- Git-ідентичність глобально не налаштована, тому комітьте так:
  `git -c user.name=vitasyk -c user.email=lifelinescret@gmail.com commit ...`
- Формат повідомлення: `[feat] ...`, `[fix] ...`, `[chore] ...` (англійською). Останній рядок:
  `Co-Authored-By: <модель> <noreply@anthropic.com>`.
- **Пуште лише тоді, коли власник просить.** Порядок: тести зелені → ручна перевірка на тестовому боті →
  власник каже «пуш» → `git push origin <гілка>` і злиття в `master`.
- Змінили модель — додайте міграцію `alembic/versions/000N_*.py` (нумерація по порядку, `down_revision`
  вказує на попередню) і закомітьте її разом з кодом.
- Деплой робить власник. Дайте йому команди:
  ```bash
  cd /opt/GenaBot
  git pull --ff-only origin master
  ./deploy.sh                 # build → alembic upgrade head → up -d
  docker compose logs -f bot  # перевірити старт
  ```
  Якщо змінилися змінні env, нагадайте додати їх у `/opt/GenaBot/.env` до деплою.

## 7. Підводні камені цього коду

- **Час.** Контейнер працює в UTC. Для бізнес-часу використовуйте `bot.utils.clock.now_local()`
  (`config.TIMEZONE`, Київ).
  - `refuel_sessions` і `schedule_entries` зберігають naive київський час.
  - `generators` і логи зберігають naive UTC.
- **Supabase pooler.** Без `statement_cache_size=0` asyncpg падає. Це вже налаштовано в `bot/database` і `alembic/env.py`.
- **JSON-колонки** (`Generator.instructions_media`). Список треба присвоювати заново, зміна на місці не збережеться.
- **Конкурентність.** Сесії переходять у новий стан умовним `UPDATE` з фільтром по статусу
  (`only_from=OPEN_STATUSES`), паливо списується через `with_for_update()`. Ці перевірки не прибирайте.
- **Блокуючі бібліотеки.** gspread обгорнутий у `asyncio.to_thread`.
- **Графік через ШІ.** `bot/services/schedule_recognizer.py` (Claude API, structured output).
  Модель задає `SCHEDULE_AI_MODEL`, ключ `ANTHROPIC_API_KEY`. Без ключа лишається ручний ввід.
- **Налаштування, які адмін змінює в боті** (`QUEUE_NUMBER`, `RESTRICT_ACCESS`, `NOTIFY_WORKERS`,
  `FUEL_THRESHOLD_CANS`), зберігаються в Redis (`bot/scheduler.py`, `RUNTIME_SETTING_KEYS`) і мають пріоритет над `.env`.
- **Доступ.** `AccessMiddleware` пропускає `ADMIN_IDS` і `ALLOWED_IDS`. Інші бачать лише `/start`, `/menu`, `/help`.
  Генераторами керують усі дозволені користувачі, адмін-панель доступна тільки `ADMIN_IDS`.
- **Генератори** зберігаються в БД з полем `is_active`. Адмін додає, вмикає і вимикає їх у боті.
  Зараз активний лише `GEN-2 (003) WILSON`.
- **Присадка (`bot/services/antigel.py`).** `fuel_since_antigel` — це літри палива **без присадки, які ще в баку**:
  - при заправці додаються;
  - при роботі генератора зменшуються пропорційно до спаленого;
  - коли підтвердили «присадку додано», обнуляються.

  Нагадування спрацьовує лише коли:
  - мінімум у прогнозі на 3 доби ≤ `FUEL_CFPP_C` + 5°C;
  - паливо без присадки становить ≥20% вмісту бака.
- **`file_id` Telegram прив'язаний до токена.** Вкладення SOS, додані в тестовому боті, у проді не працюють.
