"""Клавиатуры (reply/inline)."""
from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from bot.config import settings
from bot.texts import t


def miniapp_button(text: str, path: str = "") -> InlineKeyboardButton | None:
    """Кнопка, открывающая Mini App (если MINIAPP_URL задан)."""
    if not settings.miniapp_url:
        return None
    return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=settings.miniapp_url + path))


def miniapp_kb(text: str, path: str = "") -> InlineKeyboardMarkup | None:
    btn = miniapp_button(text, path)
    return InlineKeyboardMarkup(inline_keyboard=[[btn]]) if btn else None


def consent_kb(lang: str = "ru") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t("btn_consent", lang))]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def main_menu_kb(lang: str = "ru") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t("btn_all", lang)), KeyboardButton(text=t("btn_sub", lang))],
            [KeyboardButton(text=t("btn_raffle", lang))],
            [KeyboardButton(text=t("btn_invite", lang)), KeyboardButton(text=t("btn_help", lang))],
        ],
        resize_keyboard=True,
    )


def receipt_decision_kb(subscription_id: int) -> InlineKeyboardMarkup:
    """Кнопки ✅/❌ под карточкой чека для админа."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"sub:ok:{subscription_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"sub:no:{subscription_id}"),
            ]
        ]
    )


def help_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    """Кнопки под FAQ: связь с админом и жалоба (раздел 3.6)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t("btn_contact_admin", lang), callback_data="help:admin")],
            [InlineKeyboardButton(text=t("btn_complain", lang), callback_data="help:complain")],
        ]
    )


def profile_kb() -> InlineKeyboardMarkup | None:
    """Вход в профиль Mini App из раздела подписки."""
    # HashRouter в Mini App: путь только после «/#/», иначе 404 на статике.
    return miniapp_kb("📱 Открыть приложение", "/#/profile")


def broadcast_confirm_kb() -> InlineKeyboardMarkup:
    """Подтверждение рассылки после предпросмотра (раздел 3.5)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📣 Отправить", callback_data="bc:go"),
                InlineKeyboardButton(text="✖️ Отмена", callback_data="bc:cancel"),
            ]
        ]
    )
