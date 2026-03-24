from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

ROLE_CALLBACK_PREFIX = "select_role:"
ROLE_REFRESH_TEXT = "Обновить роль"
PARENT_FAMILY_TITLES = ("мама", "папа")
TEEN_FAMILY_TITLES = ("дочь", "сын", "подросток")

ROLE_LABELS: dict[str, str] = {
    "teen": "🧒 Подросток",
    "parent": "👨‍👩‍👧 Родитель",
}


def role_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=label,
                callback_data=f"{ROLE_CALLBACK_PREFIX}{role}",
            )
        ]
        for role, label in ROLE_LABELS.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def family_title_keyboard(role: str) -> ReplyKeyboardMarkup:
    if role == "parent":
        options = PARENT_FAMILY_TITLES
    else:
        options = TEEN_FAMILY_TITLES

    rows = [[KeyboardButton(text=option)] for option in options]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)
