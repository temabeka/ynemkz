"""Покупатель: /start + онбординг, подписка, активация (раздел 3.6).

Один обработчик /start разбирает deep links:
  p_<id>  → активация у партнёра (вариант C)
  ref_<id> → привязка реферала
"""
from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timezone

import asyncpg
from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import db
from bot.config import settings
from bot.keyboards import (
    consent_kb,
    help_kb,
    main_menu_kb,
    pay_kb,
    profile_kb,
    receipt_decision_kb,
)
from bot.services import partners, payments, qr, redemption, storage
from bot.texts import t

router = Router(name="buyer")

SCREEN_SECONDS = 300  # экран активации живёт 5 минут (раздел 3.2)
TICK_SECONDS = 10     # период обновления «тикающих часов»

# Ссылки на фоновые задачи: без них garbage collector может убить task на лету.
_bg_tasks: set[asyncio.Task] = set()


def _spawn(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return task


class Onboarding(StatesGroup):
    consent = State()


class HelpContact(StatesGroup):
    admin_msg = State()   # «Написать админу»
    complaint = State()   # «Пожаловаться на заведение»


# --- /start + deep links --------------------------------------------------------

@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext) -> None:
    lang = settings.default_lang
    payload = command.args or ""

    user = await db.fetchrow("SELECT * FROM users WHERE id = $1", message.from_user.id)

    # Реферал: сохраняем в FSM, привяжем после регистрации.
    # Битый/самореферальный линк не должен блокировать регистрацию (FK users).
    if payload.startswith("ref_") and user is None:
        ref_id = _safe_int(payload[4:])
        if (
            ref_id
            and ref_id != message.from_user.id
            and await db.fetchval("SELECT 1 FROM users WHERE id = $1", ref_id)
        ):
            await state.update_data(referrer_id=ref_id)

    if user is None:
        # Незарегистрирован → онбординг; deep link продолжим после.
        await state.update_data(pending_payload=payload)
        await state.set_state(Onboarding.consent)
        await message.answer(t("welcome", lang))
        await message.answer(t("ask_consent", lang), reply_markup=consent_kb(lang))
        return

    await state.clear()  # /start сбрасывает подвисшие состояния (помощь и т.п.)

    # Зарегистрирован: если пришёл по p_<id> — сразу экран активации.
    if payload.startswith("p_"):
        await _activate(message, dict(user), _safe_int(payload[2:]))
        return

    # Инвайт-ссылка кассира (staff_<token>) — становится кассиром сразу.
    if payload.startswith("staff_"):
        await _join_staff(message, dict(user), payload[6:])
        return

    await message.answer(t("menu_hint", user["lang"]), reply_markup=main_menu_kb(user["lang"]))


async def _join_staff(message: Message, user: dict, token: str) -> None:
    """Принять приглашение кассира по одноразовому токену (миграция 005)."""
    lang = user["lang"]
    try:
        partner = await partners.use_invite(token, user["id"])
    except partners.StaffError as e:
        await message.answer(str(e))
        return

    await message.answer(t("staff_joined", lang, partner=partner["name"]))
    # Владельцу — уведомление, что кассир присоединился.
    if partner["user_id"]:
        with contextlib.suppress(Exception):
            await message.bot.send_message(
                partner["user_id"],
                t("staff_joined_owner", lang,
                  name=user["full_name"] or user["id"], partner=partner["name"]),
            )


@router.message(Onboarding.consent, F.text)
async def onboarding_consent(message: Message, state: FSMContext) -> None:
    """Один тап «Продолжить» = акцепт условий → сразу регистрация.

    Телефон не собираем: Kaspi не показывает номер плательщика, сверка чеков
    идёт по сумме/времени/имени — номер в ней не участвует.
    """
    lang = settings.default_lang
    if message.text != t("btn_consent", lang):
        # Без согласия дальше нельзя (раздел 3.6).
        await message.answer(t("ask_consent", lang), reply_markup=consent_kb(lang))
        return

    data = await state.get_data()
    # Ранняя очистка: даже при ошибке ниже пользователь не застрянет в онбординге.
    await state.clear()

    async def _register(referrer_id: int | None) -> None:
        await db.execute(
            """
            INSERT INTO users (id, username, full_name, referrer_id, lang)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (id) DO NOTHING
            """,
            message.from_user.id,
            message.from_user.username,
            message.from_user.full_name,
            referrer_id,
            lang,
        )

    try:
        await _register(data.get("referrer_id"))
    except asyncpg.ForeignKeyViolationError:
        # Реферер исчез между /start и согласием — регистрируем без него.
        await _register(None)
    await message.answer(t("registered", lang), reply_markup=main_menu_kb(lang))

    # Продолжаем отложенный deep link: активация или приглашение кассира.
    payload = data.get("pending_payload") or ""
    if payload.startswith(("p_", "staff_")):
        user = await db.fetchrow("SELECT * FROM users WHERE id = $1", message.from_user.id)
        if payload.startswith("p_"):
            await _activate(message, dict(user), _safe_int(payload[2:]))
        else:
            await _join_staff(message, dict(user), payload[6:])


