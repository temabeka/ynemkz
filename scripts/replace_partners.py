"""Одноразовая замена партнёров (август 2026): удаляет всех прошлых
(вместе с тестовыми визитами) и заводит 6 новых из partners/parnters.txt
с логотипами и координатами (геокодинг Nominatim по адресу в Экибастузе).

Запуск из корня проекта: .venv/bin/python scripts/replace_partners.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # корень проекта

from bot import db
from bot.services import storage

PARTNERS = [
    # (имя, категория, адрес, % по подписке, файл логотипа)
    ("Mofani",      "Еда",         "Кеншілер, 126",                   30, "mofanicoffee.jpg"),
    ("Yami Yami",   "Еда",         "М. Әуезова, 47Б, парк Maxi Mall", 15, "yamiyami.jpg"),
    ("Yumi Market", "Шопинг",      "Мәшһүр Жүсіпа, 48",                7, "yumimarket.jpg"),
    ("Tor.ekb",     "Еда",         "ул. 50 лет города, 5",            15, "torekb.jpg"),
    ("La Roza",     "Шопинг",      "М. Әуезова, 42",                   7, "la roza.jpg"),
    ("Jump Park",   "Развлечения", "Королёва, 78/1",                   5, "jumppark.jpg"),
]

# Упрощённые запросы для геокодера (без корпусов и уточнений)
GEO_QUERY = {
    "Mofani":      "Кеншилер 126, Экибастуз",
    "Yami Yami":   "Ауэзова 47Б, Экибастуз",
    "Yumi Market": "Машхур Жусупа 48, Экибастуз",
    "Tor.ekb":     "улица 50 лет города 5, Экибастуз",
    "La Roza":     "Ауэзова 42, Экибастуз",
    "Jump Park":   "Королева 78, Экибастуз",
}


def geocode(query: str) -> tuple[float, float] | None:
    url = ("https://nominatim.openstreetmap.org/search?format=json&limit=1&q="
           + urllib.parse.quote(query))
    req = urllib.request.Request(url, headers={"User-Agent": "ynemkz-setup/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.load(resp)
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:  # noqa: BLE001 — геокодинг не критичен
        print(f"  геокодинг не удался: {e}")
    return None


async def main() -> None:
    await db.init_pool()
    # Прошлые партнёры и всё, что на них ссылается (тестовые данные)
    for q in ("DELETE FROM redemptions",
              "DELETE FROM partner_edits",
              "DELETE FROM staff_invites",
              "DELETE FROM partner_staff",
              "DELETE FROM partners"):
        res = await db.execute(q)
        print(res, "—", q)

    for name, cat, addr, pct, logo in PARTNERS:
        pid = await db.fetchval(
            """INSERT INTO partners (name, category, address, discount_premium, is_active, is_paused)
               VALUES ($1, $2, $3, $4, true, false) RETURNING id""",
            name, cat, addr, pct,
        )
        with open(f"partners/{logo}", "rb") as f:
            url = await asyncio.to_thread(storage.upload_logo, f.read(), pid)
        coords = await asyncio.to_thread(geocode, GEO_QUERY[name])
        if coords:
            await db.execute(
                "UPDATE partners SET logo_url = $2, lat = $3, lng = $4 WHERE id = $1",
                pid, url, coords[0], coords[1],
            )
        else:
            await db.execute("UPDATE partners SET logo_url = $2 WHERE id = $1", pid, url)
        print(f"#{pid} {name} — {pct}%, логотип ок, координаты: {coords or 'НЕ найдены'}")
        await asyncio.sleep(1)  # лимит Nominatim — 1 запрос/сек

    rows = await db.fetch("SELECT id, name, discount_premium, lat, lng FROM partners ORDER BY id")
    print("\nИтог:")
    for r in rows:
        print(f"  #{r['id']} {r['name']} −{r['discount_premium']}% "
              f"{'📍' if r['lat'] else '⚠️ без координат'}")
    await db.close_pool()


asyncio.run(main())
