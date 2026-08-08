"""Профиль, визиты, активация скидки, оплата Stars."""
from __future__ import annotations

import asyncio
import contextlib
import io
from datetime import datetime, timezone

from aiogram import Bot
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from api.auth import get_user
from bot import db
from bot.config import settings
from bot.services import partners, payments, qr, redemption
from bot.texts import t

router = APIRouter()

# Ссылки на фоновые задачи: без них garbage collector может убить task на лету.
_bg_tasks: set[asyncio.Task] = set()


def _spawn(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return task


def _bot() -> Bot:
    """aiogram Bot без polling — для пингов и инвойсов из API."""
    return Bot(token=settings.bot_token)


async def _ping_partners(chat_ids: list[int], text: str) -> None:
    """Пинг владельцу и кассирам заведения одним ботом без polling."""
    bot = _bot()
    try:
        for chat_id in chat_ids:
            with contextlib.suppress(Exception):
                await bot.send_message(chat_id, text)
    finally:
        await bot.session.close()


async def _ensure_qr_token(user: dict) -> str:
    """Токен персонального QR — лениво при первом запросе профиля.

    COALESCE решает гонку двух параллельных /me: побеждает первый токен.
    user из auth-кэша (5 мин) может не знать о токене — тогда лишний UPDATE
    вернёт уже существующий.
    """
    if user.get("qr_token"):
        return user["qr_token"]
    return await db.fetchval(
        "UPDATE users SET qr_token = coalesce(qr_token, $2) WHERE id = $1 RETURNING qr_token",
        user["id"], qr.gen_client_token(),
    )


@router.get("/me")
async def me(user: dict = Depends(get_user)) -> dict:
    sub = await payments.active_subscription(user["id"])
    visits, saved = await payments.savings(user["id"])
    days_left = None
    if sub:
        days_left = max((sub["expires_at"] - datetime.now(timezone.utc)).days, 0)
    return {
        "id": user["id"],
        "full_name": user["full_name"],
        "role": user["role"],
        "subscription": {
            "active": sub is not None,
            "days_left": days_left,
            "pending": await payments.has_pending(user["id"]) if not sub else False,
        },
        "visits": visits,
        "saved": saved,
        "daily_sign": qr.daily_sign(),
        "qr_token": await _ensure_qr_token(user),
    }


@router.get("/me/avatar")
async def my_avatar(user: dict = Depends(get_user)) -> Response:
    """Фото профиля Telegram — центр персонального QR (вариант D, раздел 3.2).

    Байты отдаём сами: прямые file-ссылки Telegram содержат токен бота.
    """
    bot = _bot()
    try:
        photos = await bot.get_user_profile_photos(user["id"], limit=1)
        if not photos.photos:
            raise HTTPException(404, "no avatar")
        sizes = photos.photos[0]
        # Средний размер (~320px) — достаточно для центра QR, не тянем оригинал
        size = sizes[1] if len(sizes) > 1 else sizes[0]
        buf = io.BytesIO()
        await bot.download(size.file_id, destination=buf)
    finally:
        await bot.session.close()
    return Response(buf.getvalue(), media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=86400"})


@router.get("/me/visits")
async def my_visits(user: dict = Depends(get_user)) -> list[dict]:
    rows = await db.fetch(
        """
        SELECT p.name, r.used_at,
               coalesce(r.discount, p.discount_premium) AS discount
        FROM redemptions r JOIN partners p ON p.id = r.partner_id
        WHERE r.user_id = $1 AND r.status = 'used'
        ORDER BY r.used_at DESC LIMIT 50
        """,
        user["id"],
    )
    return [dict(r) for r in rows]


class ActivateBody(BaseModel):
    partner_id: int


@router.post("/activate")
async def activate(body: ActivateBody, user: dict = Depends(get_user)) -> dict:
    """Экран активации в Mini App (вариант C): визит пишется сразу + пинг партнёру."""
    try:
        result = await redemption.activate(user["id"], body.partner_id)
    except redemption.NeedSubscription as e:
        raise HTTPException(402, {"reason": "need_subscription",
                                  "partner": e.partner_name, "discount": e.discount})
    except redemption.RedeemError as e:
        raise HTTPException(409, str(e))

    now = datetime.now(timezone.utc)
    partner = result["partner"]
    recipients = await partners.ping_recipients(partner["id"])
    if recipients:
        # Пинг владельцу и кассирам — в фоне: клиент не должен ждать Telegram API
        _spawn(_ping_partners(
            recipients,
            t("partner_ping", name=user["full_name"] or "Клиент",
              discount=result["discount"], time=now.strftime("%H:%M")),
        ))

    return {
        "partner_name": partner["name"],
        "discount": result["discount"],
        "kind": result["kind"],
        "client_name": user["full_name"],
        "daily_sign": qr.daily_sign(),
        "server_time": now.isoformat(),
        "expires_at": result["redemption"]["expires_at"].isoformat(),
    }


@router.post("/stars-invoice")
async def stars_invoice(user: dict = Depends(get_user)) -> dict:
    """Ссылка на инвойс в Stars (XTR) — Mini App открывает её через openInvoice.

    Активная подписка не блокирует оплату: продление стекуется — +30 дней
    к текущему сроку (раздел 3.1).
    """
    bot = _bot()
    try:
        link = await bot.create_invoice_link(
            title="Подписка Ynem",
            description="Скидки 10–15% у всех партнёров на 30 дней "
                        "(при активной подписке — продление, дни сложатся)",
            payload=f"sub:{user['id']}",
            currency="XTR",
            prices=[{"label": "Подписка на 30 дней",
                     "amount": settings.subscription_price_stars}],
        )
    finally:
        await bot.session.close()
    return {"invoice_link": link}
