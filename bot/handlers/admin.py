"""Админ (в боте, раздел 3.5): партнёры, подписчики, заявки, рассылка."""
from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, MagicData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import db
from bot.config import settings
from bot.keyboards import broadcast_confirm_kb
from bot.services import broadcast, payments, qr
from bot.texts import t

log = logging.getLogger(__name__)

# Роутер закрыт фильтром по роли (data кладёт AuthMiddleware, outer):
# апдейты не-админов проходят мимо — /stats партнёра доходит до partner-роутера.
router = Router(name="admin")
router.message.filter(MagicData(F.role == "admin"))
router.callback_query.filter(MagicData(F.role == "admin"))

# /admin_access доступен любому (иначе роль admin не получить) — отдельный роутер.
access_router = Router(name="admin_access")


class BroadcastFlow(StatesGroup):
    confirm = State()


def _safe_int(s: str) -> int | None:
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


@access_router.message(Command("admin_access"))
async def grant_admin(message: Message, role: str, command: CommandObject) -> None:
    """Выдача роли admin по секрету: /admin_access <ADMIN_SECRET>.

    Секрет в env; пусто — команда отключена. На неверный секрет молчим
    (не подтверждаем существование команды). Сообщение с секретом удаляем.
    """
    secret = (command.args or "").strip()
    # Секрет не должен оставаться в истории чата
    with contextlib.suppress(Exception):
        await message.delete()

    if not settings.admin_secret or not secret:
        return
    if not hmac.compare_digest(secret, settings.admin_secret):
        log.warning("admin_access: неверный секрет от %s", message.from_user.id)
        return
    if role == "admin":
        await message.answer("Вы уже админ. Меню: /admin")
        return

    await db.execute(
        """
        INSERT INTO users (id, username, full_name, role)
        VALUES ($1, $2, $3, 'admin')
        ON CONFLICT (id) DO UPDATE SET role = 'admin'
        """,
        message.from_user.id,
        message.from_user.username,
        message.from_user.full_name,
    )
    log.info("admin_access: роль admin выдана %s", message.from_user.id)
    await message.answer("✅ Роль admin выдана. Меню: /admin")

    # Аудит: уведомить остальных админов
    for admin_id in settings.admin_id_set - {message.from_user.id}:
        with contextlib.suppress(Exception):
            await message.bot.send_message(
                admin_id,
                f"⚠️ Новый админ через /admin_access: {message.from_user.full_name} "
                f"(@{message.from_user.username}, id {message.from_user.id})",
            )


@router.message(Command("admin"))
async def admin_menu(message: Message, role: str) -> None:
    if role != "admin":
        return
    await message.answer(
        "🛠 Админка:\n"
        "/add_partner {tg_id} {название} — добавить партнёра\n"
        "/set_location {partner_id} {lat} {lng} — координаты (пин на карте)\n"
        "фото с подписью «/logo {partner_id}» — логотип партнёра\n"
        "/qr {partner_id} — QR-наклейка на кассу\n"
        "/subs — список подписчиков\n"
        "/receipts — очередь чеков\n"
        "/refund {subscription_id} — возврат Stars-платежа\n"
        "/broadcast {all|subscribers|expired} {текст} — рассылка\n"
        "/stats — метрики\n"
        "/ban {tg_id} · /unban {tg_id} — модерация"
    )


@router.message(Command("add_partner"))
async def add_partner(message: Message, role: str, command: CommandObject) -> None:
    if role != "admin":
        return
    parts = (command.args or "").split(maxsplit=1)
    tg_id = _safe_int(parts[0]) if parts else None
    if len(parts) < 2 or tg_id is None:
        await message.answer("Формат: /add_partner {tg_id} {название}")
        return
    name = parts[1]
    # Заводим пользователя (если нет) и повышаем роль до partner.
    await db.execute(
        """INSERT INTO users (id, role) VALUES ($1, 'partner')
           ON CONFLICT (id) DO UPDATE SET role = 'partner'""",
        tg_id,
    )
    pid = await db.fetchval(
        "INSERT INTO partners (user_id, name) VALUES ($1, $2) RETURNING id", tg_id, name
    )
    await message.answer(f"✅ Партнёр #{pid} «{name}» добавлен. QR: /qr {pid}")


@router.message(Command("set_location"))
async def set_location(message: Message, role: str, command: CommandObject) -> None:
    """Координаты партнёра — без них он не попадает на карту Mini App."""
    if role != "admin":
        return
    parts = (command.args or "").split()
    try:
        pid, lat, lng = int(parts[0]), float(parts[1]), float(parts[2])
    except (IndexError, ValueError):
        await message.answer(
            "Формат: /set_location {partner_id} {lat} {lng}\n"
            "Координаты можно скопировать из 2GIS (ПКМ по точке)."
        )
        return
    res = await db.execute("UPDATE partners SET lat = $2, lng = $3 WHERE id = $1", pid, lat, lng)
    if res.endswith("0"):
        await message.answer(f"Партнёр #{pid} не найден.")
    else:
        await message.answer(f"📍 Партнёр #{pid}: {lat}, {lng} — появится на карте.")


