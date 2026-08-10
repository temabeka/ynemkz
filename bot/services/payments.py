"""Подписки: приём чека Kaspi и ручное подтверждение админом (раздел 3.1)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import asyncpg

from bot import db
from bot.config import settings


async def has_pending(user_id: int) -> bool:
    """Защита: не более 1 pending-заявки на пользователя."""
    n = await db.fetchval(
        "SELECT count(*) FROM subscriptions WHERE user_id = $1 AND status = 'pending'",
        user_id,
    )
    return bool(n)


async def create_pending(user_id: int, receipt_url: str) -> dict | None:
    """Создать pending-заявку. None — заявка уже на проверке (частичный
    уникальный индекс uq_subscriptions_one_pending, миграция 003)."""
    try:
        row = await db.fetchrow(
            """
            INSERT INTO subscriptions (user_id, status, receipt_url, amount)
            VALUES ($1, 'pending', $2, $3)
            RETURNING *
            """,
            user_id,
            receipt_url,
            settings.subscription_price,
        )
    except asyncpg.UniqueViolationError:
        return None
    return dict(row)


async def approve(subscription_id: int, admin_id: int) -> dict | None:
    """Подтвердить pending-заявку. Если у пользователя уже есть активная
    подписка — это продление: срок стекуется, expires_at =
    GREATEST(текущий expires_at, now()) + 30 дней (раздел 3.1)."""
    now = datetime.now(timezone.utc)
    row = await db.fetchrow(
        """
        UPDATE subscriptions s
        SET status = 'active', paid_at = $2, confirmed_by = $3,
            expires_at = coalesce(
                (SELECT max(expires_at) FROM subscriptions
                 WHERE user_id = s.user_id AND status = 'active' AND expires_at > $2),
                $2) + interval '30 days'
        WHERE s.id = $1 AND s.status = 'pending'
        RETURNING *
        """,
        subscription_id,
        now,
        admin_id,
    )
    return dict(row) if row else None


async def reject(subscription_id: int, admin_id: int) -> dict | None:
    row = await db.fetchrow(
        """
        UPDATE subscriptions SET status = 'rejected', confirmed_by = $2
        WHERE id = $1 AND status = 'pending'
        RETURNING *
        """,
        subscription_id,
        admin_id,
    )
    return dict(row) if row else None


async def approve_stars(user_id: int, charge_id: str, amount_stars: int) -> dict | None:
    """Оплата Telegram Stars: подписка активируется мгновенно, без админа.

    Каждый платёж — ОТДЕЛЬНАЯ строка (как Kaspi через approve): tg_charge_id
    никогда не перезаписывается, поэтому идемпотентность и возврат остаются
    рабочими для каждого платежа, а история денег не теряется. Продление
    стекуется: expires_at новой строки = GREATEST(max активный expires_at,
    now()) + 30 дней (раздел 3.1).

    Идемпотентность: charge_id уникален (индекс uq_subscriptions_tg_charge_id,
    миграция 003) — повторная доставка successful_payment возвращает None
    (dup-check + гонка ловится UniqueViolationError на вставке).
    """
    now = datetime.now(timezone.utc)

    # Повторная доставка: этот платёж уже учтён.
    dup = await db.fetchval(
        "SELECT 1 FROM subscriptions WHERE tg_charge_id = $1", charge_id
    )
    if dup:
        return None

    try:
        row = await db.fetchrow(
            """
            INSERT INTO subscriptions (user_id, status, amount, paid_at, expires_at,
                                       payment_method, tg_charge_id)
            VALUES ($1, 'active', $2, $3,
                    coalesce(
                        (SELECT max(expires_at) FROM subscriptions
                         WHERE user_id = $1 AND status = 'active' AND expires_at > $3),
                        $3) + interval '30 days',
                    'stars', $4)
            RETURNING *
            """,
            user_id,
            amount_stars,
            now,
            charge_id,
        )
    except asyncpg.UniqueViolationError:
        return None  # гонка повторной доставки — платёж уже учтён
    return dict(row)


async def grant_manual(user_id: int, days: int, admin_id: int) -> dict:
    """Ручная выдача/продление подписки админом (наличные, промо, компенсация).

    Стекинг как в approve_stars: активная подписка продлевается
    (GREATEST(expires_at, now()) + N дней) — payment_method и amount
    НЕ трогаем, чтобы Kaspi/Stars-подписка не «превратилась» в manual
    (сломались бы бейджи и кнопка возврата Stars). Без активной — новая
    строка payment_method='manual', amount=0.
    """
    now = datetime.now(timezone.utc)
    row = await db.fetchrow(
        """
        UPDATE subscriptions
        SET expires_at = GREATEST(expires_at, $2) + make_interval(days => $3)
        WHERE id = (SELECT id FROM subscriptions
                    WHERE user_id = $1 AND status = 'active' AND expires_at > $2
                    ORDER BY expires_at DESC LIMIT 1)
        RETURNING *
        """,
        user_id,
        now,
        days,
    )
    if row:
        return dict(row)

    # expires_at считаем в Python (как в approve_stars): $2 и в paid_at, и в
    # "$2 + interval" Postgres не может однозначно типизировать (Ambiguous
    # ParameterError: interval versus timestamptz)
    row = await db.fetchrow(
        """
        INSERT INTO subscriptions (user_id, status, amount, paid_at, expires_at,
                                   payment_method, confirmed_by)
        VALUES ($1, 'active', 0, $2, $3, 'manual', $4)
        RETURNING *
        """,
        user_id,
        now,
        now + timedelta(days=days),
        admin_id,
    )
    return dict(row)


async def cancel_active(user_id: int, admin_id: int) -> dict | None:
    """Отменить активную подписку любого метода: status='expired' (scheduler и
    сегмент рассылки «Истёкшие» уже оперируют этим статусом). Stars-возврат —
    отдельное действие refund_stars; здесь звёзды НЕ возвращаются.

    Гасит все активные строки пользователя разом (обычно одна благодаря
    стекингу). None — активной подписки нет.
    """
    rows = await db.fetch(
        """
        UPDATE subscriptions
        SET status = 'expired', expires_at = now(), confirmed_by = $2
        WHERE user_id = $1 AND status = 'active' AND expires_at > now()
        RETURNING *
        """,
        user_id,
        admin_id,
    )
    return dict(rows[0]) if rows else None


async def refund_stars(bot, subscription_id: int) -> dict:
    """Возврат Stars-платежа: звёзды назад, подписка гаснет. Бросает ValueError.

    bot — aiogram Bot (у бота свой, у API — временный без polling).
    Порядок атомарный: сначала гасим подписку (UPDATE ... WHERE status='active' —
    параллельный /refund получит «уже возвращена»), затем возврат в Telegram;
    при ошибке Telegram откатываем статус обратно в active.
    """
    sub = await db.fetchrow(
        """
        UPDATE subscriptions SET status = 'refunded'
        WHERE id = $1 AND status = 'active'
          AND payment_method = 'stars' AND tg_charge_id IS NOT NULL
        RETURNING *
        """,
        subscription_id,
    )
    if sub is None:
        raise ValueError("Заявка не найдена, не Stars-платёж или уже возвращена/не активна.")
    try:
        await bot.refund_star_payment(
            user_id=sub["user_id"],
            telegram_payment_charge_id=sub["tg_charge_id"],
        )
    except Exception:
        # Telegram отклонил возврат — подписка остаётся активной.
        await db.execute(
            "UPDATE subscriptions SET status = 'active' WHERE id = $1", sub["id"]
        )
        raise
    return dict(sub)


async def apply_referral_bonus(user_id: int) -> int | None:
    """+7 дней рефереру при ПЕРВОЙ подписке приглашённого (раздел 3.6).

    Возвращает telegram_id реферера, если бонус начислен, иначе None.
    """
    row = await db.fetchrow(
        """
        SELECT u.referrer_id,
               (SELECT count(*) FROM subscriptions
                WHERE user_id = u.id AND status IN ('active', 'expired')
                  AND payment_method <> 'manual') AS paid_count
        FROM users u WHERE u.id = $1
        """,
        user_id,
    )
    if row is None or row["referrer_id"] is None or row["paid_count"] != 1:
        return None
    bonus = await db.fetchrow(
        """
        UPDATE subscriptions SET expires_at = expires_at + interval '7 days'
        WHERE user_id = $1 AND status = 'active' AND expires_at > now()
        RETURNING user_id
        """,
        row["referrer_id"],
    )
    return row["referrer_id"] if bonus else None


async def savings(user_id: int) -> tuple[int, int]:
    """(визитов, сэкономлено ₸) — счётчик «вы сэкономили» по avg_check партнёра."""
    row = await db.fetchrow(
        """
        SELECT count(*) AS visits,
               coalesce(sum(
                 p.avg_check * coalesce(r.discount, p.discount_premium) / 100
               ), 0)::int AS saved
        FROM redemptions r JOIN partners p ON p.id = r.partner_id
        WHERE r.user_id = $1 AND r.status = 'used'
        """,
        user_id,
    )
    return row["visits"], row["saved"]


async def active_subscription(user_id: int) -> dict | None:
    row = await db.fetchrow(
        """
        SELECT * FROM subscriptions
        WHERE user_id = $1 AND status = 'active' AND expires_at > now()
        ORDER BY expires_at DESC LIMIT 1
        """,
        user_id,
    )
    return dict(row) if row else None
