"""Pair test handler for the new scenario "Dialog about choice"."""
from __future__ import annotations

import asyncio
import logging
import time

from aiogram import Dispatcher, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.db.session import AsyncSessionLocal
from app.keyboards.pair_test import (
    PAIR_CHECK_STATUS,
    PAIR_CANCEL_NO_PREFIX,
    PAIR_CANCEL_REQUEST_PREFIX,
    PAIR_CANCEL_YES_PREFIX,
    PAIR_MISSION_DONE,
    PAIR_MODE_BACK,
    PAIR_MODE_ENTER_CODE,
    PAIR_MODE_START_PARENT,
    PAIR_MODE_START_TEEN,
    PAIR_PHASE1_SCORE_PREFIX,
    PAIR_PHASE2_ANSWER_PREFIX,
    PAIR_PHASE3_ANSWER_PREFIX,
    PAIR_PHASE3_SCENARIO_DONE,
    PAIR_PHASE3_SCENARIO_TOGGLE_PREFIX,
    PAIR_PHASE4_DONE,
    PAIR_PHASE4_VALUE_TOGGLE_PREFIX,
    PAIR_RESULT_DISCUSS,
    PAIR_RESULT_MY,
    PAIR_RESULT_NEXT,
    PAIR_RESULT_RESTART,
    PAIR_PING_PARTNER,
    PAIR_RESUME_FLOW,
    PAIR_START_TEST,
    RESUME_PAIR_TEST_TEXT,
    pair_cancel_confirm_keyboard,
    pair_entry_keyboard,
    pair_join_confirm_keyboard,
    pair_phase1_score_keyboard,
    pair_phase2_answer_keyboard,
    pair_phase3_answer_keyboard,
    pair_phase3_scenario_select_keyboard,
    pair_phase4_values_keyboard,
    pair_result_keyboard,
    pair_session_status_keyboard,
    pair_waiting_keyboard,
)
from app.data.pair_questions import get_phase_question, get_phase_questions_for_role
from app.services.dialogue_test_data import (
    PHASE2_TOTAL_QUESTIONS,
    PHASE3_MAX_CHOICES,
    PHASE3_MIN_CHOICES,
    PHASE3_SCENARIOS_BY_ID,
    PHASE4_REQUIRED_COUNT,
)
from app.services.family_service import get_family_for_user
from app.services.pair_analysis_service import build_phase2_comparison_report
from app.services.pair_report_service import (
    DISCUSSION_QUESTIONS,
    NEXT_STEPS_TEXT,
    build_dialogue_report,
)
from app.services.pair_test_service import (
    _CANCELLABLE_STATUSES,
    cancel_pair_session,
    create_pair_session,
    get_active_pair_session_for_user,
    get_dialogue_progress,
    get_pair_session_by_id,
    get_phase2_answers_for_role,
    get_phase3_answers_for_role,
    get_phase3_scenario_result,
    get_phase3_selected_scenarios,
    get_phase4_summary,
    get_phase4_values_for_role,
    is_phase3_selection_ready,
    join_pair_session,
    mark_role_done,
    process_phase2_answer_sync,
    reset_phase2_sync_state,
    save_phase1_score,
    save_phase1_word,
    save_phase3_answer,
    save_phase3_selected_scenarios,
    save_phase4_values,
    set_phase3_selection_ready,
)
from app.services.pair_engine import format_message, get_current_step, try_transition
from app.services.result_service import build_result_text, get_last_result
from app.services.retention_service import ping_partner
from app.services.segment_service import track_user_event
from app.services.user_service import get_or_create_user, get_user_role
from app.services.pair_service import build_invite_link, create_pair_session as _create_pair_invite
from app.states.pair_test import PairTest, PairTestStates
from app.states.registration import RegistrationStates
from app.texts import PAIR_TEXTS, TEXTS

log = logging.getLogger(__name__)
router = Router(name="pair_test")
DEBOUNCE_SECONDS = 2


@router.callback_query(F.data == "start_pair")
async def start_pair_test(callback: CallbackQuery, state: FSMContext) -> None:
    """Global pair entrypoint: works even if user is stuck in another FSM state."""
    if callback.message is None:
        return
    await callback.answer()
    await state.clear()
    await state.update_data(mode="pair_test")
    await show_pair_entry(callback.message, state)


def _parse_session_id_from_callback(data: str | None, prefix: str) -> int | None:
    if data is None or not data.startswith(prefix):
        return None
    raw = data[len(prefix):].strip()
    if not raw.isdigit():
        return None
    session_id = int(raw)
    if session_id <= 0:
        return None
    return session_id


def _pair_status_label(status: str) -> str:
    labels = {
        "pending": "ожидает подключения подростка",
        "active": "активна",
        "parent_done": "родитель завершил все фазы",
        "teen_done": "подросток завершил все фазы",
        "completed": "завершена",
        "cancelled": "отменена",
        "expired": "истекла",
    }
    return labels.get(status, status)


def _build_pair_status_text(pair_session) -> str:
    lines = [
        f"Код Диалога о выборе: <b>{pair_session.pair_code}</b>",
        f"Статус: {_pair_status_label(pair_session.status)}",
    ]
    if pair_session.status == "pending":
        lines.append("Подросток пока не подключился.")
    elif pair_session.status == "active":
        lines.append(f"{PAIR_TEXTS['session_active']}\nПрогресс зависит от действий участников.")
    elif pair_session.status in ("parent_done", "teen_done"):
        lines.append("Один участник уже завершил все 4 фазы. Ожидаем второго.")
    elif pair_session.status == "completed":
        lines.append("Оба участника завершили Диалог о выборе.")
    return "\n".join(lines)


async def _answer_once(
    state: FSMContext,
    message: Message,
    *,
    flag_key: str,
    text: str,
) -> None:
    data = await state.get_data()
    if data.get(flag_key):
        return
    await message.answer(text, reply_markup=pair_waiting_keyboard())
    await state.update_data(**{flag_key: True})


def _phase3_selection_action(*, role: str, teen_ready: bool, parent_ready: bool) -> str:
    if teen_ready and parent_ready:
        return "answering"

    role_ready = teen_ready if role == "teen" else parent_ready
    if role_ready:
        return "waiting"
    return "selecting"


def format_question(text: str, phase: int) -> str:
    step = get_current_step({"phase": phase})
    intro = format_message(step["messages"])
    return f"{intro}\n\n{text}"


async def _typing_pause(chat_id: int, bot) -> None:
    await bot.send_chat_action(chat_id, "typing")
    await asyncio.sleep(0.5)


def _next_phase_number(phase: int) -> int:
    return phase + 1


REQUIRED_STATE_KEYS = [
    "pair_task_id",
    "phase",
    "question_index",
    "role",
    "phase_completed",
]


def validate_state(data: dict) -> None:
    for key in REQUIRED_STATE_KEYS:
        if key not in data:
            raise ValueError(f"Missing state key: {key}")


def get_phase_state(phase: int):
    return _generic_phase_state(phase)


def get_questions_for_phase(phase: int, role: str) -> list[str]:
    if phase == 2:
        return get_phase_questions_for_role(phase=phase, role=role)
    return []


def _generic_phase_state(phase: int):
    phase_map = {
        1: PairTest.phase_1,
        2: PairTest.phase_2,
        3: PairTest.phase_3,
        4: PairTest.phase_4,
    }
    return phase_map.get(phase, PairTest.finished)


async def both_users_finished_phase(session, pair_session_id: int, phase: int) -> bool:
    progress = await get_dialogue_progress(session, pair_session_id=pair_session_id)
    phase_key = f"phase{phase}"
    phase_payload = progress.get(phase_key)
    if not isinstance(phase_payload, dict):
        return False
    return bool(phase_payload.get("completed"))


async def mark_phase_completed(state: FSMContext) -> None:
    await state.update_data(
        phase_completed=True,
        waiting_for_other=True,
    )


async def _pair_participants(session, *, pair_session_id: int) -> list[tuple[int, str]]:
    pair_session = await get_pair_session_by_id(session, pair_session_id=pair_session_id)
    if pair_session is None:
        return []

    participants: list[tuple[int, str]] = []
    parent_tg = await _get_telegram_id_by_user_id(pair_session.parent_user_id)
    teen_tg = await _get_telegram_id_by_user_id(pair_session.teen_user_id)

    if parent_tg is not None:
        participants.append((parent_tg, "parent"))
    if teen_tg is not None:
        participants.append((teen_tg, "teen"))

    return participants


