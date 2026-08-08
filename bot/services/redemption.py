"""Активация скидок: выдача экрана (вариант C) и фолбэк-код (вариант A).

Анти-фрод (раздел 3.2): лимит 1 активация у партнёра в день на пользователя,
привязка к партнёру, TTL 30 мин у кода / 5 мин у экрана.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import asyncpg

from bot import db
from bot.services import qr

CODE_TTL = timedelta(minutes=30)      # фолбэк-код (вариант A)
SCREEN_TTL = timedelta(minutes=5)     # экран активации (вариант C)

# Атомарную гарантию лимита даёт уникальный индекс
# uq_redemptions_user_partner_day (user_id, partner_id, issued_on) — миграция 003.
_DAILY_LIMIT_MSG = "Вы уже активировали скидку у этого партнёра сегодня."


class RedeemError(Exception):
    """Ошибка бизнес-правила активации (лимит, нет подписки и т.п.)."""


async def _check_daily_limit(user_id: int, partner_id: int) -> None:
    """Быстрый pre-check; настоящая защита от гонки — уникальный индекс в issue()."""
    used = await db.fetchval(
        """
        SELECT count(*) FROM redemptions
        WHERE user_id = $1 AND partner_id = $2
          AND issued_on = now()::date
        """,
        user_id,
        partner_id,
    )
    if used:
        raise RedeemError(_DAILY_LIMIT_MSG)


async def issue(
    user_id: int,
    partner_id: int,
    kind: str = "premium",
    auto_use: bool = False,
    discount: int | None = None,
) -> dict:
    """Создать redemption и вернуть данные для экрана активации.

    kind: 'premium' (по подписке) — единственный тип после отказа от скидки дня.
    auto_use: вариант C (наклейка) — визит записывается сразу (раздел 3.2),
      кассир ничего не вводит. False — фолбэк A, код гасится кассиром.
    discount: % на момент визита — фиксируется, чтобы история не менялась
      при смене процента партнёра.
    """
    await _check_daily_limit(user_id, partner_id)

    now = datetime.now(timezone.utc)
    code = qr.gen_code()
    try:
        row = await db.fetchrow(
            """
            INSERT INTO redemptions (code, user_id, partner_id, type, status, issued_at, used_at, expires_at, discount)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING *
            """,
            code,
            user_id,
            partner_id,
            kind,
            "used" if auto_use else "issued",
            now,
            now if auto_use else None,
            now + (SCREEN_TTL if auto_use else CODE_TTL),
            discount,
        )
    except asyncpg.UniqueViolationError as e:
        # Гонка двух параллельных активаций: лимит держит уникальный индекс.
        if e.constraint_name == "uq_redemptions_user_partner_day":
            raise RedeemError(_DAILY_LIMIT_MSG) from e
        raise
    return dict(row)


async def activate(user_id: int, partner_id: int) -> dict:
    """Полный флоу активации (вариант C) — общий для бота и API.

    Правила: скидка discount_premium только по активной подписке; без подписки —
    NeedSubscription. Визит пишется сразу.
    Возвращает {partner, discount, kind, redemption}. Бросает RedeemError.
    """
    from bot.services import payments  # локальный импорт — разрыв цикла

    partner = await db.fetchrow(
        "SELECT * FROM partners WHERE id = $1 AND is_active AND NOT is_paused", partner_id
    )
    if partner is None:
        raise RedeemError("Заведение не найдено или временно недоступно.")

    sub = await payments.active_subscription(user_id)
    if not sub:
        raise NeedSubscription(partner["name"], partner["discount_premium"])
    kind, discount = "premium", partner["discount_premium"]

    redemption = await issue(user_id, partner_id, kind, auto_use=True, discount=discount)
    return {"partner": dict(partner), "discount": discount, "kind": kind, "redemption": redemption}


class NeedSubscription(RedeemError):
    """Скидка у этого партнёра доступна только по подписке."""

    def __init__(self, partner_name: str, discount: int):
        self.partner_name = partner_name
        self.discount = discount
        super().__init__(f"Скидка у «{partner_name}» доступна по подписке.")


async def redeem_by_code(code: str, partner_id: int) -> dict | None:
    """Атомарное погашение кода кассиром (фолбэк A, раздел 3.2).

    Возвращает запись при успехе, None если код неверный/использован/истёк.
    """
    row = await db.fetchrow(
        """
        UPDATE redemptions SET status = 'used', used_at = now()
        WHERE code = $1 AND partner_id = $2 AND status = 'issued' AND expires_at > now()
        RETURNING *
        """,
        code.upper(),
        partner_id,
    )
    return dict(row) if row else None