# --- Экран активации (вариант C) ------------------------------------------------

async def _activate(message: Message, user: dict, partner_id: int | None) -> None:
    """Фолбэк-активация в боте (основной флоу — в Mini App через startapp)."""
    lang = user["lang"]
    if not partner_id:
        await message.answer(t("error", lang))
        return

    try:
        # Общая бизнес-логика с API (правила скидки, анти-фрод, запись визита).
        result = await redemption.activate(user["id"], partner_id)
    except redemption.NeedSubscription as e:
        await message.answer(
            t("need_subscription", lang,
              partner=e.partner_name, discount=e.discount,
              price=settings.subscription_price)
        )
        return
    except redemption.RedeemError as e:
        await message.answer(str(e))
        return

    partner, discount = result["partner"], result["discount"]

    def render(now: datetime) -> str:
        return t(
            "activation_screen", lang,
            partner=partner["name"],
            discount=discount,
            name=user["full_name"] or "",
            date=now.strftime("%d.%m.%Y"),
            sign=qr.daily_sign(),
            clock=now.strftime("%H:%M:%S"),
        )

    now = datetime.now(timezone.utc)
    screen = await message.answer(render(now))
    # Живые тикающие часы (анти-скриншот) + авто-истечение через 5 минут.
    _spawn(_tick_screen(screen, render, lang))

    # Пинг владельцу и кассирам в реальном времени (раздел 3.2).
    ping_text = t("partner_ping", lang, name=user["full_name"] or "Клиент",
                  discount=discount, time=now.strftime("%H:%M"))
    for chat_id in await partners.ping_recipients(partner["id"]):
        with contextlib.suppress(Exception):
            await message.bot.send_message(chat_id, ping_text)