async def start_phase3_answering_for_both_users(
    session,
    *,
    pair_session_id: int,
    bot,
    dispatcher: Dispatcher,
) -> None:
    selected = await get_phase3_selected_scenarios(session, pair_session_id=pair_session_id)
    if not selected:
        return

    for telegram_id, role in await _pair_participants(session, pair_session_id=pair_session_id):
        state = dispatcher.fsm.get_context(bot=bot, chat_id=telegram_id, user_id=telegram_id)
        role_answer_map = await get_phase3_answers_for_role(
            session,
            pair_session_id=pair_session_id,
            role=role,
        )
        answered_ids = set(role_answer_map.keys())
        next_scenario_id = next((sid for sid in selected if sid not in answered_ids), None)
        if next_scenario_id is None:
            continue

        scenario = PHASE3_SCENARIOS_BY_ID[next_scenario_id]
        options = scenario["teenager_options" if role == "teen" else "parent_options"]

        await state.set_state(PairTest.phase_3)
        await state.update_data(
            pair_task_id=pair_session_id,
            pair_session_id=pair_session_id,
            phase=3,
            question_index=selected.index(next_scenario_id),
            phase_completed=False,
            waiting_for_other=False,
            role=role,
            mode="pair_test",
            fsm_phase_state=PairTest.phase_3.state,
            phase3_selected=selected,
            phase3_current_scenario_id=next_scenario_id,
            phase_transition_done=False,
            transition_from_phase=None,
        )
        await bot.send_message(
            telegram_id,
            f"<b>Фаза 3. {scenario['title']}</b>\n\n{scenario['situation']}",
            reply_markup=pair_phase3_answer_keyboard(next_scenario_id, options),
        )


async def start_next_phase_for_both_users(
    session,
    *,
    pair_session_id: int,
    current_phase: int,
    bot,
    dispatcher: Dispatcher,
) -> None:
    next_phase = _next_phase_number(current_phase)
    participants = await _pair_participants(session, pair_session_id=pair_session_id)
    if current_phase == 2:
        for telegram_id, _role in participants:
            await bot.send_message(telegram_id, "⏳ Анализируем ответы...")
    phase2_report_text = (
        await build_phase2_comparison_report(session, pair_session_id=pair_session_id)
        if current_phase == 2
        else None
    )
    progress = await get_dialogue_progress(session, pair_session_id=pair_session_id) if next_phase > 4 else None
    report_text = build_dialogue_report(progress) if progress is not None else None

    if next_phase == 2 and hasattr(session, "execute"):
        await reset_phase2_sync_state(session, pair_session_id=pair_session_id)

    for telegram_id, role in participants:
        state = dispatcher.fsm.get_context(bot=bot, chat_id=telegram_id, user_id=telegram_id)
        data = await state.get_data()
        current_user_phase = data.get("phase")

        if isinstance(current_user_phase, int) and current_user_phase > current_phase:
            continue
        if data.get("phase_transition_done") and data.get("transition_from_phase") == current_phase:
            continue

        await state.update_data(phase_transition_done=True, transition_from_phase=current_phase)

        if phase2_report_text is not None:
            await bot.send_chat_action(telegram_id, "typing")
            await asyncio.sleep(0.5)
            await bot.send_message(telegram_id, phase2_report_text)

        if next_phase > 4:
            await state.set_state(PairTest.finished)
            await state.update_data(
                pair_task_id=pair_session_id,
                pair_session_id=pair_session_id,
                phase=4,
                phase_completed=True,
                waiting_for_other=False,
                role=role,
                mode="pair_test",
                fsm_phase_state=PairTest.finished.state,
                phase_transition_done=False,
                transition_from_phase=None,
            )
            await bot.send_message(telegram_id, "Тест завершён. Формируем итог.")
            if report_text is not None:
                await bot.send_message(telegram_id, report_text, reply_markup=pair_result_keyboard())
            continue

        await state.set_state(get_phase_state(next_phase))
        await state.update_data(
            pair_task_id=pair_session_id,
            pair_session_id=pair_session_id,
            phase=next_phase,
            question_index=0,
            phase_completed=False,
            waiting_for_other=False,
            role=role,
            mode="pair_test",
            fsm_phase_state=get_phase_state(next_phase).state,
            phase_transition_done=False,
            transition_from_phase=None,
        )

        if next_phase == 2:
            questions = get_questions_for_phase(next_phase, role)
            await state.update_data(phase2_question_id=1)
            if questions:
                await bot.send_chat_action(telegram_id, "typing")
                await asyncio.sleep(0.5)
                await bot.send_message(
                    telegram_id,
                    format_question(questions[0], phase=2),
                    reply_markup=pair_phase2_answer_keyboard(1),
                )
            continue

        if next_phase == 3:
            selected = await get_phase3_selected_scenarios(session, pair_session_id=pair_session_id)
            await state.update_data(phase3_selected=selected, phase3_current_scenario_id=None)
            await bot.send_chat_action(telegram_id, "typing")
            await asyncio.sleep(0.5)
            await bot.send_message(
                telegram_id,
                f"Сейчас будет интересно 👇\n\nВыберите {PHASE3_MIN_CHOICES}–{PHASE3_MAX_CHOICES} сценариев, которые ближе вашей ситуации.",
                reply_markup=pair_phase3_scenario_select_keyboard(selected),
            )
            continue

        if next_phase == 4:
            selected_values = await get_phase4_values_for_role(session, pair_session_id=pair_session_id, role=role)
            await state.update_data(phase4_selected=selected_values)
            await bot.send_chat_action(telegram_id, "typing")
            await asyncio.sleep(0.5)
            await bot.send_message(
                telegram_id,
                format_question(f"Выберите ровно {PHASE4_REQUIRED_COUNT} ценностей.", phase=4),
                reply_markup=pair_phase4_values_keyboard(selected_values),
            )


async def _set_pair_state(
    state: FSMContext,
    next_state,
    *,
    phase: int,
    **extra_data,
) -> None:
    question_index = extra_data.pop("question_index", None)
    phase_completed = extra_data.pop("phase_completed", False)
    waiting_for_other = extra_data.pop("waiting_for_other", False)
    pair_task_id = extra_data.pop("pair_task_id", extra_data.get("pair_session_id"))
    role = extra_data.pop("role", None)

    await state.update_data(
        pair_task_id=pair_task_id,
        pair_phase=phase,
        phase=phase,
        question_index=question_index,
        phase_completed=phase_completed,
        waiting_for_other=waiting_for_other,
        role=role,
        mode="pair_test",
        fsm_phase_state=getattr(_generic_phase_state(phase), "state", None),
        phase_1_sent=False,
        phase_2_sent=False,
        phase_3_selection_sent=False,
        phase_3_sent=False,
        phase_4_sent=False,
        **extra_data,
    )
    await state.set_state(next_state)


async def _enter_waiting_state(
    state: FSMContext,
    message: Message,
    *,
    next_state,
    phase: int,
    flag_key: str,
    text: str,
    **extra_data,
) -> None:
    current_state = await state.get_state()
    target_state = getattr(next_state, "state", None)

    if current_state != target_state:
        await _set_pair_state(
            state,
            next_state,
            phase=phase,
            **extra_data,
        )
    elif extra_data:
        await state.update_data(**extra_data)

    await _answer_once(
        state,
        message,
        flag_key=flag_key,
        text=text,
    )


async def _send_pair_status_screen(message: Message, *, pair_session) -> None:
    reply_markup = None
    if pair_session.status in _CANCELLABLE_STATUSES:
        reply_markup = pair_session_status_keyboard(session_id=pair_session.id)
    await message.answer(_build_pair_status_text(pair_session), reply_markup=reply_markup)


async def _send_session_not_found(message: Message) -> None:
    await message.answer(
        "⚠️ Сессия не найдена\n\n"
        "Возможно:\n"
        "• тест был завершён\n"
        "• сессия истекла\n\n"
        "Нажмите ниже, чтобы начать заново 👇",
        reply_markup=pair_entry_keyboard(),
    )


