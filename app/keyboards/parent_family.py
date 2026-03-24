from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

PARENT_FAMILY_INVITE_TEXT = "Пригласить ребенка"


def parent_family_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=PARENT_FAMILY_INVITE_TEXT)],
        ],
        resize_keyboard=True,
    )
