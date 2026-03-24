from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

MINI_TEST_CALLBACK_PREFIX = "mini_test:"


def mini_test_keyboard(options: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    inline_keyboard = []
    for code, option_text in options:
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"{code}. {option_text}",
                    callback_data=f"{MINI_TEST_CALLBACK_PREFIX}{code}",
                )
            ]
        )

    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
