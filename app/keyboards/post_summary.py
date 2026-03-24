from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

POST_SUMMARY_RESTART_PREFIX = "ps_restart:"
POST_SUMMARY_EXTENDED_PREFIX = "ps_extended:"
POST_SUMMARY_MENU_PREFIX = "ps_menu:"


def post_summary_keyboard(*, session_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Пройти заново",
                    callback_data=f"{POST_SUMMARY_RESTART_PREFIX}{session_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Получить расширенный разбор",
                    callback_data=f"{POST_SUMMARY_EXTENDED_PREFIX}{session_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Вернуться в меню",
                    callback_data=f"{POST_SUMMARY_MENU_PREFIX}{session_id}",
                )
            ],
        ]
    )
