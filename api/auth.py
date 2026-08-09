"""Авторизация Mini App: валидация Telegram initData (раздел 4.5).

Mini App шлёт initData в заголовке `Authorization: tma <initData>`.
Подпись: HMAC-SHA256(data_check_string, key), где key = HMAC-SHA256("WebAppData", bot_token).
Паролей нет — telegram_id из подписанных данных, роль из users.
Кэш валидации 5 минут, чтобы не считать HMAC и не ходить в БД на каждый запрос.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from fastapi import Depends, Header, HTTPException

from bot import db
from bot.config import settings

AUTH_TTL = 300  # секунд
# Telegram подписывает initData при открытии Mini App и не обновляет, пока
# webview жив: при лимите в час у долго открытого приложения все запросы
# падали в 401. 12 часов — баланс между удобством и окном для replay-атаки.
MAX_AGE = 12 * 3600

_cache: dict[str, tuple[float, dict]] = {}  # initData → (ts, user)


def _validate_init_data(init_data: str, bot_token: str) -> dict:
    """Проверить подпись initData, вернуть объект user из него. Бросает ValueError."""
    pairs = dict(parse_qsl(init_data, strict_parsing=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise ValueError("no hash")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, received_hash):
        raise ValueError("bad signature")

    auth_date = int(pairs.get("auth_date", 0))
    if time.time() - auth_date > MAX_AGE:
        raise ValueError("stale initData")

    return json.loads(pairs["user"])


async def get_user(authorization: str = Header(default="")) -> dict:
    """FastAPI dependency: валидный пользователь из БД + роль."""
    scheme, _, init_data = authorization.partition(" ")
    if scheme.lower() != "tma" or not init_data:
        raise HTTPException(401, "expected 'Authorization: tma <initData>'")

    cached = _cache.get(init_data)
    if cached and time.time() - cached[0] < AUTH_TTL:
        return cached[1]

    try:
        tg_user = _validate_init_data(init_data, settings.bot_token)
    except (ValueError, KeyError, json.JSONDecodeError):
        raise HTTPException(401, "invalid initData")

    row = await db.fetchrow("SELECT * FROM users WHERE id = $1", tg_user["id"])
    if row is None:
        # Регистрация — в боте (телефон + согласие). Mini App шлёт в бот.
        raise HTTPException(403, "not registered, start the bot first")
    if row["is_banned"]:
        raise HTTPException(403, "banned")

    user = dict(row)
    user["role"] = "admin" if user["id"] in settings.admin_id_set else user["role"]

    if len(_cache) > 10_000:  # незатейливая защита от распухания
        _cache.clear()
    _cache[init_data] = (time.time(), user)
    return user


def require_role(*roles: str):
    """Dependency-фабрика: доступ только для перечисленных ролей."""
    async def checker(user: dict = Depends(get_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(403, "forbidden")
        return user
    return checker
