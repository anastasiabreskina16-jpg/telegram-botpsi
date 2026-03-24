from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

RESTART_TEST_CALLBACK = "restart_test"


def result_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔁 Пройти тест снова",
                    callback_data=RESTART_TEST_CALLBACK,
                )
            ]
        ]
    )
