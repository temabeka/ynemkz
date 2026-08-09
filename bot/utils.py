"""Мелкие помощники для сообщений бота."""
from __future__ import annotations

from aiogram import html


def mention(user_id: int, full_name: str | None, username: str | None) -> str:
    """Упоминание пользователя для сообщений админам (HTML parse_mode).

    С username — обычное @упоминание; без него — кликабельная ссылка
    tg://user?id, чтобы админ мог открыть профиль и написать (иначе в тексте
    появлялось «@None»).
    """
    name = html.quote(full_name or "Без имени")
    if username:
        return f"{name} (@{username})"
    return f'{name} (<a href="tg://user?id={user_id}">id {user_id}</a>)'
