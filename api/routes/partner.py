"""Кабинет партнёра: статистика, скан QR клиента, фолбэк-код, сотрудники, скидка."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import require_role
from api.routes.admin import Category
from api.routes.me import _ping_partners, _spawn
from bot import db
from bot.config import settings
from bot.services import partners, redemption
from bot.texts import t

router = APIRouter(dependencies=[Depends(require_role("partner", "admin"))])


async def _partner_of(user_id: int, owner_only: bool = False) -> tuple[dict, bool]:
    """Заведение пользователя (владелец или кассир) + флаг владения."""
    res = await partners.partner_for_user(user_id)
    if res is None:
        raise HTTPException(404, "partner profile not found")
    partner, is_owner = res
    if owner_only and not is_owner:
        raise HTTPException(403, "доступно только владельцу заведения")
    return partner, is_owner


@router.get("/stats")
async def stats(user: dict = Depends(require_role("partner", "admin"))) -> dict:
    partner, _ = await _partner_of(user["id"])
    row = await db.fetchrow(
        """
        SELECT
          count(*) FILTER (WHERE used_at::date = now()::date)                    AS today,
          count(*) FILTER (WHERE used_at >= now() - interval '7 days')           AS week,
          count(*) FILTER (WHERE used_at >= now() - interval '30 days')          AS month,
          count(DISTINCT user_id) FILTER
            (WHERE used_at >= now() - interval '30 days')                        AS unique_month
        FROM redemptions
        WHERE partner_id = $1 AND status = 'used'
        """,
        partner["id"],
    )
    # Новые vs повторные за месяц: новый = первый визит к этому партнёру в этом месяце
    clients = await db.fetchrow(
        """
        SELECT
          count(*) FILTER (WHERE first_visit >= now() - interval '30 days') AS new_clients,
          count(*) FILTER (WHERE first_visit <  now() - interval '30 days') AS repeat_clients
        FROM (
          SELECT user_id, min(used_at) AS first_visit
          FROM redemptions
          WHERE partner_id = $1 AND status = 'used'
          GROUP BY user_id
          HAVING max(used_at) >= now() - interval '30 days'
        ) t
        """,
        partner["id"],
    )
    # По дням за месяц — для графика
    days = await db.fetch(
        """
        SELECT used_at::date AS day, count(*) AS visits
        FROM redemptions
        WHERE partner_id = $1 AND status = 'used' AND used_at >= now() - interval '30 days'
        GROUP BY 1 ORDER BY 1
        """,
        partner["id"],
    )
    return {**dict(row), **dict(clients), "by_day": [dict(d) for d in days]}


@router.get("/me")
async def my_card(user: dict = Depends(require_role("partner", "admin"))) -> dict:
    """Моя карточка. Владелец меняет % (10–15) и паузу сам, остальное — через админа."""
    partner, is_owner = await _partner_of(user["id"])
    return {**partner, "is_owner": is_owner}


@router.get("/activations")
async def activations(user: dict = Depends(require_role("partner", "admin"))) -> list[dict]:
    """Лента последних визитов."""
    partner, _ = await _partner_of(user["id"])
    rows = await db.fetch(
        """
        SELECT u.full_name, r.used_at,
               coalesce(r.discount, $2) AS discount
        FROM redemptions r JOIN users u ON u.id = r.user_id
        WHERE r.partner_id = $1 AND r.status = 'used'
        ORDER BY r.used_at DESC LIMIT 30
        """,
        partner["id"], partner["discount_premium"],
    )
    return [dict(r) for r in rows]


class PauseBody(BaseModel):
    paused: bool


@router.post("/pause")
async def set_pause(body: PauseBody,
                    user: dict = Depends(require_role("partner", "admin"))) -> dict:
    """Пауза скидки («отпуск») — карточка скрывается из каталога и карты. Только владелец."""
    partner, _ = await _partner_of(user["id"], owner_only=True)
    await db.execute("UPDATE partners SET is_paused = $2 WHERE id = $1",
                     partner["id"], body.paused)
    return {"is_paused": body.paused}


class ScanBody(BaseModel):
    qr: str  # содержимое QR: deep link t.me/...startapp=c_<token> или голый токен


@router.post("/scan")
async def scan(body: ScanBody, user: dict = Depends(require_role("partner", "admin"))) -> dict:
    """Кассир сканирует персональный QR клиента (вариант D, раздел 3.2).

    Зеркало POST /api/activate: те же правила (проверка подписки, кулдаун
    30 мин между активациями), но активацию запускает кассир — клиенту ничего
    сканировать не нужно, ему уходит подтверждение в бот.
    """
    partner, _ = await _partner_of(user["id"])
    m = re.search(r"c_([A-Za-z0-9_-]{8,64})", body.qr.strip())
    token = m.group(1) if m else body.qr.strip()
    client = await db.fetchrow(
        "SELECT id, full_name, is_banned FROM users WHERE qr_token = $1", token
    )
    if client is None:
        raise HTTPException(404, "QR не распознан — это не код клиента Ynem")
    if client["is_banned"]:
        raise HTTPException(403, "клиент заблокирован в клубе")

    try:
        result = await redemption.activate(client["id"], partner["id"])
    except redemption.NeedSubscription:
        raise HTTPException(402, "у клиента нет подписки — сегодня скидка ему здесь недоступна")
    except redemption.RedeemError as e:
        raise HTTPException(409, str(e))

    # Подтверждение клиенту в бот — в фоне, кассир не ждёт Telegram API
    _spawn(_ping_partners(
        [client["id"]],
        t("qr_scan_ping", partner=partner["name"], discount=result["discount"]),
    ))
    return {
        "client_name": client["full_name"],
        "discount": result["discount"],
        "kind": result["kind"],
        "partner_name": partner["name"],
    }


class RedeemBody(BaseModel):
    code: str


@router.post("/redeem")
async def redeem(body: RedeemBody, user: dict = Depends(require_role("partner", "admin"))) -> dict:
    """Фолбэк A: кассир вводит код клиента в Mini App."""
    partner, _ = await _partner_of(user["id"])
    row = await redemption.redeem_by_code(body.code, partner["id"])
    if row is None:
        raise HTTPException(409, "код неверный, уже использован или истёк")
    client = await db.fetchrow("SELECT full_name FROM users WHERE id = $1", row["user_id"])
    return {"ok": True, "client_name": client["full_name"] if client else None}


# --- Сотрудники-кассиры (владелец управляет, кассиры получают пинги) -------------

class StaffBody(BaseModel):
    query: str  # @username или числовой telegram_id


@router.get("/staff")
async def staff(user: dict = Depends(require_role("partner", "admin"))) -> list[dict]:
    partner, _ = await _partner_of(user["id"], owner_only=True)
    return await partners.staff_list(partner["id"])


@router.post("/staff")
async def staff_add(body: StaffBody,
                    user: dict = Depends(require_role("partner", "admin"))) -> dict:
    partner, _ = await _partner_of(user["id"], owner_only=True)
    try:
        cashier_id = await partners.resolve_user_id(body.query)
        await partners.staff_add(partner["id"], user["id"], cashier_id)
    except partners.StaffError as e:
        raise HTTPException(409, str(e))
    return {"ok": True}


@router.post("/staff/invite")
async def staff_invite(user: dict = Depends(require_role("partner", "admin"))) -> dict:
    """Одноразовый токен приглашения кассира (TTL 24 ч).

    Ссылку t.me/<bot>?start=staff_<token> собирает Mini App (username бота — на фронте).
    """
    partner, _ = await _partner_of(user["id"], owner_only=True)
    return {"token": await partners.create_invite(partner["id"])}


@router.delete("/staff/{telegram_id}")
async def staff_remove(telegram_id: int,
                       user: dict = Depends(require_role("partner", "admin"))) -> dict:
    partner, _ = await _partner_of(user["id"], owner_only=True)
    await partners.staff_remove(partner["id"], telegram_id)
    return {"ok": True}


# --- Заявка на изменение карточки (модерация админом) ----------------------------

class EditBody(BaseModel):
    """Поля, которые партнёр может предложить изменить. Пустые не отправляются."""
    name: str | None = Field(default=None, min_length=2, max_length=80)
    category: Category | None = None
    address: str | None = Field(default=None, min_length=3, max_length=200)
    work_hours: str | None = Field(default=None, min_length=3, max_length=100)
    avg_check: int | None = Field(default=None, ge=100, le=1_000_000)


@router.get("/edit")
async def edit_pending(user: dict = Depends(require_role("partner", "admin"))) -> dict | None:
    """Текущая заявка на модерации — для баннера в кабинете."""
    partner, _ = await _partner_of(user["id"], owner_only=True)
    return await partners.pending_edit(partner["id"])


@router.post("/edit")
async def edit_submit(body: EditBody,
                      user: dict = Depends(require_role("partner", "admin"))) -> dict:
    partner, _ = await _partner_of(user["id"], owner_only=True)
    try:
        edit = await partners.submit_edit(partner["id"], user["id"],
                                          body.model_dump(exclude_none=True))
    except partners.EditError as e:
        raise HTTPException(409, str(e))
    # Админам — пинг в бот, решение принимается в Mini App
    if settings.admin_id_set:
        _spawn(_ping_partners(sorted(settings.admin_id_set),
                              t("edit_submitted_admin", partner=partner["name"])))
    edit["created_at"] = edit["created_at"].isoformat()
    return {"id": edit["id"], "changes": edit["changes"], "created_at": edit["created_at"]}


@router.delete("/edit")
async def edit_cancel(user: dict = Depends(require_role("partner", "admin"))) -> dict:
    partner, _ = await _partner_of(user["id"], owner_only=True)
    return {"cancelled": await partners.cancel_edit(partner["id"])}


# --- Моя скидка: владелец меняет % для подписчиков в пределах 10–15 --------------

class DiscountBody(BaseModel):
    discount: int = Field(ge=partners.DISCOUNT_MIN, le=partners.DISCOUNT_MAX)


@router.post("/discount")
async def set_discount(body: DiscountBody,
                       user: dict = Depends(require_role("partner", "admin"))) -> dict:
    partner, _ = await _partner_of(user["id"], owner_only=True)
    try:
        value = await partners.set_premium_discount(partner["id"], body.discount)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"discount_premium": value}