@router.message(F.photo, F.caption.regexp(r"^/logo\s+\d+"))
async def set_logo(message: Message, role: str) -> None:
    """Логотип: админ шлёт фото с подписью «/logo <partner_id>»."""
    if role != "admin":
        return
    from bot.services import storage

    pid = int(message.caption.split()[1])
    exists = await db.fetchval("SELECT 1 FROM partners WHERE id = $1", pid)
    if not exists:
        await message.answer(f"Партнёр #{pid} не найден.")
        return

    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    buf = await message.bot.download_file(file.file_path)
    url = await asyncio.to_thread(storage.upload_logo, buf.read(), pid)  # синхронный SDK
    await db.execute("UPDATE partners SET logo_url = $2 WHERE id = $1", pid, url)
    await message.answer(f"🖼 Логотип партнёра #{pid} обновлён.")


@router.message(Command("refund"))
async def refund_stars(message: Message, role: str, command: CommandObject) -> None:
    """Возврат Stars-платежа: подписка гасится, звёзды возвращаются."""
    if role != "admin":
        return
    if not (command.args or "").strip().isdigit():
        await message.answer("Формат: /refund {subscription_id} (см. /subs)")
        return
    try:
        sub = await payments.refund_stars(message.bot, int(command.args.strip()))
    except ValueError as e:
        await message.answer(str(e))
        return
    except Exception as e:  # noqa: BLE001 — Telegram отклонил возврат
        await message.answer(f"Telegram отклонил возврат: {e}")
        return
    try:
        await message.bot.send_message(sub["user_id"], "⭐️ Платёж возвращён, подписка отменена.")
    except Exception:  # noqa: BLE001
        pass
    await message.answer(f"✅ Возврат по подписке #{sub['id']} выполнен.")


@router.message(Command("qr"))
async def partner_qr(message: Message, role: str, command: CommandObject) -> None:
    if role != "admin":
        return
    pid = _safe_int((command.args or "").strip())
    if pid is None:
        await message.answer("Формат: /qr {partner_id}")
        return
    me = await message.bot.get_me()
    png = qr.partner_qr(me.username, pid)
    from aiogram.types import BufferedInputFile
    await message.answer_photo(
        BufferedInputFile(png, filename=f"partner_{pid}.png"),
        caption=f"QR-наклейка для партнёра #{pid}",
    )


@router.message(Command("subs"))
async def list_subs(message: Message, role: str) -> None:
    if role != "admin":
        return
    rows = await db.fetch(
        """
        SELECT u.full_name, s.expires_at
        FROM subscriptions s JOIN users u ON u.id = s.user_id
        WHERE s.status = 'active' AND s.expires_at > now()
        ORDER BY s.expires_at
        """
    )
    if not rows:
        await message.answer("Активных подписчиков нет.")
        return
    lines = [f"• {r['full_name']} — до {r['expires_at']:%d.%m.%Y}" for r in rows]
    await message.answer("👥 Подписчики:\n" + "\n".join(lines))


@router.message(Command("receipts"))
async def list_receipts(message: Message, role: str) -> None:
    if role != "admin":
        return
    from bot.keyboards import receipt_decision_kb

    rows = await db.fetch(
        """
        SELECT s.id, u.full_name, u.username, s.amount, s.receipt_url
        FROM subscriptions s JOIN users u ON u.id = s.user_id
        WHERE s.status = 'pending' ORDER BY s.created_at
        """
    )
    if not rows:
        await message.answer("Очередь чеков пуста.")
        return
    for r in rows:
        await message.answer(
            f"🧾 Заявка #{r['id']}\n{r['full_name']} (@{r['username']}) — {r['amount']} ₸\n{r['receipt_url']}",
            reply_markup=receipt_decision_kb(r["id"]),
        )