async def _get_telegram_id_by_user_id(user_id: int | None) -> int | None:
    if user_id is None:
        return None
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select as sa_select
        from app.db.models import User

        result = await session.execute(sa_select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
    if user is None:
        return None
    return user.telegram_id


async def _notify_other_participant(pair_session, *, role: str, bot, text: str) -> None:
    other_user_id = pair_session.parent_user_id if role == "teen" else pair_session.teen_user_id
    other_telegram_id = await _get_telegram_id_by_user_id(other_user_id)
    if other_telegram_id is None:
        return
    try:
        await bot.send_message(other_telegram_id, text)
    except Exception:
        log.warning("Failed to notify other participant", exc_info=True)


async def show_pair_entry(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.update_data(mode="pair_test")
    await message.answer(
        "<b>Совместный тест «Диалог о выборе»</b>\n\n"
        "4 фазы: эмоциональный фон, индивидуальные вопросы, совместные сценарии и ценностные карточки.\n"
        "Финал покажет, где вы совпадаете и где важно обсудить различия.\n\n"
        + TEXTS["pair_start"],
        reply_markup=pair_entry_keyboard(),
    )


@router.callback_query(F.data == PAIR_MODE_BACK)
async def cb_pair_back(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None:
        return
    await callback.answer()
    await state.clear()
    from app.keyboards.mode import mode_keyboard

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, callback.from_user)

    await state.set_state(RegistrationStates.waiting_for_role)
    await callback.message.edit_text("Выберите режим:", reply_markup=mode_keyboard(role=user.role))


@router.callback_query(F.data == PAIR_MODE_START_TEEN)
async def cb_pair_start_teen(callback: CallbackQuery, state: FSMContext) -> None:
    """Teen initiates a pair session and receives a deep link to share with their parent."""
    if callback.from_user is None or callback.message is None:
        return
    await callback.answer()

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, callback.from_user)
        role = await get_user_role(session, callback.from_user.id)
        if role != "teen":
            await callback.message.answer("Этот блок только для подростка.")
            return

        pair = await _create_pair_invite(session, teen_telegram_id=callback.from_user.id)

    assert callback.bot is not None
    link = await build_invite_link(callback.bot, pair.id)
    await callback.message.answer(
        f"Отправь родителю 👇\n\n{link}",
        disable_web_page_preview=True,
    )
    await callback.message.answer(
        "👉 Родителю нужно просто нажать кнопку\n"
        "«НАЧАТЬ» после перехода\n\n"
        "👇 Инструкция для родителя:\n\n"
        "1. Перейти по ссылке\n"
        "2. Нажать START\n"
        "3. Дождаться запуска теста"
    )
    await callback.message.answer(
        "Я жду подключения родителя 👇\n\n"
        "Как только он зайдёт — сразу начнём"
    )


@router.callback_query(F.data == PAIR_MODE_START_PARENT)
async def cb_pair_start_parent(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None:
        return
    await callback.answer()

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, callback.from_user)
        if user.role != "parent":
            await callback.message.answer(
                "Запустить сессию как родитель может только пользователь с ролью «Родитель»."
            )
            return

        existing = await get_active_pair_session_for_user(session, user_id=user.id, role="parent")
        if existing is not None:
            await _send_pair_status_screen(callback.message, pair_session=existing)
            return

        family_link = await get_family_for_user(session, user_id=user.id)
        family_link_id = family_link.id if family_link is not None else None
        pair_session = await create_pair_session(
            session,
            parent_user_id=user.id,
            family_link_id=family_link_id,
        )

    await state.update_data(
        pair_session_id=pair_session.id,
        pair_task_id=pair_session.id,
        user_id=user.id,
        role="parent",
        phase=1,
        question_index=0,
        phase_completed=False,
        fsm_phase_state=PairTest.phase_1.state,
    )
    await callback.message.edit_text(
        f"Ваш код для подключения подростка: <b>{pair_session.pair_code}</b>\n\n"
        "После подключения вы оба пройдете 4 фазы Диалога о выборе."
    )
    await _send_pair_status_screen(callback.message, pair_session=pair_session)
    await _send_phase1_score_prompt(callback.message)
    await _set_pair_state(
        state,
        PairTestStates.waiting_phase1_score,
        phase=1,
        pair_task_id=pair_session.id,
        pair_session_id=pair_session.id,
        role="parent",
        question_index=0,
        phase_completed=False,
    )


@router.callback_query(F.data == PAIR_MODE_ENTER_CODE)
async def cb_pair_enter_code(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None:
        return
    await callback.answer()

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, callback.from_user)

    if user.role == "parent":
        await callback.message.answer(
            "Эта опция для подростка. Родитель создает сессию через «Начать как родитель»."
        )
        return

    await state.update_data(
        user_id=user.id,
        role="teen",
        phase=1,
        question_index=0,
        phase_completed=False,
        fsm_phase_state=PairTest.phase_1.state,
    )
    await _set_pair_state(
        state,
        PairTestStates.entering_code,
        phase=1,
        role="teen",
        question_index=0,
        phase_completed=False,
    )
    await callback.message.edit_text("Введите код, который вам отправил родитель:")


@router.message(PairTestStates.entering_code)
async def handle_code_input(message: Message, state: FSMContext, dispatcher: Dispatcher) -> None:
    if message.from_user is None:
        return
    code = (message.text or "").strip().upper()
    if not code:
        await message.answer("Пожалуйста, введите код.")
        return

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, message.from_user)
        existing = await get_active_pair_session_for_user(session, user_id=user.id, role="teen")
        if existing is not None and existing.pair_code != code:
            await message.answer(
                "У вас уже есть активная совместная сессия с кодом "
                f"<b>{existing.pair_code}</b>."
            )
            return

        if existing is None:
            try:
                pair_session = await join_pair_session(session, pair_code=code, teen_user_id=user.id)
            except Exception as exc:
                reason = str(exc)
                if "not_found" in reason:
                    await message.answer("Код не найден. Проверьте и попробуйте снова.")
                elif "already_joined" in reason:
                    await message.answer("К сессии уже подключен другой подросток.")
                else:
                    await message.answer("Не удалось подключиться. Попробуйте снова.")
                return
        else:
            pair_session = existing

    await state.update_data(
        pair_session_id=pair_session.id,
        pair_task_id=pair_session.id,
        user_id=user.id,
        role="teen",
        phase=1,
        question_index=0,
        phase_completed=False,
        fsm_phase_state=PairTest.phase_1.state,
    )
    await _set_pair_state(
        state,
        PairTestStates.waiting_phase1_score,
        phase=1,
        pair_task_id=pair_session.id,
        pair_session_id=pair_session.id,
        role="teen",
        question_index=0,
        phase_completed=False,
    )
    await message.answer(
        "Вы подключены к «Диалогу о выборе».\n"
        "Нажмите кнопку ниже, чтобы начать.",
        reply_markup=pair_join_confirm_keyboard(),
    )

    parent_telegram_id = await _get_telegram_id_by_user_id(pair_session.parent_user_id)
    if parent_telegram_id is not None:
        try:
            await message.bot.send_message(
                parent_telegram_id,
                _build_pair_status_text(pair_session),
                reply_markup=pair_session_status_keyboard(session_id=pair_session.id),
            )
        except Exception:
            log.warning("Failed to notify parent about teen join", exc_info=True)

    async with AsyncSessionLocal() as session:
        await try_transition(
            session,
            pair_session_id=pair_session.id,
            phase=1,
            bot=message.bot,
            dispatcher=dispatcher
        )


