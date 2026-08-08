"""APScheduler: знак дня, деактивация подписок, напоминания, протухание QR (раздел 1)."""
from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot import db
from bot.services import qr
from bot.texts import t

log = logging.getLogger(__name__)


async def expire_subscriptions() -> None:
    """Просроченные active → expired."""
    res = await db.execute(
        "UPDATE subscriptions SET status = 'expired' "
        "WHERE status = 'active' AND expires_at <= now()"
    )
    log.info("expire_subscriptions: %s", res)


async def expire_redemptions() -> None:
    """Непогашенные коды с истёкшим TTL → expired."""
    await db.execute(
        "UPDATE redemptions SET status = 'expired' "
        "WHERE status = 'issued' AND expires_at <= now()"
    )


async def remind_expiring(bot: Bot) -> None:
    """За 3 дня до expires_at — напоминание о продлении (раздел 3.1).

    Запускается раз в день; выбирает подписки, истекающие ровно через 3 дня, —
    так каждый получает одно напоминание без флага «уже напомнили».
    """
    rows = await db.fetch(
        """
        SELECT user_id, expires_at FROM subscriptions
        WHERE status = 'active'
          AND expires_at::date = (now() + interval '3 days')::date
        """
    )
    for r in rows:
        with contextlib.suppress(Exception):
            await bot.send_message(r["user_id"], t("sub_reminder", days=3))
        await asyncio.sleep(0.05)
    if rows:
        log.info("remind_expiring: напомнили %d", len(rows))


async def notify_daily_sign(bot: Bot) -> None:
    """Утро: знак дня партнёрам (анти-фрод сверка на кассе, раздел 3.2)."""
    sign = qr.daily_sign()
    partners = await db.fetch(
        "SELECT user_id FROM partners WHERE is_active AND user_id IS NOT NULL"
    )
    sent = 0
    for p in partners:
        with contextlib.suppress(Exception):
            await bot.send_message(p["user_id"], f"Знак дня сегодня: {sign}")
            sent += 1
        await asyncio.sleep(0.05)  # ~20 msg/сек, под лимитом Telegram
    log.info("notify_daily_sign: отправлено %d, знак %s", sent, sign)


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    sched = AsyncIOScheduler(timezone="Asia/Almaty")
    sched.add_job(expire_subscriptions, "interval", hours=1, id="expire_subs")
    sched.add_job(expire_redemptions, "interval", minutes=10, id="expire_redemptions")
    sched.add_job(notify_daily_sign, "cron", hour=9, minute=0, args=[bot], id="daily_sign")
    sched.add_job(remind_expiring, "cron", hour=11, minute=0, args=[bot], id="remind_expiring")
    return sched
