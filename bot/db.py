"""Слой доступа к данным: asyncpg pool для SQL + supabase client для Storage.

Общий модуль — им пользуется и бот, и (в Фазе 2) FastAPI.
"""
from __future__ import annotations

from typing import Any, Optional

import asyncpg
from supabase import Client, create_client

from bot.config import settings

_pool: Optional[asyncpg.Pool] = None
_supabase: Optional[Client] = None


async def init_pool() -> asyncpg.Pool:
    """Создать пул подключений к Postgres (idempotent)."""
    global _pool
    if _pool is None:
        # min_size=4: параллельные запросы Mini App не ждут создания
        # TLS-коннектов к Supabase pooler (дорого, особенно межрегионально).
        # timezone: now()::date и подобные в SQL считаются локальным днём
        # Экибастуза, а не UTC (статистика по дням, «сегодня» в отчётах).
        _pool = await asyncpg.create_pool(
            settings.database_url,
            min_size=4,
            max_size=10,
            server_settings={"timezone": "Asia/Almaty"},
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Pool не инициализирован — вызови init_pool()")
    return _pool


def supabase() -> Client:
    """Клиент Supabase (Storage: чеки Kaspi, логотипы)."""
    global _supabase
    if _supabase is None:
        _supabase = create_client(settings.supabase_url, settings.supabase_key)
    return _supabase


# --- Тонкие хелперы поверх пула -------------------------------------------------

async def fetch(query: str, *args: Any) -> list[asyncpg.Record]:
    async with pool().acquire() as conn:
        return await conn.fetch(query, *args)


async def fetchrow(query: str, *args: Any) -> Optional[asyncpg.Record]:
    async with pool().acquire() as conn:
        return await conn.fetchrow(query, *args)


async def fetchval(query: str, *args: Any) -> Any:
    async with pool().acquire() as conn:
        return await conn.fetchval(query, *args)


async def execute(query: str, *args: Any) -> str:
    async with pool().acquire() as conn:
        return await conn.execute(query, *args)
