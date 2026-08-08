# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Что это

Ynem — дисконт-клуб Экибастуза: Telegram Mini App (основной интерфейс) + aiogram-бот + FastAPI. Полная архитектура, схема БД, флоу и trade-offs — в [ARCHITECTURE.md](ARCHITECTURE.md); при изменении механик сверяйся с ним (код ссылается на его разделы в докстрингах).

Язык проекта — русский: комментарии, докстринги, коммиты, тексты пользователю.

## Команды

```bash
# Бэкенд (Python 3.12, venv в .venv)
source .venv/bin/activate
pip install -r requirements.txt
python -m bot.main                    # бот (long polling)
uvicorn api.main:app --reload         # API для Mini App (порт 8000)

# Миграции (обычный psql к Supabase Postgres, без инструмента миграций).
# Применяются по порядку номеров; каждая идемпотентна (повторный прогон не падает).
psql "$DATABASE_URL" -f migrations/001_init.sql   # ... и далее 002–009
psql "$DATABASE_URL" -f migrations/seed_demo_partners.sql   # демо-партнёры (опционально)

# Mini App (React + Vite + TS, в miniapp/)
cd miniapp
npm run dev        # vite на :5173, /api проксируется на localhost:8000
npm run build      # tsc -b && vite build
npm run lint       # oxlint
```

Тестов в проекте нет. Docker: `docker compose up --build -d` (бот + API).

Конфиг — `.env` (см. `.env.example`), читается через pydantic-settings в `bot/config.py`. Для запуска нужны минимум `BOT_TOKEN`, `SUPABASE_URL`, `SUPABASE_KEY`, `DATABASE_URL`.

## Архитектура: главное

**Один репозиторий — три компонента, два процесса.** Бот (`bot/`) и API (`api/`) — отдельные процессы, но API импортирует общий слой из пакета бота: `bot/db.py` (asyncpg pool + supabase client), `bot/config.py`, `bot/services/` (бизнес-логика). Бизнес-правила пишутся один раз в `bot/services/` и вызываются и хэндлерами бота, и роутами API — например, активация скидки это `bot/services/redemption.py`, используемый из `bot/handlers/buyer.py` и `api/routes/me.py`. Не дублируй логику в `api/`.

**Разделение бот / Mini App:** Mini App — витрина, карта, активация, профиль, кабинеты партнёра и админа. Бот — то, что нельзя или не нужно делать в вебе: онбординг, пинги партнёрам в реальном времени, уведомления, приём фото чеков Kaspi, Stars-платежи (`pre_checkout_query`/`successful_payment`), рассылки, фолбэк-команды. Пинги и инвойсы из API отправляются через aiogram `Bot` без polling.

**Авторизация.** Паролей нет, личность = telegram_id. Mini App шлёт заголовок `Authorization: tma <initData>`; `api/auth.py` валидирует HMAC-подпись initData (ключ = HMAC-SHA256("WebAppData", bot_token)), кэширует 5 минут, отклоняет initData старше часа. Роль берётся из `users.role`, но id из `ADMIN_IDS` (env) — всегда admin. Доступ к роутам — через `Depends(require_role("partner", "admin"))`. В боте то же самое делает `bot/middlewares/auth.py` (кладёт роль в контекст, отсекает забаненных).

**Механика активации (вариант C, основная):** QR-наклейка на кассе → deep link `t.me/<bot>/app?startapp=p_<id>` (Mini App) или `t.me/<bot>?start=p_<id>` (фолбэк в боте) → `redemption.issue(auto_use=True)` записывает визит сразу → экран с тикающими часами по серверному времени (TTL 5 мин) + пинг партнёру в бот. Анти-фрод: 1 активация у партнёра в день, без подписки скидки нет (API отвечает 402), незарегистрированным — 403 → онбординг в боте. Вариант D: кассир сканирует персональный QR клиента в кабинете партнёра (`users.qr_token`, генерируется лениво в `GET /api/me`) — визит пишется сразу, клиенту сканировать ничего не нужно. Фолбэк (вариант A): 6-символьный код с TTL 30 мин, гасится атомарным UPDATE (кассир вводит код в Mini App).

**Роли и кассиры.** Роли: buyer / partner / admin (`users.role`). У партнёра-владельца могут быть сотрудники-кассиры (`partner_staff`): владелец приглашает по одноразовой ссылке `t.me/<bot>?start=staff_<token>` (TTL 24 ч) или по @username; кассир получает роль partner, доступ к кабинету своего заведения и пинги об активациях, но без прав владельца (роуты различают по флагу владения в `api/routes/partner.py`). Правки карточки заведения партнёром проходят модерацию админа (`006_partner_edits.sql`).

**Тексты пользователю** — только через i18n-словарь `bot/texts.py`: `t("key", lang, **kwargs)`. Русский заполнен, казахский добавляется ключами в `TEXTS["kk"]`. Не хардкодь строки в хэндлерах.

**Фоновые задачи** — `bot/scheduler.py` (APScheduler в процессе бота): протухание подписок и кодов, утренняя рассылка знака дня партнёрам.

**Mini App** (`miniapp/`): React 18 (требование `@telegram-apps/telegram-ui`) + `@telegram-apps/sdk-react`, роутинг — HashRouter (SPA на статике), карта — Leaflet/OSM без API-ключей. Все запросы через `src/api.ts`; в dev `VITE_API_URL` пустой — работает vite-прокси на :8000.

## Деплой

Railway — два сервиса из одного репо (`railway.bot.json` — worker без домена, `railway.api.json` — с доменом и хелсчеком `/health`). Vercel — Mini App с Root Directory `miniapp`. `MINIAPP_URL` в env бэка — это CORS и web_app-кнопки; при смене домена фронта нужен redeploy API. Пошаговая инструкция — в README.md.

## Нагрузка

Город ~120 тыс. населения; сотни–тысячи пользователей. Масштабирование сознательно не проектируем: long polling вместо webhook, один процесс бота, Supabase free tier. Не усложняй инфраструктуру без запроса.
