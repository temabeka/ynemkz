# Ynem

Дисконт-клуб Экибастуза: Telegram Mini App (основной интерфейс) + бот + FastAPI.
Полная архитектура — в [ARCHITECTURE.md](ARCHITECTURE.md).

- **Mini App** — витрина, карта, активация скидки, профиль, кабинеты партнёра/админа
- **Бот** — онбординг, пинги партнёрам, уведомления, чеки Kaspi, Stars-платежи, фолбэки
- **API** — FastAPI, авторизация по `initData`, общий слой с ботом

## Быстрый старт

```bash
cp .env.example .env          # BOT_TOKEN, SUPABASE_*, DATABASE_URL, ADMIN_IDS, MINIAPP_URL
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Применить схему БД (psql к Supabase Postgres)
psql "$DATABASE_URL" -f migrations/001_init.sql
psql "$DATABASE_URL" -f migrations/002_miniapp.sql

python -m bot.main                      # бот (long polling)
uvicorn api.main:app --reload           # API для Mini App (отдельный терминал)
```

Mini App (dev):

```bash
cd miniapp && npm install
cp .env.example .env                    # VITE_BOT_USERNAME; VITE_API_URL пустой в dev (proxy)
npm run dev                             # vite на :5173, /api проксируется на :8000
```

Через Docker (бот + API):

```bash
docker compose up --build -d
```

## Деплой: Railway (бэк) + Vercel (фронт)

### Railway — два сервиса из одного репо

1. New Project → Deploy from GitHub repo → это создаст первый сервис (**bot**).
2. В сервисе: Settings → Config-as-code → путь `railway.bot.json`.
3. `+ New` → GitHub Repo → тот же репозиторий → второй сервис (**api**),
   Config-as-code → `railway.api.json`. У api появится публичный домен
   (Settings → Networking → Generate Domain) — это адрес для `VITE_API_URL`.
4. Variables (можно на уровне Environment — общие для обоих сервисов):
   `BOT_TOKEN, SUPABASE_URL, SUPABASE_KEY, DATABASE_URL, ADMIN_IDS, KASPI_PHONE,`
   `SUBSCRIPTION_PRICE, SUBSCRIPTION_PRICE_STARS, STORAGE_BUCKET, MINIAPP_URL`.
   `DATABASE_URL` — pooled-строка Supabase (Session mode, порт 5432).
   `PORT` для api Railway задаёт сам.

Бот — worker без домена (long polling), домен нужен только api.
Хелсчек api: `/health` (уже в `railway.api.json`).

### Vercel — Mini App

1. Import репозитория → **Root Directory: `miniapp`** (Framework: Vite определится сам).
2. Environment Variables:
   - `VITE_API_URL` = `https://<api>.up.railway.app` (домен api из Railway, без слэша)
   - `VITE_BOT_USERNAME` = username бота без @
3. Deploy → прод-домен (например `https://ynemkz.vercel.app`) →
   вписать его в `MINIAPP_URL` на Railway (это CORS и web_app-кнопки) → redeploy api.

Роутинг — HashRouter, rewrites не нужны; `miniapp/vercel.json` добавляет кэш ассетов.

### Финальная привязка

1. Миграции: `psql "$DATABASE_URL" -f migrations/001_init.sql -f migrations/002_miniapp.sql`.
2. Supabase Storage: создать **public** bucket `receipts`.
3. BotFather: `/newapp` → выбрать бота → короткое имя **`app`** (наклейки ведут на
   `t.me/<bot>/app?startapp=p_<id>`), Web App URL = домен Vercel.
   Там же: Menu Button → URL Mini App.
4. Проверка: `curl https://<api>.up.railway.app/health` → `{"ok":true}`; открыть Mini App
   из меню бота; `/admin` в боте.

## Структура

```
bot/
├─ main.py            entrypoint, Dispatcher, long polling
├─ config.py          env-настройки (pydantic-settings)
├─ db.py              asyncpg pool + supabase client (Storage)
├─ keyboards.py       reply/inline клавиатуры
├─ texts.py           i18n-словарь (ru/kk)
├─ middlewares/
│  └─ auth.py         роль в контекст, отсечка забаненных
├─ handlers/
│  ├─ buyer.py        /start + deep links, подписка, активация
│  ├─ partner.py      ввод кода, статистика, пауза
│  └─ admin.py        партнёры, чеки, рассылка
├─ services/
│  ├─ qr.py           коды, QR-наклейки, знак дня
│  ├─ redemption.py   выдача/погашение активаций (анти-фрод)
│  ├─ payments.py     подписки, подтверждение чеков
│  ├─ storage.py      загрузка чеков в Supabase Storage
│  └─ broadcast.py    рассылки батчами
└─ scheduler.py       APScheduler: expire подписок/кодов, знак дня
migrations/001_init.sql
```

## Роли и доступ

Авторизация по `telegram_id`, паролей нет. `ADMIN_IDS` из env → всегда admin.

**Админ:** `/admin` — меню, `/add_partner <tg_id> <название>`, `/set_location <id> <lat> <lng>`
(пин на карте), фото с подписью `/logo <id>` (логотип), `/qr <id>` (наклейка на кассу),
`/receipts` (очередь чеков ✅/❌), `/refund <sub_id>`
(возврат Stars), `/subs`, `/stats`, `/broadcast <сегмент> <текст>`, `/ban` / `/unban`.

**Партнёр:** `/partner` — меню, `/code` (фолбэк-ввод кода), `/stats`, `/pause`.

## Механика активации (вариант C)

Клиент сканирует QR-наклейку на кассе → `t.me/bot?start=p_<id>` → бот показывает экран
активации с **живыми тикающими часами** (обновление каждые 10 с, гаснет через 5 мин),
знаком дня и именем клиента; визит записывается сразу, партнёру летит пинг.
Подписчику — повышенная скидка везде; без подписки — базовая скидка партнёра,
если он её даёт (иначе — предложение оформить подписку). Между активациями у одного
партнёра — пауза 10 минут; в день можно несколько визитов.

## Структура (Фаза 2)

```
api/                  FastAPI: auth.py (initData HMAC), routes/{catalog,me,partner,admin}
miniapp/src/pages/    Home, Partner, Map (Leaflet), Activate (тикающие часы),
                      Profile (Stars/Kaspi), PartnerCabinet, AdminReceipts
migrations/002_miniapp.sql   lat/lng/logo_url, payment_method/tg_charge_id, discount
```

Проверка на staging (нужен живой Postgres): активация → анти-фрод лимит,
Stars-платёж → мгновенная подписка, `redemptions.discount` фиксируется на момент визита.
```
