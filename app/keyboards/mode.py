from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

MODE_PERSONAL = "mode:personal"
MODE_PAIR = "start_pair"


def mode_keyboard(role=None) -> InlineKeyboardMarkup:
    if role == "parent":
        personal_label = "Личный тест: про ребёнка"
    else:
        personal_label = "Личный тест: про себя"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=personal_label, callback_data=MODE_PERSONAL)],
            [InlineKeyboardButton(text="💬 Совместный тест", callback_data=MODE_PAIR)],
        ]
    )