@router.callback_query(PairTestStates.waiting_phase1_score, F.data == PAIR_START_TEST)
async def cb_start_dialogue(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    await callback.answer()
    await callback.message.edit_text("Начинаем фазу 1.")
    await _send_phase1_score_prompt(callback.message)


async def _send_phase1_score_prompt(message: Message) -> None:
    assert message.bot is not None
    await _typing_pause(message.chat.id, message.bot)
    await message.answer(
        format_question(
            TEXTS["phase_1"]
            + "\n"
            "Когда я думаю о теме выбора профессии и будущего, я чувствую...\n"
            "Выберите оценку от 1 до 10:",
            phase=1,
        ),
        reply_markup=pair_phase1_score_keyboard(),
    )


@router.callback_query(PairTestStates.waiting_phase1_score, F.data.startswith(PAIR_PHASE1_SCORE_PREFIX))
async def cb_phase1_score(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.data is not None
    if callback.message is None:
        return
    await callback.answer()

    try:
        score = int(callback.data[len(PAIR_PHASE1_SCORE_PREFIX):])
    except ValueError:
        await callback.answer("Некорректный формат ответа", show_alert=True)
        return

    data = await state.get_data()
    pair_session_id = data.get("pair_session_id")
    user_id = data.get("user_id")
    role = data.get("role")
    if not isinstance(pair_session_id, int) or not isinstance(user_id, int) or role not in ("teen", "parent"):
        await state.clear()
        await _send_session_not_found(callback.message)
        return

    async with AsyncSessionLocal() as session:
        await save_phase1_score(
            session,
            pair_session_id=pair_session_id,
            user_id=user_id,
            role=role,
            score=score,
        )

    await callback.message.edit_reply_markup(reply_markup=None)
    await state.update_data(current_user_answered_phase1_score=True, question_index=0, phase=1, phase_completed=False)
    await state.set_state(PairTestStates.waiting_phase1_word)
    await callback.message.answer("Понял тебя.")
    await callback.message.answer("Напишите одним словом, что вы чувствуете:")


@router.message(PairTestStates.waiting_phase1_word)
async def msg_phase1_word(message: Message, state: FSMContext, dispatcher: Dispatcher) -> None:
    if message.from_user is None:
        return
    word = (message.text or "").strip()
    if not word:
        await message.answer("Нужно одно слово. Попробуйте еще раз.")
        return

    data = await state.get_data()
    pair_session_id = data.get("pair_session_id")
    user_id = data.get("user_id")
    role = data.get("role")
    if not isinstance(pair_session_id, int) or not isinstance(user_id, int) or role not in ("teen", "parent"):
        await state.clear()
        await _send_session_not_found(message)
        return

    if data.get("phase_completed") and data.get("phase") == 1:
        return

    async with AsyncSessionLocal() as session:
        await save_phase1_word(
            session,
            pair_session_id=pair_session_id,
            user_id=user_id,
            role=role,
            word=word,
        )

    await state.update_data(phase=1, question_index=1, phase_completed=True)
    async with AsyncSessionLocal() as session:
        transitioned = await try_transition(
            session, pair_session_id=pair_session_id, phase=1, bot=message.bot, dispatcher=dispatcher
        )
    if not transitioned:
        await mark_phase_completed(state)
        await _enter_waiting_state(
            state,
            message,
            next_state=PairTestStates.phase1_waiting_other,
            phase=1,
            flag_key="phase_1_sent",
            text=PAIR_TEXTS["phase_1_wait"],
            pair_task_id=pair_session_id,
            pair_session_id=pair_session_id,
            role=role,
            question_index=1,
            phase_completed=True,
            waiting_for_other=True,
            current_user_answered=True,
            both_users_answered=False,
        )


async def _start_phase2(message: Message, state: FSMContext, *, pair_session_id: int, role: str) -> None:
    async with AsyncSessionLocal() as session:
        role_answers = await get_phase2_answers_for_role(session, pair_session_id=pair_session_id, role=role)
    next_qid = len(role_answers) + 1
    if next_qid > PHASE2_TOTAL_QUESTIONS:
        await _complete_phase2_side(message, state, pair_session_id=pair_session_id, role=role)
        return

    await _set_pair_state(
        state,
        PairTest.phase_2,
        phase=2,
        pair_task_id=pair_session_id,
        pair_session_id=pair_session_id,
        role=role,
        phase2_question_id=next_qid,
        question_index=next_qid - 1,
        current_user_answered=False,
    )
    await _send_phase2_question(message, role=role, question_id=next_qid)


async def _send_phase2_question(message: Message, *, role: str, question_id: int) -> None:
    assert message.bot is not None
    if role not in ["teen", "parent"]:
        raise ValueError("Invalid role")
    question = get_phase_question(phase=2, role=role, index=question_id - 1)
    phase = 2
    index = question_id - 1
    print(
        "\n"
        f"ROLE={role}\n"
        f"PHASE={phase}\n"
        f"INDEX={index}\n"
        f"QUESTION={question}\n"
    )
    await _typing_pause(message.chat.id, message.bot)
    await message.answer(
        format_question(question, phase=2),
        reply_markup=pair_phase2_answer_keyboard(question_id),
    )


async def _send_phase2_next_for_both(
    *,
    pair_session_id: int,
    question_id: int,
    bot,
    dispatcher: Dispatcher,
) -> None:
    async with AsyncSessionLocal() as session:
        pair_session = await get_pair_session_by_id(session, pair_session_id=pair_session_id)
        if pair_session is None:
            return

        # Hard anti-desync gate: next question only when both indices are aligned.
        if pair_session.teen_index != pair_session.parent_index:
            return

        participants = await _pair_participants(session, pair_session_id=pair_session_id)

    for telegram_id, role in participants:
        peer_state = dispatcher.fsm.get_context(bot=bot, chat_id=telegram_id, user_id=telegram_id)
        data = await peer_state.get_data()
        await peer_state.set_state(PairTest.phase_2)
        await peer_state.update_data(
            pair_task_id=pair_session_id,
            pair_session_id=pair_session_id,
            phase=2,
            role=role,
            mode="pair_test",
            fsm_phase_state=PairTest.phase_2.state,
            phase2_question_id=question_id,
            question_index=question_id - 1,
            waiting_for_other=False,
            current_user_answered=False,
            both_users_answered=False,
            phase_completed=False,
            phase_transition_done=False,
            transition_from_phase=None,
            user_id=data.get("user_id", telegram_id),
        )
        await bot.send_message(telegram_id, "Понял тебя.")
        question_text = get_phase_question(phase=2, role=role, index=question_id - 1)
        await bot.send_message(
            telegram_id,
            format_question(question_text, phase=2),
            reply_markup=pair_phase2_answer_keyboard(question_id),
        )


@router.callback_query(PairTestStates.phase2_answering, F.data.startswith(PAIR_PHASE2_ANSWER_PREFIX))
@router.callback_query(PairTest.phase_2, F.data.startswith(PAIR_PHASE2_ANSWER_PREFIX))
async def cb_phase2_answer(callback: CallbackQuery, state: FSMContext, dispatcher: Dispatcher) -> None:
    assert callback.data is not None
    if callback.message is None:
        return
    await callback.answer()
    try:
        raw = callback.data[len(PAIR_PHASE2_ANSWER_PREFIX):]
        try:
            qid_str, value_str = raw.split(":")
            question_id = int(qid_str)
            value = int(value_str)
        except Exception:
            await callback.answer("Некорректный формат ответа", show_alert=True)
            return

        if value not in [1, 2, 3, 4]:
            await callback.answer("Выбери вариант от 1 до 4", show_alert=True)
            return

        data = await state.get_data()
        now = time.time()

        last_click_ts_raw = data.get("phase2_last_click_ts", 0)
        last_click_qid = data.get("phase2_last_click_qid")
        last_click_ts = float(last_click_ts_raw) if isinstance(last_click_ts_raw, (int, float)) else 0.0

        # Debounce by question id: ignore ultra-fast repeated clicks for the same question.
        if last_click_qid == question_id and (now - last_click_ts) < DEBOUNCE_SECONDS:
            log.info("[PAIR_P2] debounce ignored: qid=%s delta=%.3f", question_id, now - last_click_ts)
            return

        expected_qid_raw = data.get("phase2_question_id")
        expected_qid: int | None = None
        if isinstance(expected_qid_raw, int):
            expected_qid = expected_qid_raw
        elif isinstance(expected_qid_raw, str) and expected_qid_raw.isdigit():
            expected_qid = int(expected_qid_raw)

        pair_session_id = data.get("pair_session_id")
        user_id = data.get("user_id")
        role = data.get("role")

        log.info(
            "[PAIR_P2] callback=%s parsed_qid=%s expected_qid=%s pair_session_id=%s user_id=%s role=%s",
            callback.data,
            question_id,
            expected_qid,
            pair_session_id,
            user_id,
            role,
        )

        # Self-heal state drift after resume/restart if phase2_question_id is absent.
        if expected_qid is None:
            expected_qid = question_id
            await state.update_data(phase2_question_id=question_id, question_index=question_id - 1)

        if question_id != expected_qid:
            log.warning(
                "[PAIR_P2] stale callback: got_qid=%s expected_qid=%s pair_session_id=%s user_id=%s",
                question_id,
                expected_qid,
                pair_session_id,
                user_id,
            )
            await callback.answer("Эта кнопка уже неактуальна", show_alert=True)
            return
        if not isinstance(pair_session_id, int) or not isinstance(user_id, int) or role not in ("teen", "parent"):
            await state.clear()
            await _send_session_not_found(callback.message)
            return

        if isinstance(expected_qid, int) and question_id != expected_qid:
            await callback.answer("Эта кнопка уже неактуальна", show_alert=True)
            return

        answered_key = f"phase2_answered_{question_id}"
        lock_key = f"phase2_lock_{question_id}"
        if data.get(answered_key) or data.get(lock_key):
            log.info("[PAIR_P2] duplicate ignored: qid=%s answered=%s lock=%s", question_id, data.get(answered_key), data.get(lock_key))
            return

        # Atomic gate: block parallel double-click processing for this question.
        await state.update_data(
            phase2_last_click_ts=now,
            phase2_last_click_qid=question_id,
            **{lock_key: True},
        )

        sync_result: dict
        async with AsyncSessionLocal() as session:
            try:
                async with session.begin():
                    sync_result = await process_phase2_answer_sync(
                        session,
                        pair_session_id=pair_session_id,
                        user_id=user_id,
                        role=role,
                        question_id=question_id,
                        answer_value=value,
                    )
            except Exception:
                await state.update_data(**{lock_key: False})
                log.exception(
                    "[PAIR_P2] tx failed: pair_session_id=%s user_id=%s role=%s qid=%s",
                    pair_session_id,
                    user_id,
                    role,
                    question_id,
                )
                await callback.message.answer("Не удалось сохранить ответ. Нажмите кнопку ещё раз.")
                return

        status = sync_result.get("status")
        if status in ("already_answered", "stale"):
            await state.update_data(**{lock_key: False})
            await callback.answer("Эта кнопка уже неактуальна", show_alert=True)
            return
        if status != "ok":
            await state.update_data(**{lock_key: False})
            if status in ("session_not_found", "session_closed", "forbidden"):
                await state.clear()
                await _send_session_not_found(callback.message)
                return
            await callback.answer("Не удалось обработать ответ", show_alert=True)
            return

        both_answered = bool(sync_result.get("both_answered"))
        phase_completed = bool(sync_result.get("phase_completed"))
        next_qid_raw = sync_result.get("next_qid")
        next_qid = int(next_qid_raw) if isinstance(next_qid_raw, int) else question_id + 1
        wait_for_role = sync_result.get("wait_for_role")

        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            log.exception("[PAIR_P2] failed to clear reply markup for qid=%s", question_id)

        if not both_answered:
            partner_label = "родителя" if wait_for_role == "parent" else "подростка"
            await state.update_data(
                waiting_for_other=True,
                current_user_answered=True,
                both_users_answered=False,
                phase_completed=False,
                **{answered_key: True, lock_key: False},
            )
            await state.set_state(PairTest.phase_2)
            await callback.message.answer(f"⏳ Ждём {partner_label}...")
            return

        await state.update_data(
            phase2_question_id=next_qid,
            question_index=max(0, next_qid - 1),
            waiting_for_other=False,
            current_user_answered=False,
            both_users_answered=True,
            phase_completed=phase_completed,
            **{answered_key: True, lock_key: False},
        )
        await state.set_state(PairTest.phase_2)

        if phase_completed or next_qid > PHASE2_TOTAL_QUESTIONS:
            await _complete_phase2_side(
                callback.message,
                state,
                pair_session_id=pair_session_id,
                role=role,
                bot=callback.bot,
                dispatcher=dispatcher,
            )
            return

        await _send_phase2_next_for_both(
            pair_session_id=pair_session_id,
            question_id=next_qid,
            bot=callback.bot,
            dispatcher=dispatcher,
        )
    except Exception:
        log.exception("[PAIR_P2] handler error for callback=%s", callback.data)


async def _complete_phase2_side(
    message: Message,
    state: FSMContext,
    *,
    pair_session_id: int,
    role: str,
    bot,
    dispatcher: Dispatcher,
) -> None:
    data = await state.get_data()
    if data.get("phase_completed") and data.get("phase") == 2:
        return
    await state.update_data(phase=2, question_index=PHASE2_TOTAL_QUESTIONS - 1, phase_completed=True)
    async with AsyncSessionLocal() as session:
        transitioned = await try_transition(
            session, pair_session_id=pair_session_id, phase=2, bot=bot, dispatcher=dispatcher
        )
    if not transitioned:
        await mark_phase_completed(state)
        await _enter_waiting_state(
            state,
            message,
            next_state=PairTestStates.phase2_waiting_other,
            phase=2,
            flag_key="phase_2_sent",
            text=f"Вы завершили фазу 2. {PAIR_TEXTS['phase_2_wait'].replace('Фаза 2. ', '')}",
            pair_task_id=pair_session_id,
            pair_session_id=pair_session_id,
            role=role,
            question_index=PHASE2_TOTAL_QUESTIONS - 1,
            phase_completed=True,
            waiting_for_other=True,
            current_user_answered=True,
            both_users_answered=False,
        )


async def _start_phase3_selection(message: Message, state: FSMContext, *, pair_session_id: int, role: str) -> None:
    async with AsyncSessionLocal() as session:
        selected = await get_phase3_selected_scenarios(session, pair_session_id=pair_session_id)
    await _set_pair_state(
        state,
        PairTest.phase_3,
        phase=3,
        pair_task_id=pair_session_id,
        pair_session_id=pair_session_id,
        role=role,
        question_index=0,
        phase_completed=False,
        phase3_selected=selected,
        current_user_answered=False,
    )
    if message.bot is None:
        return
    await _typing_pause(message.chat.id, message.bot)
    await message.answer(
        f"Сейчас будет интересно 👇\n\nВыберите {PHASE3_MIN_CHOICES}–{PHASE3_MAX_CHOICES} сценариев, которые ближе вашей ситуации.",
        reply_markup=pair_phase3_scenario_select_keyboard(selected),
    )


@router.callback_query(PairTestStates.phase3_selecting_scenarios, F.data.startswith(PAIR_PHASE3_SCENARIO_TOGGLE_PREFIX))
@router.callback_query(PairTest.phase_3, F.data.startswith(PAIR_PHASE3_SCENARIO_TOGGLE_PREFIX))
async def cb_phase3_toggle_scenario(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.data is not None
    if callback.message is None:
        return
    await callback.answer()

    try:
        scenario_id = int(callback.data[len(PAIR_PHASE3_SCENARIO_TOGGLE_PREFIX):])
    except ValueError:
        return
    if scenario_id not in PHASE3_SCENARIOS_BY_ID:
        return

    data = await state.get_data()
    selected: list[int] = list(data.get("phase3_selected", []))
    if scenario_id in selected:
        selected = [x for x in selected if x != scenario_id]
    else:
        if len(selected) >= PHASE3_MAX_CHOICES:
            await callback.answer(f"Можно выбрать максимум {PHASE3_MAX_CHOICES} сценариев", show_alert=True)
            return
        selected.append(scenario_id)

    await state.update_data(phase3_selected=selected)
    await callback.message.edit_reply_markup(reply_markup=pair_phase3_scenario_select_keyboard(selected))


@router.callback_query(PairTestStates.phase3_selecting_scenarios, F.data == PAIR_PHASE3_SCENARIO_DONE)
@router.callback_query(PairTest.phase_3, F.data == PAIR_PHASE3_SCENARIO_DONE)
async def cb_phase3_done_selection(callback: CallbackQuery, state: FSMContext, dispatcher: Dispatcher) -> None:
    if callback.message is None:
        return
    await callback.answer()

    data = await state.get_data()
    selected: list[int] = list(data.get("phase3_selected", []))
    pair_session_id = data.get("pair_session_id")
    user_id = data.get("user_id")
    role = data.get("role")

    if len(selected) < PHASE3_MIN_CHOICES or len(selected) > PHASE3_MAX_CHOICES:
        await callback.answer(f"Нужно выбрать {PHASE3_MIN_CHOICES}-{PHASE3_MAX_CHOICES} сценариев", show_alert=True)
        return
    if not isinstance(pair_session_id, int) or not isinstance(user_id, int) or role not in ("teen", "parent"):
        await state.clear()
        await _send_session_not_found(callback.message)
        return

    async with AsyncSessionLocal() as session:
        await save_phase3_selected_scenarios(
            session,
            pair_session_id=pair_session_id,
            actor_user_id=user_id,
            scenario_ids=selected,
        )
        await set_phase3_selection_ready(
            session,
            pair_session_id=pair_session_id,
            user_id=user_id,
            role=role,
            ready=True,
        )
        teen_ready = await is_phase3_selection_ready(session, pair_session_id=pair_session_id, role="teen")
        parent_ready = await is_phase3_selection_ready(session, pair_session_id=pair_session_id, role="parent")

    if teen_ready and parent_ready:
        await callback.message.edit_reply_markup(reply_markup=None)
        async with AsyncSessionLocal() as session:
            await start_phase3_answering_for_both_users(
                session,
                pair_session_id=pair_session_id,
                bot=callback.bot,
                dispatcher=dispatcher,
            )
    else:
        await mark_phase_completed(state)
        await _enter_waiting_state(
            state,
            callback.message,
            next_state=PairTest.phase_3,
            phase=3,
            flag_key="phase_3_selection_sent",
            text=f"{PAIR_TEXTS['phase_3_selection_saved']} {PAIR_TEXTS['phase_3_selection_sync']}",
            pair_task_id=pair_session_id,
            pair_session_id=pair_session_id,
            role=role,
            waiting_for_other=True,
            current_user_answered=True,
            both_users_answered=False,
        )


async def _start_phase3_answering(
    message: Message,
    state: FSMContext,
    *,
    pair_session_id: int,
    role: str,
    dispatcher: Dispatcher | None = None,
    bot=None,
) -> None:
    async with AsyncSessionLocal() as session:
        selected = await get_phase3_selected_scenarios(session, pair_session_id=pair_session_id)
        role_answer_map = await get_phase3_answers_for_role(
            session,
            pair_session_id=pair_session_id,
            role=role,
        )
        answered_ids = set(role_answer_map.keys())

    next_scenario_id = next((sid for sid in selected if sid not in answered_ids), None)
    if next_scenario_id is None:
        if dispatcher is None or bot is None:
            raise ValueError("dispatcher_and_bot_required")
        await _complete_phase3_side(
            message,
            state,
            pair_session_id=pair_session_id,
            role=role,
            bot=bot,
            dispatcher=dispatcher,
        )
        return

    await _set_pair_state(
        state,
        PairTest.phase_3,
        phase=3,
        pair_task_id=pair_session_id,
        pair_session_id=pair_session_id,
        role=role,
        question_index=selected.index(next_scenario_id),
        phase3_selected=selected,
        phase3_current_scenario_id=next_scenario_id,
        current_user_answered=False,
    )
    await _send_phase3_question(message, role=role, scenario_id=next_scenario_id)


async def _send_phase3_question(message: Message, *, role: str, scenario_id: int) -> None:
    if message.bot is None:
        return
    scenario = PHASE3_SCENARIOS_BY_ID[scenario_id]
    options = scenario["teenager_options" if role == "teen" else "parent_options"]
    await _typing_pause(message.chat.id, message.bot)
    await message.answer(
        format_question(f"<b>{scenario['title']}</b>\n\n{scenario['situation']}", phase=3),
        reply_markup=pair_phase3_answer_keyboard(scenario_id, options),
    )


@router.callback_query(PairTestStates.phase3_answering, F.data.startswith(PAIR_PHASE3_ANSWER_PREFIX))
@router.callback_query(PairTest.phase_3, F.data.startswith(PAIR_PHASE3_ANSWER_PREFIX))
async def cb_phase3_answer(callback: CallbackQuery, state: FSMContext, dispatcher: Dispatcher) -> None:
    assert callback.data is not None
    if callback.message is None:
        return
    await callback.answer()

    raw = callback.data[len(PAIR_PHASE3_ANSWER_PREFIX):]
    try:
        sid_str, opt_str = raw.split(":")
        scenario_id = int(sid_str)
        option_index = int(opt_str)
    except Exception:
        await callback.answer("Некорректный формат ответа", show_alert=True)
        return

    data = await state.get_data()
    current_sid = data.get("phase3_current_scenario_id")
    pair_session_id = data.get("pair_session_id")
    user_id = data.get("user_id")
    role = data.get("role")

    if scenario_id != current_sid:
        await callback.answer("Эта кнопка уже неактуальна", show_alert=True)
        return
    if not isinstance(pair_session_id, int) or not isinstance(user_id, int) or role not in ("teen", "parent"):
        await state.clear()
        await _send_session_not_found(callback.message)
        return

    async with AsyncSessionLocal() as session:
        await save_phase3_answer(
            session,
            pair_session_id=pair_session_id,
            user_id=user_id,
            role=role,
            scenario_id=scenario_id,
            option_index=option_index,
        )
        result = await get_phase3_scenario_result(session, pair_session_id=pair_session_id, scenario_id=scenario_id)
        pair_session = await get_pair_session_by_id(session, pair_session_id=pair_session_id)

    await callback.message.edit_reply_markup(reply_markup=None)

    if result.get("ready"):
        if result["matched"]:
            text = f"Сценарий «{result['title']}»: совпало ✅"
        else:
            text = (
                f"Сценарий «{result['title']}»: не совпало ❌\n"
                f"Вопрос для обсуждения: {result['discussion_question']}"
            )
        await callback.message.answer(text)
        if pair_session is not None:
            await _notify_other_participant(pair_session, role=role, bot=callback.bot, text=text)

    await _start_phase3_answering(
        callback.message,
        state,
        pair_session_id=pair_session_id,
        role=role,
        dispatcher=dispatcher,
        bot=callback.bot,
    )


async def _complete_phase3_side(
    message: Message,
    state: FSMContext,
    *,
    pair_session_id: int,
    role: str,
    bot,
    dispatcher: Dispatcher,
) -> None:
    data = await state.get_data()
    if data.get("phase_completed") and data.get("phase") == 3:
        return
    await state.update_data(phase=3, phase_completed=True)
    async with AsyncSessionLocal() as session:
        transitioned = await try_transition(
            session, pair_session_id=pair_session_id, phase=3, bot=bot, dispatcher=dispatcher
        )
    if not transitioned:
        await mark_phase_completed(state)
        await _enter_waiting_state(
            state,
            message,
            next_state=PairTest.phase_3,
            phase=3,
            flag_key="phase_3_sent",
            text=f"Вы завершили свои сценарии. {PAIR_TEXTS['phase_3_wait'].replace('Фаза 3. ', '')}",
            pair_task_id=pair_session_id,
            pair_session_id=pair_session_id,
            role=role,
            phase_completed=True,
            waiting_for_other=True,
            current_user_answered=True,
            both_users_answered=False,
        )


async def _start_phase4_selecting(message: Message, state: FSMContext, *, pair_session_id: int, role: str) -> None:
    async with AsyncSessionLocal() as session:
        selected_values = await get_phase4_values_for_role(session, pair_session_id=pair_session_id, role=role)

    await _set_pair_state(
        state,
        PairTest.phase_4,
        phase=4,
        pair_task_id=pair_session_id,
        pair_session_id=pair_session_id,
        role=role,
        question_index=0,
        phase_completed=False,
        phase4_selected=selected_values,
        current_user_answered=False,
    )
    if message.bot is None:
        return
    await _typing_pause(message.chat.id, message.bot)
    await message.answer(
        format_question(f"Выберите ровно {PHASE4_REQUIRED_COUNT} ценностей.", phase=4),
        reply_markup=pair_phase4_values_keyboard(selected_values),
    )


@router.callback_query(PairTestStates.phase4_selecting_values, F.data.startswith(PAIR_PHASE4_VALUE_TOGGLE_PREFIX))
@router.callback_query(PairTest.phase_4, F.data.startswith(PAIR_PHASE4_VALUE_TOGGLE_PREFIX))
async def cb_phase4_toggle_value(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.data is not None
    if callback.message is None:
        return
    await callback.answer()

    try:
        value_id = int(callback.data[len(PAIR_PHASE4_VALUE_TOGGLE_PREFIX):])
    except ValueError:
        return

    data = await state.get_data()
    selected: list[int] = list(data.get("phase4_selected", []))
    if value_id in selected:
        selected = [x for x in selected if x != value_id]
    else:
        if len(selected) >= PHASE4_REQUIRED_COUNT:
            await callback.answer(f"Можно выбрать только {PHASE4_REQUIRED_COUNT}", show_alert=True)
            return
        selected.append(value_id)

    await state.update_data(phase4_selected=selected)
    await callback.message.edit_reply_markup(reply_markup=pair_phase4_values_keyboard(selected))


@router.callback_query(PairTestStates.phase4_selecting_values, F.data == PAIR_PHASE4_DONE)
@router.callback_query(PairTest.phase_4, F.data == PAIR_PHASE4_DONE)
async def cb_phase4_done(callback: CallbackQuery, state: FSMContext, dispatcher: Dispatcher) -> None:
    if callback.message is None:
        return
    await callback.answer()

    data = await state.get_data()
    pair_session_id = data.get("pair_session_id")
    user_id = data.get("user_id")
    role = data.get("role")
    selected: list[int] = list(data.get("phase4_selected", []))

    if len(selected) != PHASE4_REQUIRED_COUNT:
        await callback.answer(f"Нужно выбрать ровно {PHASE4_REQUIRED_COUNT} ценностей", show_alert=True)
        return
    if not isinstance(pair_session_id, int) or not isinstance(user_id, int) or role not in ("teen", "parent"):
        await state.clear()
        await _send_session_not_found(callback.message)
        return

    async with AsyncSessionLocal() as session:
        await save_phase4_values(
            session,
            pair_session_id=pair_session_id,
            user_id=user_id,
            role=role,
            value_ids=selected,
        )
        phase4 = await get_phase4_summary(session, pair_session_id=pair_session_id)
        updated_session = await mark_role_done(session, pair_session_id=pair_session_id, role=role)

    await callback.message.edit_reply_markup(reply_markup=None)

    if phase4["completed"]:
        await state.update_data(
            pair_task_id=pair_session_id,
            phase=4,
            question_index=PHASE4_REQUIRED_COUNT - 1,
            phase_completed=True,
            waiting_for_other=False,
            fsm_phase_state=PairTest.finished.state,
        )
        async with AsyncSessionLocal() as session:
            await try_transition(
                session, pair_session_id=pair_session_id, phase=4, bot=callback.bot, dispatcher=dispatcher
            )
        return

    await mark_phase_completed(state)
    await _enter_waiting_state(
        state,
        callback.message,
        next_state=PairTestStates.phase4_waiting_other,
        phase=4,
        flag_key="phase_4_sent",
        text=f"Ваши ценности сохранены. {PAIR_TEXTS['phase_4_wait'].replace('Фаза 4. ', '')}",
        pair_task_id=pair_session_id,
        pair_session_id=pair_session_id,
        role=role,
        question_index=PHASE4_REQUIRED_COUNT - 1,
        phase_completed=True,
        waiting_for_other=True,
        current_user_answered=True,
        both_users_answered=False,
    )


async def _send_final_report(message: Message, *, pair_session_id: int) -> None:
    async with AsyncSessionLocal() as session:
        progress = await get_dialogue_progress(session, pair_session_id=pair_session_id)
    blocks = list(progress.get("phase2", {}).get("blocks", []))
    strongest_diff = None
    strongest_match = None
    if blocks:
        strongest_diff = max(blocks, key=lambda item: int(item.get("pair_diff", 0)))
        strongest_match = min(blocks, key=lambda item: int(item.get("pair_diff", 0)))

    if strongest_diff is not None and strongest_match is not None:
        await message.answer(
            "📊 Ваш результат готов\n\n"
            "👇 Главное:\n"
            f"❗ Самое сильное расхождение: {strongest_diff.get('block_name', '—')}\n"
            f"✅ Самое сильное совпадение: {strongest_match.get('block_name', '—')}\n\n"
            "👇 Что дальше:",
            reply_markup=pair_result_keyboard(),
        )

    report_text = build_dialogue_report(progress)
    await message.answer(report_text, reply_markup=pair_result_keyboard())


@router.callback_query(F.data.startswith(PAIR_CANCEL_REQUEST_PREFIX))
async def cb_pair_cancel_request(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    await callback.answer()

    session_id = _parse_session_id_from_callback(callback.data, PAIR_CANCEL_REQUEST_PREFIX)
    if session_id is None:
        await callback.message.answer("Некорректная команда отмены.")
        return

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, callback.from_user)
        pair_session = await get_pair_session_by_id(session, pair_session_id=session_id)

    if user.role != "parent" or pair_session is None or pair_session.parent_user_id != user.id:
        await callback.message.answer("Эта команда доступна только родителю своей сессии.")
        return
    if pair_session.status not in _CANCELLABLE_STATUSES:
        await callback.message.answer("Эту сессию уже нельзя отменить.")
        return

    await callback.message.edit_text(
        "Вы уверены, что хотите отменить текущую совместную сессию?",
        reply_markup=pair_cancel_confirm_keyboard(session_id=pair_session.id),
    )


@router.callback_query(F.data.startswith(PAIR_CANCEL_NO_PREFIX))
async def cb_pair_cancel_keep(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    await callback.answer()

    session_id = _parse_session_id_from_callback(callback.data, PAIR_CANCEL_NO_PREFIX)
    if session_id is None:
        await callback.message.answer("Отмена не выполнена.")
        return

    async with AsyncSessionLocal() as session:
        pair_session = await get_pair_session_by_id(session, pair_session_id=session_id)

    if pair_session is None:
        await callback.message.answer("Сессия недоступна.")
        return
    await callback.message.edit_text(
        _build_pair_status_text(pair_session),
        reply_markup=pair_session_status_keyboard(session_id=pair_session.id),
    )


@router.callback_query(F.data.startswith(PAIR_CANCEL_YES_PREFIX))
async def cb_pair_cancel_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None:
        return
    await callback.answer()

    session_id = _parse_session_id_from_callback(callback.data, PAIR_CANCEL_YES_PREFIX)
    if session_id is None:
        await callback.message.answer("Некорректная команда отмены.")
        return

    teen_telegram_id: int | None = None
    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, callback.from_user)
        if user.role != "parent":
            await callback.message.answer("Эта команда доступна только родителю.")
            return

        cancelled = await cancel_pair_session(
            session,
            pair_session_id=session_id,
            parent_user_id=user.id,
        )
        teen_telegram_id = await _get_telegram_id_by_user_id(cancelled.teen_user_id)

    await state.clear()
    await callback.message.edit_text(_build_pair_status_text(cancelled), reply_markup=None)
    await callback.message.answer("Совместная сессия отменена.")

    if teen_telegram_id is not None:
        try:
            await callback.bot.send_message(teen_telegram_id, "Совместный тест был завершен родителем.")
        except Exception:
            log.warning("Failed to notify teen about cancellation", exc_info=True)


@router.callback_query(F.data == PAIR_RESULT_DISCUSS)
async def cb_pair_result_discuss(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    await callback.answer()
    text = "Три вопроса для разговора:\n\n" + "\n".join(
        f"{idx}. {q}" for idx, q in enumerate(DISCUSSION_QUESTIONS, start=1)
    )
    await callback.message.answer(text)


@router.callback_query(F.data == PAIR_RESULT_NEXT)
async def cb_pair_result_next(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    await callback.answer()
    await callback.message.answer(NEXT_STEPS_TEXT)


@router.callback_query(F.data == PAIR_RESULT_MY)
async def cb_pair_result_my(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    await callback.answer()

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, callback.from_user)
        cached = await get_last_result(session, user.telegram_id)

    if cached is None:
        await callback.message.answer("Пока нет сохранённого результата. Пройдите тест до конца.")
        return
    await callback.message.answer(build_result_text(cached))


@router.callback_query(F.data == PAIR_RESULT_RESTART)
async def cb_pair_result_restart(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message is None:
        return
    await callback.answer()
    await state.clear()
    await show_pair_entry(callback.message, state)


@router.callback_query(F.data == PAIR_CHECK_STATUS)
async def cb_pair_check_status(callback: CallbackQuery, state: FSMContext, dispatcher: Dispatcher) -> None:
    if callback.from_user is None or callback.message is None:
        return

    data = await state.get_data()
    pair_session_id = data.get("pair_session_id")
    phase = data.get("phase")
    role = data.get("role")
    user_id = data.get("user_id")

    if not isinstance(pair_session_id, int) or not isinstance(phase, int) or role not in ("teen", "parent"):
        await callback.answer("Сессия не найдена", show_alert=True)
        await _send_session_not_found(callback.message)
        return

    async with AsyncSessionLocal() as session:
        progress = await get_dialogue_progress(session, pair_session_id=pair_session_id)
        phase_key = f"phase{phase}"
        phase_payload = progress.get(phase_key, {})

        completed = bool(phase_payload.get("completed")) if isinstance(phase_payload, dict) else False
        if completed:
            await callback.answer("✅ Оба ответили, продолжаем")
            await try_transition(
                session,
                pair_session_id=pair_session_id,
                phase=phase,
                bot=callback.bot,
                dispatcher=dispatcher,
            )
            return

        if isinstance(phase_payload, dict):
            my_done = bool(phase_payload.get(role, {}).get("done", phase_payload.get(f"{role}_done", False)))
            if my_done:
                await callback.answer("⏳ Второй участник ещё не ответил", show_alert=True)
                return

    await callback.answer("Ответьте на текущий шаг, чтобы продолжить", show_alert=True)


@router.callback_query(F.data == PAIR_PING_PARTNER)
async def cb_ping_partner(callback: CallbackQuery) -> None:
    if callback.from_user is None:
        return

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, callback.from_user)
        role = user.role
        if role not in ("teen", "parent"):
            await callback.answer("Сначала выберите роль", show_alert=True)
            return

        active = await get_active_pair_session_for_user(session, user_id=user.id, role=role)
        if active is None:
            await callback.answer("Нет активной сессии", show_alert=True)
            return

        ok = await ping_partner(callback.bot, session, pair_id=active.id, from_user_id=user.id)

    if ok:
        await callback.answer("📩 Напоминание отправлено")
    else:
        await callback.answer("Не удалось отправить напоминание", show_alert=True)


async def _resume_pair_for_actor(
    *,
    actor_tg_id: int,
    message: Message,
    state: FSMContext,
    dispatcher: Dispatcher,
) -> None:
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select as sa_select
        from app.db.models import User

        user_row = await session.execute(sa_select(User).where(User.telegram_id == actor_tg_id))
        user = user_row.scalar_one_or_none()
        if user is None:
            await message.answer("Сначала выберите роль через /start.")
            return

        role = user.role
        if role not in ("teen", "parent"):
            await message.answer("Сначала выберите роль через /start.")
            return

        pair_session = await get_active_pair_session_for_user(session, user_id=user.id, role=role)
        if pair_session is None:
            await message.answer("Нет активной сессии.")
            return

        await track_user_event(session, user_id=user.id, event="return")
        await session.commit()

        progress = await get_dialogue_progress(session, pair_session_id=pair_session.id)

    await state.clear()

    if not progress["phase1"]["completed"]:
        role_done = bool(progress["phase1"][role].get("done"))
        if role_done:
            await _set_pair_state(
                state,
                PairTestStates.phase1_waiting_other,
                phase=1,
                pair_task_id=pair_session.id,
                pair_session_id=pair_session.id,
                user_id=user.id,
                role=role,
                question_index=1,
                phase_completed=True,
                waiting_for_other=True,
            )
            await message.answer("⏳ Пока ждём второго участника")
            return

        await _set_pair_state(
            state,
            PairTestStates.waiting_phase1_score,
            phase=1,
            pair_task_id=pair_session.id,
            pair_session_id=pair_session.id,
            user_id=user.id,
            role=role,
            question_index=0,
            phase_completed=False,
            waiting_for_other=False,
        )
        await _send_phase1_score_prompt(message)
        return

    if not progress["phase2"]["completed"]:
        role_done = bool(progress["phase2"][role].get("done"))
        if role_done:
            await _set_pair_state(
                state,
                PairTestStates.phase2_waiting_other,
                phase=2,
                pair_task_id=pair_session.id,
                pair_session_id=pair_session.id,
                user_id=user.id,
                role=role,
                question_index=PHASE2_TOTAL_QUESTIONS - 1,
                phase_completed=True,
                waiting_for_other=True,
            )
            await message.answer("⏳ Пока ждём второго участника")
            return

        await _start_phase2(message, state, pair_session_id=pair_session.id, role=role)
        return

    if not progress["phase3"]["completed"]:
        role_done = bool(progress["phase3"][f"{role}_done"])
        if role_done:
            await _set_pair_state(
                state,
                PairTestStates.phase3_waiting_other,
                phase=3,
                pair_task_id=pair_session.id,
                pair_session_id=pair_session.id,
                user_id=user.id,
                role=role,
                question_index=0,
                phase_completed=True,
                waiting_for_other=True,
            )
            await message.answer("⏳ Пока ждём второго участника")
            return

        selected = list(progress["phase3"].get("selected_scenarios", []))
        if not selected:
            await _start_phase3_selection(message, state, pair_session_id=pair_session.id, role=role)
            return

        await _start_phase3_answering(
            message,
            state,
            pair_session_id=pair_session.id,
            role=role,
            dispatcher=dispatcher,
            bot=message.bot,
        )
        return

    if not progress["phase4"]["completed"]:
        role_done = bool(progress["phase4"][f"{role}_done"])
        if role_done:
            await _set_pair_state(
                state,
                PairTestStates.phase4_waiting_other,
                phase=4,
                pair_task_id=pair_session.id,
                pair_session_id=pair_session.id,
                user_id=user.id,
                role=role,
                question_index=PHASE4_REQUIRED_COUNT - 1,
                phase_completed=True,
                waiting_for_other=True,
            )
            await message.answer("⏳ Пока ждём второго участника")
            return

        await _start_phase4_selecting(message, state, pair_session_id=pair_session.id, role=role)
        return

    await _send_final_report(message, pair_session_id=pair_session.id)


@router.callback_query(F.data == PAIR_RESUME_FLOW)
async def cb_resume_flow(callback: CallbackQuery, state: FSMContext, dispatcher: Dispatcher) -> None:
    if callback.from_user is None or callback.message is None:
        return
    await callback.answer()
    await _resume_pair_for_actor(
        actor_tg_id=callback.from_user.id,
        message=callback.message,
        state=state,
        dispatcher=dispatcher,
    )


@router.callback_query(F.data == PAIR_MISSION_DONE)
async def cb_mission_done(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    await callback.answer()
    await callback.message.answer(
        "🔥 Отлично! Это уже шаг вперёд.\n\n"
        "Хотите пройти тест ещё раз и посмотреть, что изменилось?\n\n"
        "Нажмите /start и выберите «🧪 Пройти тест»."
    )


@router.message(F.text == RESUME_PAIR_TEST_TEXT)
async def msg_resume_pair_test(message: Message, state: FSMContext, dispatcher: Dispatcher) -> None:
    if message.from_user is None:
        return
    await _resume_pair_for_actor(
        actor_tg_id=message.from_user.id,
        message=message,
        state=state,
        dispatcher=dispatcher,
    )


@router.message(PairTestStates.waiting_phase1_score)
async def msg_phase1_score_fallback(message: Message) -> None:
    await message.answer("Для ответа используйте кнопку с оценкой 1-10.")


@router.message(PairTestStates.phase2_answering)
async def msg_phase2_fallback(message: Message) -> None:
    await message.answer("Для ответа используйте кнопки 1-4 под вопросом.")


@router.message(PairTestStates.phase1_waiting_other)
@router.message(PairTestStates.phase2_waiting_other)
@router.message(PairTestStates.phase4_waiting_other)
async def msg_pair_waiting_other(message: Message) -> None:
    await message.answer(
        "⏳ Вы ответили.\n\nЖдём второго участника, чтобы продолжить 👇",
        reply_markup=pair_waiting_keyboard(),
    )


@router.message(PairTest.phase_2)
async def msg_pair_phase2_generic(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("waiting_for_other"):
        await message.answer(
            "⏳ Вы ответили.\n\nЖдём второго участника, чтобы продолжить 👇",
            reply_markup=pair_waiting_keyboard(),
        )
        return
    await message.answer("Для ответа используйте кнопки 1-4 под вопросом.")


@router.message(PairTestStates.phase3_selecting_scenarios)
async def msg_phase3_select_fallback(message: Message) -> None:
    await message.answer("Используйте кнопки выбора сценариев и кнопку «Готово».")


@router.message(PairTestStates.phase3_answering)
async def msg_phase3_answer_fallback(message: Message) -> None:
    await message.answer("Выберите вариант кнопкой под сценарием.")


@router.message(PairTest.phase_3)
async def msg_pair_phase3_generic(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("waiting_for_other"):
        await message.answer(
            "⏳ Вы ответили.\n\nЖдём второго участника, чтобы продолжить 👇",
            reply_markup=pair_waiting_keyboard(),
        )
        return
    if data.get("phase3_current_scenario_id"):
        await message.answer("Выберите вариант кнопкой под сценарием.")
        return
    await message.answer("Используйте кнопки выбора сценариев и кнопку «Готово».")


@router.message(PairTestStates.phase4_selecting_values)
async def msg_phase4_select_fallback(message: Message) -> None:
    await message.answer("Выберите ровно 5 ценностей кнопками и нажмите подтверждение.")


@router.message(PairTest.phase_4)
async def msg_pair_phase4_generic(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("waiting_for_other"):
        await message.answer(
            "⏳ Вы ответили.\n\nЖдём второго участника, чтобы продолжить 👇",
            reply_markup=pair_waiting_keyboard(),
        )
        return
    await message.answer("Выберите ровно 5 ценностей кнопками и нажмите подтверждение.")


@router.callback_query(PairTestStates.entering_code)
async def cb_entering_code_fallback(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    await callback.answer("Сейчас нужно ввести код текстом", show_alert=True)
    await callback.message.answer("Введите код, который вам отправил родитель.")


@router.callback_query(PairTestStates.waiting_phase1_word)
async def cb_phase1_word_fallback(callback: CallbackQuery) -> None:
    await callback.answer("Сейчас нужно ввести одно слово сообщением", show_alert=True)


@router.callback_query(PairTestStates.completed)
async def cb_completed_fallback(callback: CallbackQuery) -> None:
    await callback.answer("Сессия уже завершена")


@router.callback_query()
async def debug_all_callbacks(callback: CallbackQuery, state: FSMContext) -> None:
    # Temporary debug hook for callback routing diagnostics.
    current_state = await state.get_state()
    log.warning("[PAIR_CALLBACK_FALLBACK] data=%s state=%s", callback.data, current_state)
    await callback.answer()

