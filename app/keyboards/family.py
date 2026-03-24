from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from app.keyboards.observation import OBSERVATION_MENU_TEXT
from app.keyboards.role import ROLE_REFRESH_TEXT

FAMILY_INVITE_CALLBACK = "family_invite"
FAMILY_CONFIRM_PREFIX = "family_confirm:"
FAMILY_DECLINE_PREFIX = "family_decline:"
FAMILY_UNLINK_TEXT = "Отменить семейную связь"
FAMILY_UNLINK_CALLBACK = "family:unlink"
FAMILY_UNLINK_CONFIRM_CALLBACK = "family:unlink:confirm"
FAMILY_UNLINK_CANCEL_CALLBACK = "family:unlink:cancel"
FAMILY_STATUS_TEXT = "Статус семьи"
FAMILY_INVITE_PARENT_TEXT = "Пригласить подростка"
FAMILY_INVITE_TEEN_TEXT = "Пригласить родителя"
FAMILY_PSYCHOLOGIST_TEXT = "Связь с психологом"
MAIN_MENU_TEST_TEXT = "🧪 Пройти тест"
MAIN_MENU_RESULT_TEXT = "📊 Мой результат"
PROGRESS_MENU_TEXT = "🏆 Мой прогресс"


def family_invite_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=FAMILY_INVITE_PARENT_TEXT, callback_data=FAMILY_INVITE_CALLBACK)],
        ]
    )


def family_confirm_keyboard(*, token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Подключиться",
                    callback_data=f"{FAMILY_CONFIRM_PREFIX}{token}",
                ),
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data=f"{FAMILY_DECLINE_PREFIX}{token}",
                ),
            ]
        ]
    )


def family_unlink_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да, отменить",
                    callback_data=FAMILY_UNLINK_CONFIRM_CALLBACK,
                )
            ],
            [
                InlineKeyboardButton(
                    text="Нет",
                    callback_data=FAMILY_UNLINK_CANCEL_CALLBACK,
                )
            ],
        ]
    )


def psychologist_link_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Перейти к @nasya_psy", url="https://t.me/nasya_psy")]
        ]
    )


def family_status_keyboard(role: str | None, has_family_link: bool) -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = []

    if role == "teen":
        rows.append([KeyboardButton(text=MAIN_MENU_TEST_TEXT)])
        rows.append([KeyboardButton(text=MAIN_MENU_RESULT_TEXT)])
        rows.append([KeyboardButton(text=PROGRESS_MENU_TEXT)])
        if has_family_link:
            rows.append([KeyboardButton(text=FAMILY_STATUS_TEXT)])
            rows.append([KeyboardButton(text=OBSERVATION_MENU_TEXT)])
            rows.append([KeyboardButton(text=FAMILY_PSYCHOLOGIST_TEXT)])
            rows.append([KeyboardButton(text=FAMILY_UNLINK_TEXT)])
            rows.append([KeyboardButton(text=ROLE_REFRESH_TEXT)])
        else:
            rows.append([KeyboardButton(text=FAMILY_INVITE_TEEN_TEXT)])
            rows.append([KeyboardButton(text=FAMILY_STATUS_TEXT)])
            rows.append([KeyboardButton(text=ROLE_REFRESH_TEXT)])
        return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

    # Keep non-teen layout as it was before teen-specific cleanup.
    rows = [
        [KeyboardButton(text=MAIN_MENU_TEST_TEXT)],
        [KeyboardButton(text=MAIN_MENU_RESULT_TEXT)],
        [KeyboardButton(text=PROGRESS_MENU_TEXT)],
        [KeyboardButton(text=FAMILY_STATUS_TEXT), KeyboardButton(text=ROLE_REFRESH_TEXT)],
    ]

    if has_family_link:
        rows.append([KeyboardButton(text=OBSERVATION_MENU_TEXT)])
        rows.append([KeyboardButton(text=FAMILY_PSYCHOLOGIST_TEXT)])
        rows.append([KeyboardButton(text=FAMILY_UNLINK_TEXT)])
    elif role == "parent":
        rows.append([KeyboardButton(text=FAMILY_INVITE_PARENT_TEXT)])

    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)
