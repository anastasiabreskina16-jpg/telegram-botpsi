from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.services.dialogue_test_data import (
    PHASE3_MAX_CHOICES,
    PHASE3_SCENARIOS,
    PHASE4_REQUIRED_COUNT,
    PHASE4_VALUES,
)

# ── Callback prefixes ─────────────────────────────────────────────────────────

PAIR_MODE_PREFIX = "pair_mode:"
PAIR_MODE_START_PARENT = f"{PAIR_MODE_PREFIX}start_parent"
PAIR_MODE_START_TEEN = f"{PAIR_MODE_PREFIX}start_teen"
PAIR_MODE_ENTER_CODE = f"{PAIR_MODE_PREFIX}enter_code"
PAIR_MODE_BACK = f"{PAIR_MODE_PREFIX}back"

PAIR_CANCEL_REQUEST_PREFIX = "pair_cancel:"
PAIR_CANCEL_YES_PREFIX = "pair_cancel_yes:"
PAIR_CANCEL_NO_PREFIX = "pair_cancel_no:"

PAIR_START_TEST = "pair_start_test"
PAIR_RESULT_DISCUSS = "pair_result:discuss"
PAIR_RESULT_NEXT = "pair_result:next"
PAIR_MISSION_DONE = "pair_mission:done"
PAIR_CHECK_STATUS = "pair_status:check"
PAIR_RESULT_MY = "pair_result:my"
PAIR_RESULT_RESTART = "pair_result:restart"
PAIR_PING_PARTNER = "pair_retention:ping_partner"
PAIR_RESUME_FLOW = "pair_retention:resume_flow"

PAIR_PHASE1_SCORE_PREFIX = "pair_p1s:"
PAIR_PHASE2_ANSWER_PREFIX = "pair_p2:"

PAIR_PHASE3_SCENARIO_TOGGLE_PREFIX = "pair_p3pick:"
PAIR_PHASE3_SCENARIO_DONE = "pair_p3done"
PAIR_PHASE3_ANSWER_PREFIX = "pair_p3ans:"

PAIR_PHASE4_VALUE_TOGGLE_PREFIX = "pair_p4pick:"
PAIR_PHASE4_DONE = "pair_p4done"

RESUME_PAIR_TEST_TEXT = "▶️ Продолжить тест"

# ── Entry point keyboard ──────────────────────────────────────────────────────

def pair_entry_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [        [InlineKeyboardButton(text="Начать как подросток 🔗", callback_data=PAIR_MODE_START_TEEN)],        [InlineKeyboardButton(text="Начать как родитель", callback_data=PAIR_MODE_START_PARENT)],
        [InlineKeyboardButton(text="У меня уже есть код", callback_data=PAIR_MODE_ENTER_CODE)],
    ]
    rows.append([InlineKeyboardButton(text="◀ Назад", callback_data=PAIR_MODE_BACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pair_session_status_keyboard(*, session_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="Отменить парную сессию",
                callback_data=f"{PAIR_CANCEL_REQUEST_PREFIX}{session_id}",
            )],
        ]
    )


def pair_cancel_confirm_keyboard(*, session_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Да, отменить", callback_data=f"{PAIR_CANCEL_YES_PREFIX}{session_id}")],
            [InlineKeyboardButton(text="Нет", callback_data=f"{PAIR_CANCEL_NO_PREFIX}{session_id}")],
        ]
    )


def pair_join_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Начать Диалог о выборе", callback_data=PAIR_START_TEST)],
        ]
    )


def pair_waiting_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Проверить статус", callback_data=PAIR_CHECK_STATUS)],
            [InlineKeyboardButton(text="📩 Напомнить", callback_data=PAIR_PING_PARTNER)],
        ]
    )


def resume_pair_test_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=RESUME_PAIR_TEST_TEXT)]],
        resize_keyboard=True,
    )


def ping_partner_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📩 Напомнить", callback_data=PAIR_PING_PARTNER)],
        ]
    )


def resume_flow_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Продолжить", callback_data=PAIR_RESUME_FLOW)],
        ]
    )


def pair_phase1_score_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for start in (1, 6):
        row: list[InlineKeyboardButton] = []
        for score in range(start, start + 5):
            row.append(
                InlineKeyboardButton(
                    text=str(score),
                    callback_data=f"{PAIR_PHASE1_SCORE_PREFIX}{score}",
                )
            )
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pair_phase2_answer_keyboard(question_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=label,
                callback_data=f"{PAIR_PHASE2_ANSWER_PREFIX}{question_id}:{value}",
            )]
            for value, label in {
                1: "1 — совсем не похоже",
                2: "2 — скорее не похоже",
                3: "3 — скорее похоже",
                4: "4 — очень похоже",
            }.items()
        ]
    )


def pair_phase3_scenario_select_keyboard(selected_ids: list[int]) -> InlineKeyboardMarkup:
    selected = set(selected_ids)
    rows: list[list[InlineKeyboardButton]] = []
    for scenario in PHASE3_SCENARIOS:
        sid = scenario["id"]
        marker = "✅" if sid in selected else "⬜"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{marker} {scenario['title']}",
                    callback_data=f"{PAIR_PHASE3_SCENARIO_TOGGLE_PREFIX}{sid}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=f"Готово ({len(selected)}/{PHASE3_MAX_CHOICES})",
                callback_data=PAIR_PHASE3_SCENARIO_DONE,
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pair_phase3_answer_keyboard(scenario_id: int, options: list[str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{idx}. {text}",
                    callback_data=f"{PAIR_PHASE3_ANSWER_PREFIX}{scenario_id}:{idx}",
                )
            ]
            for idx, text in enumerate(options, start=1)
        ]
    )


def pair_phase4_values_keyboard(selected_ids: list[int]) -> InlineKeyboardMarkup:
    selected = set(selected_ids)
    rows: list[list[InlineKeyboardButton]] = []
    for idx, value in enumerate(PHASE4_VALUES, start=1):
        marker = "✅" if idx in selected else "⬜"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{marker} {value}",
                    callback_data=f"{PAIR_PHASE4_VALUE_TOGGLE_PREFIX}{idx}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=f"Подтвердить выбор ({len(selected)}/{PHASE4_REQUIRED_COUNT})",
                callback_data=PAIR_PHASE4_DONE,
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pair_result_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📈 Мой результат", callback_data=PAIR_RESULT_MY)],
            [InlineKeyboardButton(text="🔁 Пройти ещё раз", callback_data=PAIR_RESULT_RESTART)],
            [InlineKeyboardButton(text="✅ Выполнили", callback_data=PAIR_MISSION_DONE)],
            [InlineKeyboardButton(text="Что обсудить вместе", callback_data=PAIR_RESULT_DISCUSS)],
            [InlineKeyboardButton(text="Следующий шаг", callback_data=PAIR_RESULT_NEXT)],
        ]
    )
