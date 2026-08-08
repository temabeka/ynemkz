"""Витрина: каталог, карточка партнёра, карта."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.auth import get_user
from bot import db

router = APIRouter(dependencies=[Depends(get_user)])


@router.get("/catalog")
async def catalog(category: str | None = None) -> list[dict]:
    rows = await db.fetch(
        """
        SELECT id, name, category, address, discount_premium,
               work_hours, logo_url, is_paused
        FROM partners
        WHERE is_active AND NOT is_paused
          AND ($1::text IS NULL OR category = $1)
        ORDER BY category NULLS LAST, name
        """,
        category,
    )
    return [dict(r) for r in rows]


@router.get("/map")
async def partners_map() -> list[dict]:
    """Пины для карты — только партнёры с координатами."""
    rows = await db.fetch(
        """
        SELECT id, name, category, address, discount_premium, logo_url, lat, lng
        FROM partners
        WHERE is_active AND NOT is_paused AND lat IS NOT NULL AND lng IS NOT NULL
        """
    )
    return [dict(r) for r in rows]


@router.get("/partners/{partner_id}")
async def partner_card(partner_id: int) -> dict:
    row = await db.fetchrow(
        """
        SELECT id, name, category, address, discount_premium,
               work_hours, logo_url, lat, lng
        FROM partners WHERE id = $1 AND is_active
        """,
        partner_id,
    )
    if row is None:
        raise HTTPException(404, "partner not found")
    return dict(row)