@router.callback_query(F.data.startswith("sub:"))
async def decide_receipt(call: CallbackQuery, role: str) -> None:
    if role != "admin":
        await call.answer("Недостаточно прав.", show_alert=True)
        return
    _, action, sub_id = call.data.split(":")
    sub_id = int(sub_id)

    if action == "ok":
        sub = await payments.approve(sub_id, call.from_user.id)
        if sub:
            with contextlib.suppress(Exception):
                await call.bot.send_message(
                    sub["user_id"], t("sub_approved", date=f"{sub['expires_at']:%d.%m.%Y}")
                )
            # Реферальный бонус: первый платёж друга → рефереру +7 дней (раздел 3.6).
            referrer_id = await payments.apply_referral_bonus(sub["user_id"])
            if referrer_id:
                with contextlib.suppress(Exception):
                    await call.bot.send_message(referrer_id, t("referral_bonus"))
            # Пометка на карточке — в конце и независимо: карточка из /receipts
            # текстовая (edit_text), из уведомления — с фото (edit_caption).
            await _mark_receipt_card(call.message, "\n\n✅ Подтверждено")
        await call.answer("Подтверждено")
    else:
        sub = await payments.reject(sub_id, call.from_user.id)
        if sub:
            with contextlib.suppress(Exception):
                await call.bot.send_message(
                    sub["user_id"], "❌ Заявка отклонена. Проверьте чек и попробуйте снова."
                )
            await _mark_receipt_card(call.message, "\n\n❌ Отклонено")
        await call.answer("Отклонено")


async def _mark_receipt_card(msg: Message, mark: str) -> None:
    """Дописать вердикт на карточку чека — не роняя хэндлер, если не вышло."""
    with contextlib.suppress(TelegramBadRequest):
        if msg.photo:
            await msg.edit_caption(caption=(msg.caption or "") + mark)
        else:
            await msg.edit_text((msg.text or "") + mark)


@router.message(Command("stats"))
async def show_stats(message: Message, role: str) -> None:
    """Ключевые метрики (раздел 3.6): регистрации, подписки, активации."""
    if role != "admin":
        return
    row = await db.fetchrow(
        """
        SELECT
          (SELECT count(*) FROM users)                                              AS users_total,
          (SELECT count(*) FROM users WHERE created_at::date = now()::date)         AS users_today,
          (SELECT count(*) FROM subscriptions
             WHERE status = 'active' AND expires_at > now())                        AS subs_active,
          (SELECT count(*) FROM subscriptions WHERE status = 'pending')             AS subs_pending,
          (SELECT count(*) FROM redemptions
             WHERE status = 'used' AND used_at::date = now()::date)                 AS visits_today,
          (SELECT count(*) FROM redemptions
             WHERE status = 'used' AND used_at >= now() - interval '30 days')       AS visits_month
        """
    )
    conversion = round(row["subs_active"] / row["users_total"] * 100, 1) if row["users_total"] else 0
    await message.answer(
        "📈 <b>Статистика</b>\n"
        f"Пользователей: {row['users_total']} (+{row['users_today']} сегодня)\n"
        f"Активных подписок: {row['subs_active']} (конверсия {conversion}%)\n"
        f"Заявок в очереди: {row['subs_pending']}\n"
        f"Визитов: сегодня {row['visits_today']}, за месяц {row['visits_month']}"
    )


@router.message(Command("ban"))
@router.message(Command("unban"))
async def moderate_user(message: Message, role: str, command: CommandObject) -> None:
    if role != "admin":
        return
    if not (command.args or "").strip().isdigit():
        await message.answer(f"Формат: /{command.command} {{tg_id}}")
        return
    banned = command.command == "ban"
    res = await db.execute(
        "UPDATE users SET is_banned = $2 WHERE id = $1", int(command.args.strip()), banned
    )
    if res.endswith("0"):
        await message.answer("Пользователь не найден.")
    else:
        await message.answer("🚫 Забанен." if banned else "✅ Разбанен.")


@router.message(Command("broadcast"))
async def broadcast_preview(message: Message, role: str, command: CommandObject, state: FSMContext) -> None:
    """Предпросмотр + подтверждение перед отправкой (раздел 3.5)."""
    if role != "admin":
        return
    parts = (command.args or "").split(maxsplit=1)
    if len(parts) < 2 or parts[0] not in ("all", "subscribers", "expired"):
        await message.answer("Формат: /broadcast {all|subscribers|expired} {текст}")
        return
    segment, text = parts[0], parts[1]

    recipients = len(await broadcast.segment_ids(segment))
    await state.set_state(BroadcastFlow.confirm)
    await state.update_data(segment=segment, text=text)
    await message.answer(f"📣 Предпросмотр — сегмент «{segment}», получателей: {recipients}.\nСообщение ниже 👇")
    await message.answer(text, reply_markup=broadcast_confirm_kb())


@router.callback_query(BroadcastFlow.confirm, F.data == "bc:go")
async def broadcast_go(call: CallbackQuery, role: str, state: FSMContext) -> None:
    if role != "admin":
        await call.answer(t("not_allowed"), show_alert=True)
        return
    data = await state.get_data()
    await state.clear()
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Отправляю…")
    sent = await broadcast.send(call.bot, data["text"], data["segment"])
    await call.message.answer(f"✅ Рассылка завершена. Отправлено: {sent}")


@router.callback_query(F.data == "bc:cancel")
async def broadcast_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Отменено")
    await call.message.answer("✖️ Рассылка отменена.")
