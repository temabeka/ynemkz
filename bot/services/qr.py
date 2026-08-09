"""Генерация кодов активации и QR-наклеек для касс.

- gen_code(): короткий человекочитаемый код (фолбэк-вариант A).
- partner_qr(): PNG с deep link t.me/bot?start=p_<id> для наклейки (вариант C).
- daily_sign(): «знак дня» — эмодзи, которое утром рассылается партнёрам и
  показывается на экране активации (анти-фрод, раздел 3.2).
"""
from __future__ import annotations

import io
import secrets
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import qrcode
from PIL import Image, ImageDraw, ImageFont
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers.pil import RoundedModuleDrawer

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
_BRAND_YELLOW = (245, 236, 0)      # #f5ec00 — фон Mini App и наклейки
_INK = (12, 12, 12)

# Без похожих символов (0/O, 1/I) — чтобы кассир не ошибся при вводе.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_SIGNS = ["🔴", "🟢", "🔵", "🟡", "🟣", "🟠", "⭐️", "❤️", "🔶", "🔷", "🍀", "⚡️"]


def gen_code(length: int = 6) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def gen_client_token() -> str:
    """Токен персонального QR клиента (вариант D, раздел 3.2).

    URL-safe алфавит [A-Za-z0-9_-] — токен целиком влезает в startapp=c_<token>.
    """
    return secrets.token_urlsafe(9)  # 12 символов


def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    name = "Montserrat-Bold.ttf" if bold else "Montserrat-Medium.ttf"
    return ImageFont.truetype(str(_ASSETS / name), size)


def _center_text(draw: ImageDraw.ImageDraw, y: int, text: str, font: ImageFont.FreeTypeFont,
                 canvas_w: int, fill: tuple[int, int, int] = _INK) -> int:
    """Рисует строку по центру, возвращает y нижней кромки."""
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(((canvas_w - (box[2] - box[0])) // 2 - box[0], y - box[1]), text, font=font, fill=fill)
    return y + (box[3] - box[1])


def partner_qr(bot_username: str, partner_id: int, app_name: str = "app",
               partner_name: str | None = None, logo_bytes: bytes | None = None) -> bytes:
    """PNG наклейки на кассу: фирменный жёлтый фон, QR с логотипом заведения, инструкция.

    QR ведёт на Direct Link Mini App: t.me/<bot>/<app>?startapp=p_<id> —
    экран активации открывается сразу; незарегистрированных Mini App отправит
    в бот (фолбэк ?start=p_<id>). Печать ~9×12 см при 300 dpi.
    logo_bytes — логотип заведения для центра QR; коррекция H (30%) позволяет
    закрыть центр без потери читаемости. Сеть здесь не трогаем — байты качает
    вызывающий (хэндлеры асинхронные, а генерация выполняется в thread pool).
    """
    link = f"https://t.me/{bot_username}/{app_name}?startapp=p_{partner_id}"

    qr_code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, border=0, box_size=22)
    qr_code.add_data(link)
    qr_img = qr_code.make_image(
        image_factory=StyledPilImage,
        module_drawer=RoundedModuleDrawer(),
        fill_color=_INK,
        back_color=(255, 255, 255),
    ).convert("RGB")

    # Логотип заведения в центре: белая скруглённая подложка + скруглённая картинка
    if logo_bytes:
        try:
            logo = Image.open(io.BytesIO(logo_bytes)).convert("RGB")
        except Exception:
            logo = None
        if logo is not None:
            side = min(logo.size)
            logo = logo.crop(((logo.width - side) // 2, (logo.height - side) // 2,
                              (logo.width + side) // 2, (logo.height + side) // 2))
            hole = int(qr_img.width * 0.30)          # белая подложка ≤ 30% — предел коррекции H
            inner = int(hole * 0.86)
            logo = logo.resize((inner, inner), Image.LANCZOS)

            pad_box = Image.new("RGB", (hole, hole), (255, 255, 255))
            mask_pad = Image.new("L", (hole, hole), 0)
            ImageDraw.Draw(mask_pad).rounded_rectangle((0, 0, hole, hole), radius=hole // 5, fill=255)
            mask_logo = Image.new("L", (inner, inner), 0)
            ImageDraw.Draw(mask_logo).rounded_rectangle((0, 0, inner, inner), radius=inner // 5, fill=255)

            cx = (qr_img.width - hole) // 2
            qr_img.paste(pad_box, (cx, cx), mask_pad)
            off = cx + (hole - inner) // 2
            qr_img.paste(logo, (off, off), mask_logo)

    W, H = 1080, 1440
    sticker = Image.new("RGB", (W, H), _BRAND_YELLOW)
    draw = ImageDraw.Draw(sticker)

    # Логотип сверху
    logo = Image.open(_ASSETS / "logo.png").convert("RGBA")
    logo_w = 460
    logo = logo.resize((logo_w, int(logo.height * logo_w / logo.width)), Image.LANCZOS)
    sticker.paste(logo, ((W - logo.width) // 2, 56), logo)
    y = 56 + logo.height + 40

    # Белая карточка со скруглением и QR внутри
    qr_size, pad = 690, 40
    card = qr_size + pad * 2
    card_x, card_y = (W - card) // 2, y
    draw.rounded_rectangle((card_x, card_y, card_x + card, card_y + card), radius=48,
                           fill=(255, 255, 255))
    sticker.paste(qr_img.resize((qr_size, qr_size), Image.LANCZOS), (card_x + pad, card_y + pad))
    y = card_y + card + 52

    # Имя заведения и инструкция
    if partner_name:
        y = _center_text(draw, y, partner_name, _font(52), W) + 26
    y = _center_text(draw, y, "Наведи камеру — скидка сразу", _font(44), W) + 18
    _center_text(draw, y, f"Ynem · дисконт-клуб Экибастуза · @{bot_username}",
                 _font(30, bold=False), W, fill=(80, 76, 0))

    buf = io.BytesIO()
    sticker.save(buf, format="PNG")
    return buf.getvalue()


def fetch_logo(url: str | None, timeout: int = 10) -> bytes | None:
    """Скачивает логотип для центра QR. Синхронная — звать через asyncio.to_thread.

    Ошибки глотаем: наклейка без логотипа лучше, чем ошибка вместо наклейки.
    """
    if not url:
        return None
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 — url из нашей БД
            return resp.read()
    except Exception:
        return None


def daily_sign(day: date | None = None) -> str:
    """Детерминированный знак дня — одинаковый у всех, меняется каждый день.

    День считаем по Asia/Almaty, а не по TZ сервера: иначе знак «переключался»
    бы среди рабочего дня или ночью не в полночь Экибастуза.
    """
    day = day or datetime.now(ZoneInfo("Asia/Almaty")).date()
    return _SIGNS[day.toordinal() % len(_SIGNS)]