async def _tick_screen(screen: Message, render, lang: str) -> None:
    """Обновляет часы на экране активации каждые TICK_SECONDS, затем гасит экран."""
    for _ in range(SCREEN_SECONDS // TICK_SECONDS - 1):
        await asyncio.sleep(TICK_SECONDS)
        with contextlib.suppress(Exception):
            await screen.edit_text(render(datetime.now(timezone.utc)))
    await asyncio.sleep(TICK_SECONDS)
    with contextlib.suppress(Exception):
        await screen.edit_text(t("activation_expired", lang))


# --- Главное меню ---------------------------------------------------------------

@router.message(F.text == t("btn_all"))
async def show_catalog(message: Message) -> None:
    """Каталог текстом — MVP без Mini App (раздел 4.5, фазировка п.1)."""
    lang = settings.default_lang
    rows = await db.fetch(
        """
        SELECT name, category, address, discount_free, discount_premium, work_hours
        FROM partners WHERE is_active AND NOT is_paused
        ORDER BY category NULLS LAST, name
        """
    )
    if not rows:
        await message.answer(t("catalog_empty", lang))
        return
    lines: list[str] = ["🏷 <b>Все скидки</b>:\n"]
    current_cat = None
    for r in rows:
        cat = r["category"] or "Другое"
        if cat != current_cat:
            current_cat = cat
            lines.append(f"\n<b>{cat.capitalize()}</b>")
        hours = f" · {r['work_hours']}" if r["work_hours"] else ""
        free = f" (без подписки {r['discount_free']}%)" if r["discount_free"] else ""
        lines.append(f"• {r['name']} — {r['discount_premium']}%{free} · 📍 {r['address'] or '—'}{hours}")
    from bot.keyboards import miniapp_kb
    await message.answer("\n".join(lines), reply_markup=miniapp_kb("📱 Каталог и карта в приложении"))


@router.message(F.text == t("btn_sub"))
async def show_subscription(message: Message, db_user: dict | None) -> None:
    lang = settings.default_lang
    sub = await payments.active_subscription(message.from_user.id)
    if sub:
        days = (sub["expires_at"] - datetime.now(timezone.utc)).days
        visits, saved = await payments.savings(message.from_user.id)
        text = (
            t("sub_active", lang, days=max(days, 0)) + "\n" +
            t("sub_saved", lang, amount=saved, visits=visits)
        )
        history = await _visit_history(message.from_user.id)
        if history:
            text += "\n\n" + t("sub_visits", lang) + "\n" + history
        # Продление доступно до истечения — дни стекуются (раздел 3.1).
        text += "\n\n" + t("sub_renew_hint", lang,
                           price=settings.subscription_price, phone=settings.kaspi_phone)
        await message.answer(text, reply_markup=profile_kb())
    elif await payments.has_pending(message.from_user.id):
        await message.answer(t("sub_pending", lang), reply_markup=profile_kb())
    else:
        await message.answer(
            t("sub_none", lang) + "\n\n" +
            t("pay_prompt", lang, price=settings.subscription_price, phone=settings.kaspi_phone),
            reply_markup=pay_kb(lang),
        )


@router.callback_query(F.data == "paid:hint")
async def paid_hint(call: CallbackQuery) -> None:
    """Кнопка «Я оплатил» — просим прислать скрин чека."""
    lang = settings.default_lang
    if await payments.has_pending(call.from_user.id):
        await call.answer(t("pay_duplicate", lang), show_alert=True)
        return
    await call.message.answer(t("paid_hint", lang))
    await call.answer()


async def _visit_history(user_id: int, limit: int = 5) -> str:
    """Последние визиты: заведение, дата, % (зафиксированный на момент визита)."""
    rows = await db.fetch(
        """
        SELECT p.name, r.used_at,
               COALESCE(r.discount, p.discount_premium) AS disc
        FROM redemptions r JOIN partners p ON p.id = r.partner_id
        WHERE r.user_id = $1 AND r.status = 'used'
        ORDER BY r.used_at DESC LIMIT $2
        """,
        user_id,
        limit,
    )
    return "\n".join(f"• {r['used_at']:%d.%m} — {r['name']}, {r['disc']}%" for r in rows)


@router.message(StateFilter(None), F.photo)
async def receive_receipt(message: Message, db_user: dict | None) -> None:
    """Приём скрина чека Kaspi (раздел 3.1).

    При активной подписке чек тоже принимается — это заявка на продление,
    approve() стекует срок (+30 дней).
    """
    lang = settings.default_lang
    if db_user is None:
        await message.answer(t("not_registered_hint", lang))
        return
    if await payments.has_pending(message.from_user.id):
        await message.answer(t("pay_duplicate", lang))
        return

    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    buf = await message.bot.download_file(file.file_path)
    # Синхронный SDK Supabase — не блокируем event loop.
    url = await asyncio.to_thread(
        storage.upload_receipt, buf.read(), f"{message.from_user.id}_{photo.file_unique_id}.jpg"
    )

    sub = await payments.create_pending(message.from_user.id, url)
    if sub is None:  # гонка двух фото подряд — заявка уже создана
        await message.answer(t("pay_duplicate", lang))
        return
    await message.answer(t("pay_received", lang))

    # Уведомление админам с карточкой чека.
    for admin_id in settings.admin_id_set:
        with contextlib.suppress(Exception):
            await message.bot.send_photo(
                admin_id,
                photo.file_id,
                caption=f"🧾 Заявка #{sub['id']}\nОт: {message.from_user.full_name} "
                        f"(@{message.from_user.username})\nСумма: {sub['amount']} ₸",
                reply_markup=receipt_decision_kb(sub["id"]),
            )


@router.message(F.text == t("btn_help"))
async def show_help(message: Message) -> None:
    lang = settings.default_lang
    await message.answer(
        t("help", lang, price=settings.subscription_price),
        reply_markup=help_kb(lang),
    )


@router.callback_query(F.data.startswith("help:"))
async def help_contact(call: CallbackQuery, state: FSMContext) -> None:
    lang = settings.default_lang
    if call.data == "help:admin":
        await state.set_state(HelpContact.admin_msg)
        await call.message.answer(t("ask_admin_msg", lang))
    else:
        await state.set_state(HelpContact.complaint)
        await call.message.answer(t("ask_complaint", lang))
    await call.answer()


@router.message(HelpContact.admin_msg, ~F.text.startswith("/"))
@router.message(HelpContact.complaint, ~F.text.startswith("/"))
async def forward_to_admin(message: Message, state: FSMContext) -> None:
    """Форвард сообщения (текст/фото/что угодно) админам (раздел 3.6)."""
    lang = settings.default_lang
    current = await state.get_state()
    kind = "⚠️ Жалоба на заведение" if current == HelpContact.complaint.state else "✉️ Сообщение админу"
    await state.clear()

    header = (
        f"{kind}\nОт: {message.from_user.full_name} "
        f"(@{message.from_user.username}, id {message.from_user.id})"
    )
    for admin_id in settings.admin_id_set:
        with contextlib.suppress(Exception):
            await message.bot.send_message(admin_id, header)
            await message.forward(admin_id)
    await message.answer(t("msg_forwarded", lang))


@router.message(F.text == t("btn_invite"))
async def show_invite(message: Message) -> None:
    me = await message.bot.get_me()
    await message.answer(
        f"Пригласите друга:\nhttps://t.me/{me.username}?start=ref_{message.from_user.id}\n\n"
        "Друг оформит подписку → вам +7 дней."
    )


@router.message(F.text == t("btn_raffle"))
async def stub_raffle(message: Message) -> None:
    # Розыгрыши — Фаза 2 (раздел 7).
    await message.answer("Розыгрыши скоро появятся 🎁")


def _safe_int(s: str) -> int | None:
    try:
        return int(s)
    except (TypeError, ValueError):
        return None
