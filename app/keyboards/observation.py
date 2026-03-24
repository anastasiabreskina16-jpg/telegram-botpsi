from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

OBSERVATION_MENU_TEXT = "Дневник наблюдений"
OBS_ADD_TEXT = "Добавить наблюдение"
OBS_MY_TEXT = "Мои записи"
OBS_OVERVIEW_TEXT = "Общая картина"
OBS_WEEKLY_TEXT = "Сводка за неделю"
OBS_PAIR_TASK_TEXT = "Парная задача"
OBS_BACK_TEXT = "Назад"  # used in inline keyboards only
OBS_BACK_TO_FAMILY_TEXT = "Назад в семейное меню"  # reply: diary → family
OBS_BACK_TO_DIARY_TEXT = "Назад к дневнику"  # reply: pair-task → diary

OBS_PAIR_TASK_GET_TEXT = "Получить задачу"
OBS_PAIR_TASK_BY_NOTES_TEXT = "Задача по наблюдениям"
OBS_PAIR_TASK_ACTIVE_TEXT = "Активная задача"
OBS_PAIR_TASK_COMPLETE_TEXT = "Завершить задачу"
OBS_PAIR_TASK_HISTORY_TEXT = "История задач"

OBS_CATEGORY_PREFIX = "obs_cat:"
OBS_CATEGORY_BACK = "obs_cat:back"
OBS_ENERGY_PREFIX = "obs_energy:"
OBS_ENERGY_SKIP = "obs_energy:skip"
OBS_CONFIRM_SAVE = "obs_confirm:save"
OBS_CONFIRM_CANCEL = "obs_confirm:cancel"
OBS_MY_LIMIT_PREFIX = "obs_my_limit:"
OBS_PAIR_TASK_DONE_PREFIX = "obs_pair_task_done:"
OBS_PAIR_TASK_LATER_PREFIX = "obs_pair_task_later:"
OBS_PAIR_TASK_OTHER_PREFIX = "obs_pair_task_other:"
OBS_PAIR_TASK_INVITE_ACCEPT_PREFIX = "obs_pair_task_invite_accept:"
OBS_PAIR_TASK_INVITE_LATER_PREFIX = "obs_pair_task_invite_later:"


def observation_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=OBS_ADD_TEXT)],
            [KeyboardButton(text=OBS_MY_TEXT)],
            [KeyboardButton(text=OBS_OVERVIEW_TEXT)],
            [KeyboardButton(text=OBS_WEEKLY_TEXT)],
            [KeyboardButton(text=OBS_PAIR_TASK_TEXT)],
            [KeyboardButton(text=OBS_BACK_TO_FAMILY_TEXT)],
        ],
        resize_keyboard=True,
    )


def observation_pair_task_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=OBS_PAIR_TASK_GET_TEXT)],
            [KeyboardButton(text=OBS_PAIR_TASK_BY_NOTES_TEXT)],
            [KeyboardButton(text=OBS_PAIR_TASK_ACTIVE_TEXT)],
            [KeyboardButton(text=OBS_PAIR_TASK_COMPLETE_TEXT)],
            [KeyboardButton(text=OBS_PAIR_TASK_HISTORY_TEXT)],
            [KeyboardButton(text=OBS_BACK_TO_DIARY_TEXT)],
        ],
        resize_keyboard=True,
    )


def observation_categories_keyboard(categories: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for code, label in categories:
        rows.append([InlineKeyboardButton(text=label, callback_data=f"{OBS_CATEGORY_PREFIX}{code}")])
    rows.append([InlineKeyboardButton(text=OBS_BACK_TEXT, callback_data=OBS_CATEGORY_BACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def observation_energy_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1", callback_data=f"{OBS_ENERGY_PREFIX}1"),
                InlineKeyboardButton(text="2", callback_data=f"{OBS_ENERGY_PREFIX}2"),
                InlineKeyboardButton(text="3", callback_data=f"{OBS_ENERGY_PREFIX}3"),
                InlineKeyboardButton(text="4", callback_data=f"{OBS_ENERGY_PREFIX}4"),
                InlineKeyboardButton(text="5", callback_data=f"{OBS_ENERGY_PREFIX}5"),
            ],
            [InlineKeyboardButton(text="Пропустить", callback_data=OBS_ENERGY_SKIP)],
        ]
    )


def observation_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Сохранить", callback_data=OBS_CONFIRM_SAVE)],
            [InlineKeyboardButton(text="Отменить", callback_data=OBS_CONFIRM_CANCEL)],
        ]
    )


def observation_my_records_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Последние 5", callback_data=f"{OBS_MY_LIMIT_PREFIX}5"),
                InlineKeyboardButton(text="Последние 10", callback_data=f"{OBS_MY_LIMIT_PREFIX}10"),
            ],
        ]
    )


def observation_pair_task_action_keyboard(*, task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Выполнили", callback_data=f"{OBS_PAIR_TASK_DONE_PREFIX}{task_id}")],
            [InlineKeyboardButton(text="Отложить", callback_data=f"{OBS_PAIR_TASK_LATER_PREFIX}{task_id}")],
            [InlineKeyboardButton(text="Другая задача", callback_data=f"{OBS_PAIR_TASK_OTHER_PREFIX}{task_id}")],
        ]
    )


def observation_pair_task_invite_keyboard(*, task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Принять задачу", callback_data=f"{OBS_PAIR_TASK_INVITE_ACCEPT_PREFIX}{task_id}")],
            [InlineKeyboardButton(text="Позже", callback_data=f"{OBS_PAIR_TASK_INVITE_LATER_PREFIX}{task_id}")],
        ]
    )
