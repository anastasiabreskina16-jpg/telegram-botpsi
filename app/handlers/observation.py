from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.db.models import User
from app.db.session import AsyncSessionLocal
from app.keyboards.family import family_status_keyboard
from app.keyboards.observation import (
    OBS_ADD_TEXT,
    OBS_BACK_TO_DIARY_TEXT,
    OBS_BACK_TO_FAMILY_TEXT,
    OBS_CATEGORY_BACK,
    OBS_CATEGORY_PREFIX,
    OBS_CONFIRM_CANCEL,
    OBS_CONFIRM_SAVE,
    OBS_ENERGY_PREFIX,
    OBS_ENERGY_SKIP,
    OBS_MY_LIMIT_PREFIX,
    OBS_MY_TEXT,
    OBS_OVERVIEW_TEXT,
    OBS_PAIR_TASK_ACTIVE_TEXT,
    OBS_PAIR_TASK_BY_NOTES_TEXT,
    OBS_PAIR_TASK_COMPLETE_TEXT,
    OBS_PAIR_TASK_DONE_PREFIX,
    OBS_PAIR_TASK_GET_TEXT,
    OBS_PAIR_TASK_HISTORY_TEXT,
    OBS_PAIR_TASK_INVITE_ACCEPT_PREFIX,
    OBS_PAIR_TASK_INVITE_LATER_PREFIX,
    OBS_PAIR_TASK_LATER_PREFIX,
    OBS_PAIR_TASK_OTHER_PREFIX,
    OBS_PAIR_TASK_TEXT,
    OBS_WEEKLY_TEXT,
    OBSERVATION_MENU_TEXT,
    observation_categories_keyboard,
    observation_confirm_keyboard,
    observation_energy_keyboard,
    observation_menu_keyboard,
    observation_my_records_keyboard,
    observation_pair_task_action_keyboard,
    observation_pair_task_invite_keyboard,
    observation_pair_task_menu_keyboard,
)
from app.services.family_service import get_family_status_for_user
from app.services.observation_service import (
    build_overview_text,
    build_weekly_summary_text,
    create_observation_entry,
    get_categories_for_role,
    get_family_observation_entries,
    get_label_for_kind,
    get_user_observation_entries,
)
from app.services.pair_task_service import (
    accept_pair_task_invite,
    complete_pair_task,
    create_pair_task,
    get_user_answers_count,
    get_active_pair_task,
    get_family_context,
    get_latest_pending_invite_task,
    get_pair_task_by_id,
    get_pair_task_history,
    get_reflection_questions_for_role,
    has_role_responses_for_task,
    render_pair_task_text,
    save_pair_task_response,
    set_pair_task_status,
    suggest_task_code_from_observations,
)
from app.services.user_service import get_or_create_user
from app.states.observation import ObservationStates
from app.states.registration import RegistrationStates
from app.texts import OBS_TEXTS

router = Router(name="observation")


def _parse_task_id(data: str | None, prefix: str) -> int | None:
    if data is None or not data.startswith(prefix):
        return None
    raw = data[len(prefix):].strip()
    if not raw.isdigit():
        return None
    value = int(raw)
    return value if value > 0 else None


def _render_my_entries_text(entries) -> str:
    if not entries:
        return OBS_TEXTS["my_entries_empty"]

    lines = ["Ваши последние наблюдения", ""]
    for entry in entries:
        day = entry.created_at.strftime("%d.%m")
        label = get_label_for_kind(entry.entry_kind)
        score_text = f" — энергия {entry.score}" if entry.score is not None else ""
        lines.append(f"{day} — {label}: \"{entry.text}\"{score_text}")
    return "\n".join(lines)


def _render_pair_task_history_text(history) -> str:
    if not history:
        return OBS_TEXTS["pair_history_empty"]

    lines = ["История парных задач", ""]
    for item in history[:10]:
        date = item.created_at.strftime("%d.%m")
        status = {
            "active": "активна",
            "pending_invite": "ожидает подтверждения",
            "postponed": "отложена",
            "completed": "завершена",
            "cancelled": "отменена",
        }.get(item.status, item.status)
        lines.append(f"{date} — {item.title} ({status})")
    return "\n".join(lines)


def _pair_task_completed_text() -> str:
    return f"{OBS_TEXTS['pair_completed']}\n{OBS_TEXTS['add_short_note']}"


def get_next_question_index(total_answers: int, total_questions: int) -> int | None:
    if total_answers >= total_questions:
        return None
    return total_answers


async def both_users_completed_phase(session, pair_task_id: int) -> bool:
    teen_done = await has_role_responses_for_task(
        session,
        pair_task_id=pair_task_id,
        role="teen",
    )
    parent_done = await has_role_responses_for_task(
        session,
        pair_task_id=pair_task_id,
        role="parent",
    )
    return teen_done and parent_done


async def _handle_pair_task_reflection_answer(message: Message, state: FSMContext) -> None:
    assert message.from_user is not None

    text = (message.text or "").strip()
    if not text:
        await message.answer("Ответ не должен быть пустым. Напишите 1-2 коротких предложения.")
        return

    data = await state.get_data()
    pair_task_id = data.get("pair_task_id")
    role = data.get("reflection_role")
    task_code = data.get("reflection_task_code")
    qcode = data.get("reflection_question_code")

    if (
        not isinstance(pair_task_id, int)
        or not isinstance(role, str)
        or not isinstance(task_code, str)
        or not isinstance(qcode, str)
    ):
        await state.clear()
        await message.answer("Состояние рефлексии потеряно. Откройте 'Парная задача' снова.")
        return

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, message.from_user)
        await save_pair_task_response(
            session,
            pair_task_id=pair_task_id,
            user_id=user.id,
            role=role,
            question_code=qcode,
            answer_text=text,
        )
        count = await get_user_answers_count(
            session,
            pair_task_id=pair_task_id,
            user_id=user.id,
        )

        questions = get_reflection_questions_for_role(role, task_code=task_code)
        next_idx = get_next_question_index(count, len(questions))

        if next_idx is not None:
            next_code, next_question = questions[next_idx]
            await state.set_state(ObservationStates.entering_pair_task_reflection_2)
            await state.update_data(reflection_question_code=next_code)
            await session.commit()
            await message.answer(f"Вопрос {count + 1}/{len(questions)}\n\n{next_question}")
            return

        completed = await both_users_completed_phase(session, pair_task_id)
        await session.commit()

    await state.set_state(ObservationStates.in_pair_task_menu)
    if completed:
        await message.answer("Переходим к следующей фазе.", reply_markup=observation_pair_task_menu_keyboard())
        return

    await message.answer(
        "Вы завершили фазу. Ожидаем второго участника.",
        reply_markup=observation_pair_task_menu_keyboard(),
    )


async def _deactivate_task_card(callback: CallbackQuery, *, text_suffix: str | None = None) -> None:
    if callback.message is None:
        return

    base_text = callback.message.text or "Карточка задачи"
    new_text = base_text
    if isinstance(text_suffix, str) and text_suffix.strip():
        new_text = f"{base_text}\n\n{text_suffix.strip()}"

    try:
        await callback.message.edit_text(new_text, reply_markup=None)
    except Exception:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass


async def _show_stale_card_alert(callback: CallbackQuery, text: str = OBS_TEXTS["stale_card"]) -> None:
    await callback.answer(text, show_alert=True)


async def _ensure_diary_access(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state == RegistrationStates.answering_test.state:
        await message.answer(OBS_TEXTS["need_finish_test"])
        return None, None

    state_data = await state.get_data()
    if state_data.get("mode") == "pair_test":
        await message.answer("Сначала завершите «Диалог о выборе» или дождитесь завершения текущей фазы.")
        return None, None

    assert message.from_user is not None
    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, message.from_user)
        family_status = await get_family_status_for_user(session, user_id=user.id)

    if user.role not in {"teen", "parent"}:
        await message.answer(OBS_TEXTS["need_role"])
        return None, None
    if not family_status.has_family_link:
        await message.answer(
            OBS_TEXTS["need_family_link"],
            reply_markup=family_status_keyboard(role=user.role, has_family_link=False),
        )
        return None, None

    return user, family_status


async def _get_task_access_for_tg_user(session, *, telegram_user, pair_task_id: int):
    db_user, _ = await get_or_create_user(session, telegram_user)
    family_status = await get_family_status_for_user(session, user_id=db_user.id)
    if not family_status.has_family_link:
        return None

    family_link, me, peer_user = await get_family_context(session, user_id=db_user.id)
    if family_link is None or me is None:
        return None

    task = await get_pair_task_by_id(session, pair_task_id=pair_task_id)
    if task is None or task.family_link_id != family_link.id:
        return None

    return task, db_user, me, peer_user


async def _start_observation_entry_flow(message: Message, state: FSMContext, *, role: str) -> None:
    categories = get_categories_for_role(role)
    await state.set_state(ObservationStates.choosing_category)
    await state.update_data(observer_role=role)
    title = "Что хотите отметить?" if role == "teen" else "Что хотите отметить о ребёнке?"
    await message.answer(_pair_task_completed_text(), reply_markup=observation_menu_keyboard())
    await message.answer(title, reply_markup=observation_categories_keyboard(categories))


async def _notify_peer_to_add_observation(message: Message, *, peer_user: User | None) -> None:
    if peer_user is None or peer_user.telegram_id is None:
        return
    try:
        await message.bot.send_message(peer_user.telegram_id, _pair_task_completed_text(), reply_markup=observation_menu_keyboard())
        await message.bot.send_message(peer_user.telegram_id, "Откройте дневник наблюдений и нажмите «Добавить наблюдение».")
    except Exception:
        pass


async def _create_pending_invite_and_notify(
    message: Message,
    *,
    family_link_id: int,
    created_by_user_id: int,
    invited_user: User,
    source_type: str,
    preferred_code: str | None = None,
    replace_active: bool = False,
) -> None:
    async with AsyncSessionLocal() as session:
        task = await create_pair_task(
            session,
            family_link_id=family_link_id,
            created_by_user_id=created_by_user_id,
            invited_user_id=invited_user.id,
            source_type=source_type,
            preferred_code=preferred_code,
            replace_active=replace_active,
            initial_status="pending_invite",
        )

    await message.answer(
        OBS_TEXTS["invite_sent"],
        reply_markup=observation_pair_task_menu_keyboard(),
    )

    try:
        await message.bot.send_message(
            invited_user.telegram_id,
            "Вам предлагают парную задачу.\n\n" + render_pair_task_text(task),
            reply_markup=observation_pair_task_invite_keyboard(task_id=task.id),
        )
    except Exception:
        await message.answer(OBS_TEXTS["invite_send_failed"])


async def _start_reflection_for_user(
    message: Message,
    state: FSMContext,
    *,
    pair_task_id: int,
    role: str,
    task_code: str,
) -> None:
    questions = get_reflection_questions_for_role(role, task_code=task_code)
    if not questions:
        await state.set_state(ObservationStates.in_pair_task_menu)
        await message.answer("Спасибо. Рефлексия по этой задаче не требуется.", reply_markup=observation_pair_task_menu_keyboard())
        return

    first_code, first_question = questions[0]
    await state.set_state(ObservationStates.entering_pair_task_reflection_1)
    await state.update_data(
        pair_task_id=pair_task_id,
        reflection_role=role,
        reflection_task_code=task_code,
        reflection_question_code=first_code,
    )
    await message.answer(first_question)


async def _complete_task_and_prompt_reflection(
    message: Message,
    state: FSMContext,
    *,
    pair_task_id: int,
) -> None:
    assert message.from_user is not None

    async with AsyncSessionLocal() as session:
        db_user, _ = await get_or_create_user(session, message.from_user)
        family_link, me, peer_user = await get_family_context(session, user_id=db_user.id)
        if family_link is None or me is None:
            await message.answer("Семейная связь не найдена. Сначала подключите семью.")
            return

        task = await complete_pair_task(session, pair_task_id=pair_task_id)
        if task is None or task.family_link_id != family_link.id:
            await message.answer("Задача недоступна или уже закрыта.")
            return

    await message.answer(OBS_TEXTS["task_done"])
    await _start_reflection_for_user(
        message,
        state,
        pair_task_id=pair_task_id,
        role=me.role or "teen",
        task_code=task.task_code,
    )

    if peer_user is not None and peer_user.telegram_id != message.from_user.id:
        try:
            await message.bot.send_message(
                peer_user.telegram_id,
                "Семейная парная задача завершена. Зайдите в 'Дневник наблюдений -> Парная задача -> Завершить задачу', чтобы ответить на 2 коротких вопроса.",
                reply_markup=observation_pair_task_menu_keyboard(),
            )
        except Exception:
            pass


@router.message(F.text == OBSERVATION_MENU_TEXT)
async def msg_open_observation_menu(message: Message, state: FSMContext) -> None:
    user, _ = await _ensure_diary_access(message, state)
    if user is None:
        return

    await state.set_state(ObservationStates.in_menu)
    await message.answer(
        OBS_TEXTS["diary_intro"],
        reply_markup=observation_menu_keyboard(),
    )


@router.message(F.text == OBS_PAIR_TASK_TEXT)
async def msg_open_pair_task_menu(message: Message, state: FSMContext) -> None:
    user, _ = await _ensure_diary_access(message, state)
    if user is None:
        return

    await state.set_state(ObservationStates.in_pair_task_menu)
    await message.answer(
        OBS_TEXTS["pair_intro"],
        reply_markup=observation_pair_task_menu_keyboard(),
    )


@router.message(ObservationStates.in_pair_task_menu, F.text == OBS_BACK_TO_DIARY_TEXT)
async def msg_pair_task_back(message: Message, state: FSMContext) -> None:
    await state.set_state(ObservationStates.in_menu)
    await message.answer(OBS_TEXTS["diary_section"], reply_markup=observation_menu_keyboard())


@router.message(F.text == OBS_PAIR_TASK_GET_TEXT)
async def msg_pair_task_get(message: Message, state: FSMContext) -> None:
    assert message.from_user is not None
    user, _ = await _ensure_diary_access(message, state)
    if user is None:
        return

    async with AsyncSessionLocal() as session:
        family_link, me, peer_user = await get_family_context(session, user_id=user.id)
        if family_link is None:
            await message.answer("Семейная связь не найдена.")
            return

        active = await get_active_pair_task(session, family_link_id=family_link.id)
        if active is not None:
            await state.set_state(ObservationStates.in_pair_task_menu)
            await message.answer(
                render_pair_task_text(active),
                reply_markup=observation_pair_task_action_keyboard(task_id=active.id),
            )
            return

        pending = await get_latest_pending_invite_task(session, family_link_id=family_link.id)
        if pending is not None:
            await state.set_state(ObservationStates.in_pair_task_menu)
            if pending.invited_user_id == user.id:
                await message.answer(
                    "Для вас есть приглашение в парную задачу.",
                    reply_markup=observation_pair_task_invite_keyboard(task_id=pending.id),
                )
                await message.answer(render_pair_task_text(pending))
            else:
                await message.answer(OBS_TEXTS["waiting_second_side"])
            return

    if me is None or peer_user is None or peer_user.telegram_id is None:
        await message.answer("Не удалось определить второго участника семьи.")
        return

    await state.set_state(ObservationStates.in_pair_task_menu)
    await _create_pending_invite_and_notify(
        message,
        family_link_id=family_link.id,
        created_by_user_id=me.id,
        invited_user=peer_user,
        source_type="manual",
    )


@router.message(F.text == OBS_PAIR_TASK_BY_NOTES_TEXT)
async def msg_pair_task_by_observations(message: Message, state: FSMContext) -> None:
    assert message.from_user is not None
    user, _ = await _ensure_diary_access(message, state)
    if user is None:
        return

    async with AsyncSessionLocal() as session:
        family_link, me, peer_user = await get_family_context(session, user_id=user.id)
        if family_link is None:
            await message.answer("Семейная связь не найдена.")
            return

        active = await get_active_pair_task(session, family_link_id=family_link.id)
        if active is not None:
            await message.answer(
                "Сейчас уже есть активная задача. Можно завершить ее или выбрать 'Другая задача'.",
                reply_markup=observation_pair_task_action_keyboard(task_id=active.id),
            )
            return

        pending = await get_latest_pending_invite_task(session, family_link_id=family_link.id)
        if pending is not None:
            await state.set_state(ObservationStates.in_pair_task_menu)
            if pending.invited_user_id == user.id:
                await message.answer(
                    "Для вас есть приглашение в парную задачу.",
                    reply_markup=observation_pair_task_invite_keyboard(task_id=pending.id),
                )
                await message.answer(render_pair_task_text(pending))
            else:
                await message.answer(OBS_TEXTS["waiting_second_side"])
            return

        suggested = await suggest_task_code_from_observations(session, family_link_id=family_link.id)

    if me is None or peer_user is None or peer_user.telegram_id is None:
        await message.answer("Не удалось определить второго участника семьи.")
        return

    await state.set_state(ObservationStates.in_pair_task_menu)
    await _create_pending_invite_and_notify(
        message,
        family_link_id=family_link.id,
        created_by_user_id=me.id,
        invited_user=peer_user,
        source_type="observation",
        preferred_code=suggested,
    )


@router.message(F.text == OBS_PAIR_TASK_ACTIVE_TEXT)
async def msg_pair_task_active(message: Message, state: FSMContext) -> None:
    assert message.from_user is not None
    user, _ = await _ensure_diary_access(message, state)
    if user is None:
        return

    async with AsyncSessionLocal() as session:
        family_link, _, _ = await get_family_context(session, user_id=user.id)
        if family_link is None:
            await message.answer("Семейная связь не найдена.")
            return

        active = await get_active_pair_task(session, family_link_id=family_link.id)
        pending = await get_latest_pending_invite_task(session, family_link_id=family_link.id)

    await state.set_state(ObservationStates.in_pair_task_menu)
    if active is not None:
        await message.answer(
            render_pair_task_text(active),
            reply_markup=observation_pair_task_action_keyboard(task_id=active.id),
        )
        return

    if pending is not None:
        if pending.invited_user_id == user.id:
            await message.answer("Есть ожидающее приглашение. Подтвердите задачу.", reply_markup=observation_pair_task_invite_keyboard(task_id=pending.id))
            await message.answer(render_pair_task_text(pending))
        else:
            await message.answer("Есть задача, ожидающая подтверждения второй стороны.")
        return

    await message.answer("Сейчас активной парной задачи нет.")


@router.message(F.text == OBS_PAIR_TASK_COMPLETE_TEXT)
async def msg_pair_task_complete(message: Message, state: FSMContext) -> None:
    assert message.from_user is not None
    user, _ = await _ensure_diary_access(message, state)
    if user is None:
        return

    async with AsyncSessionLocal() as session:
        family_link, me, peer_user = await get_family_context(session, user_id=user.id)
        if family_link is None or me is None:
            await message.answer("Семейная связь не найдена.")
            return

        active = await get_active_pair_task(session, family_link_id=family_link.id)
        if active is None:
            await state.set_state(ObservationStates.in_pair_task_menu)
            await message.answer("Нет активной задачи для завершения.")
            return

        await complete_pair_task(session, pair_task_id=active.id)

    await _start_observation_entry_flow(message, state, role=me.role or "teen")
    await _notify_peer_to_add_observation(message, peer_user=peer_user)


@router.message(F.text == OBS_PAIR_TASK_HISTORY_TEXT)
async def msg_pair_task_history(message: Message, state: FSMContext) -> None:
    assert message.from_user is not None
    user, _ = await _ensure_diary_access(message, state)
    if user is None:
        return

    async with AsyncSessionLocal() as session:
        family_link, _, _ = await get_family_context(session, user_id=user.id)
        if family_link is None:
            await message.answer("Семейная связь не найдена.")
            return

        history = await get_pair_task_history(session, family_link_id=family_link.id, limit=10)

    await state.set_state(ObservationStates.in_pair_task_menu)
    await message.answer(_render_pair_task_history_text(history), reply_markup=observation_pair_task_menu_keyboard())


@router.callback_query(F.data.startswith(OBS_PAIR_TASK_DONE_PREFIX))
async def cb_pair_task_done(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.message is not None
    assert callback.from_user is not None
    await callback.answer()

    pair_task_id = _parse_task_id(callback.data, OBS_PAIR_TASK_DONE_PREFIX)
    if pair_task_id is None:
        await callback.message.answer(OBS_TEXTS["task_invalid"])
        return

    async with AsyncSessionLocal() as session:
        access = await _get_task_access_for_tg_user(session, telegram_user=callback.from_user, pair_task_id=pair_task_id)
        if access is None:
            await _show_stale_card_alert(callback)
            return

        task, _, me, peer_user = access
        if task.status != "active":
            await _show_stale_card_alert(callback)
            return

        await complete_pair_task(session, pair_task_id=task.id)

    await _deactivate_task_card(callback, text_suffix="Статус: завершена")
    await _start_observation_entry_flow(callback.message, state, role=me.role or "teen")
    await _notify_peer_to_add_observation(callback.message, peer_user=peer_user)


@router.callback_query(F.data.startswith(OBS_PAIR_TASK_LATER_PREFIX))
async def cb_pair_task_later(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.message is not None
    assert callback.from_user is not None
    await callback.answer()

    pair_task_id = _parse_task_id(callback.data, OBS_PAIR_TASK_LATER_PREFIX)
    if pair_task_id is None:
        await callback.message.answer(OBS_TEXTS["task_invalid"])
        return

    async with AsyncSessionLocal() as session:
        access = await _get_task_access_for_tg_user(session, telegram_user=callback.from_user, pair_task_id=pair_task_id)
        if access is None:
            await _show_stale_card_alert(callback)
            return
        task, _, _, _ = access
        if task.status not in {"active", "pending_invite"}:
            await _show_stale_card_alert(callback)
            return
        await set_pair_task_status(session, pair_task_id=task.id, status="postponed")

    await _deactivate_task_card(callback, text_suffix="Статус: отложена")
    await state.set_state(ObservationStates.in_pair_task_menu)
    await callback.message.answer(OBS_TEXTS["task_postponed"])


@router.callback_query(F.data.startswith(OBS_PAIR_TASK_OTHER_PREFIX))
async def cb_pair_task_other(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.from_user is not None
    assert callback.message is not None
    await callback.answer()

    pair_task_id = _parse_task_id(callback.data, OBS_PAIR_TASK_OTHER_PREFIX)
    if pair_task_id is None:
        await callback.message.answer(OBS_TEXTS["task_invalid"])
        return

    async with AsyncSessionLocal() as session:
        access = await _get_task_access_for_tg_user(session, telegram_user=callback.from_user, pair_task_id=pair_task_id)
        if access is None:
            await _show_stale_card_alert(callback)
            return

        task, db_user, _, peer_user = access
        if task.family_link_id is None or peer_user is None or peer_user.telegram_id is None:
            await _show_stale_card_alert(callback, "Не удалось определить второго участника семьи.")
            return
        if task.status not in {"active", "pending_invite", "postponed"}:
            await _show_stale_card_alert(callback)
            return

        await set_pair_task_status(session, pair_task_id=task.id, status="cancelled")

    await _deactivate_task_card(callback, text_suffix="Задача заменена новой.")
    await state.set_state(ObservationStates.in_pair_task_menu)
    await _create_pending_invite_and_notify(
        callback.message,
        family_link_id=task.family_link_id,
        created_by_user_id=db_user.id,
        invited_user=peer_user,
        source_type="manual",
        replace_active=True,
    )


@router.callback_query(F.data.startswith(OBS_PAIR_TASK_INVITE_ACCEPT_PREFIX))
async def cb_pair_task_invite_accept(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.message is not None
    assert callback.from_user is not None
    await callback.answer()

    pair_task_id = _parse_task_id(callback.data, OBS_PAIR_TASK_INVITE_ACCEPT_PREFIX)
    if pair_task_id is None:
        await callback.message.answer(OBS_TEXTS["task_invalid"])
        return

    async with AsyncSessionLocal() as session:
        access = await _get_task_access_for_tg_user(session, telegram_user=callback.from_user, pair_task_id=pair_task_id)
        if access is None:
            await _show_stale_card_alert(callback)
            return

        task, db_user, _, peer_user = access
        if task.invited_user_id is not None and task.invited_user_id != db_user.id:
            await _show_stale_card_alert(callback, "Это приглашение предназначено не вам.")
            return

        activated = await accept_pair_task_invite(session, pair_task_id=task.id, accepter_user_id=db_user.id)
        if activated is None:
            await _show_stale_card_alert(callback, "Не удалось активировать задачу.")
            return

    await _deactivate_task_card(callback, text_suffix="Приглашение подтверждено.")
    text = "Парная задача активирована. Теперь вы можете выполнять её вместе.\n\n" + render_pair_task_text(activated)
    await state.set_state(ObservationStates.in_pair_task_menu)
    await callback.message.answer(text, reply_markup=observation_pair_task_action_keyboard(task_id=activated.id))
    if peer_user is not None and peer_user.telegram_id is not None and peer_user.telegram_id != callback.from_user.id:
        try:
            await callback.message.bot.send_message(
                peer_user.telegram_id,
                text,
                reply_markup=observation_pair_task_action_keyboard(task_id=activated.id),
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith(OBS_PAIR_TASK_INVITE_LATER_PREFIX))
async def cb_pair_task_invite_later(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.message is not None
    assert callback.from_user is not None
    await callback.answer()

    pair_task_id = _parse_task_id(callback.data, OBS_PAIR_TASK_INVITE_LATER_PREFIX)
    if pair_task_id is None:
        await callback.message.answer(OBS_TEXTS["task_invalid"])
        return

    async with AsyncSessionLocal() as session:
        access = await _get_task_access_for_tg_user(session, telegram_user=callback.from_user, pair_task_id=pair_task_id)
        if access is None:
            await _show_stale_card_alert(callback)
            return

        task, db_user, _, peer_user = access
        if task.invited_user_id is not None and task.invited_user_id != db_user.id:
            await _show_stale_card_alert(callback, "Это приглашение предназначено не вам.")
            return

        await set_pair_task_status(session, pair_task_id=task.id, status="postponed")

    await _deactivate_task_card(callback, text_suffix="Статус: отложена")
    await state.set_state(ObservationStates.in_pair_task_menu)
    await callback.message.answer("Принято. Вы можете вернуться к приглашению позже.")
    if peer_user is not None and peer_user.telegram_id is not None and peer_user.telegram_id != callback.from_user.id:
        try:
            await callback.message.bot.send_message(peer_user.telegram_id, "Второй участник пока не подтвердил задачу.")
        except Exception:
            pass


@router.message(ObservationStates.entering_pair_task_reflection_1)
async def msg_pair_task_reflection_1(message: Message, state: FSMContext) -> None:
    await _handle_pair_task_reflection_answer(message, state)


@router.message(ObservationStates.entering_pair_task_reflection_2)
async def msg_pair_task_reflection_2(message: Message, state: FSMContext) -> None:
    await _handle_pair_task_reflection_answer(message, state)


@router.message(ObservationStates.in_menu, F.text == OBS_BACK_TO_FAMILY_TEXT)
async def msg_observation_back(message: Message, state: FSMContext) -> None:
    assert message.from_user is not None

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, message.from_user)
        family_status = await get_family_status_for_user(session, user_id=user.id)

    await state.clear()
    await message.answer(
        family_status.status_text,
        reply_markup=family_status_keyboard(
            role=user.role,
            has_family_link=family_status.has_family_link,
        ),
    )


@router.message(F.text == OBS_ADD_TEXT)
async def msg_add_observation(message: Message, state: FSMContext) -> None:
    user, _ = await _ensure_diary_access(message, state)
    if user is None:
        return

    categories = get_categories_for_role(user.role)
    await state.set_state(ObservationStates.choosing_category)
    await state.update_data(observer_role=user.role)

    title = "Что хотите отметить?" if user.role == "teen" else "Что хотите отметить о ребёнке?"
    await message.answer(
        title,
        reply_markup=observation_categories_keyboard(categories),
    )


@router.callback_query(ObservationStates.choosing_category, F.data == OBS_CATEGORY_BACK)
async def cb_observation_category_back(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.message is not None
    await callback.answer()
    await state.set_state(ObservationStates.in_menu)
    await callback.message.answer(OBS_TEXTS["diary_section"], reply_markup=observation_menu_keyboard())


@router.callback_query(ObservationStates.choosing_category, F.data.startswith(OBS_CATEGORY_PREFIX))
async def cb_observation_category_selected(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.message is not None

    category = callback.data.removeprefix(OBS_CATEGORY_PREFIX) if callback.data else ""
    data = await state.get_data()
    role = data.get("observer_role")
    valid_codes = {code for code, _ in get_categories_for_role(role)}
    if category not in valid_codes:
        await callback.answer("Выберите категорию кнопкой.")
        return

    await callback.answer()
    await state.update_data(entry_kind=category)
    await state.set_state(ObservationStates.entering_text)
    await callback.message.answer("Опишите это коротко одним-двумя предложениями.")


@router.message(ObservationStates.entering_text)
async def msg_observation_text(message: Message, state: FSMContext) -> None:
    note_text = (message.text or "").strip()
    if not note_text:
        await message.answer("Текст не должен быть пустым. Напишите короткое наблюдение.")
        return
    if len(note_text) > 600:
        await message.answer("Слишком длинно. Сократите, пожалуйста, до 600 символов.")
        return

    await state.update_data(note_text=note_text)
    await state.set_state(ObservationStates.choosing_energy)
    await message.answer(
        "Насколько это было заметно / сильно?",
        reply_markup=observation_energy_keyboard(),
    )


@router.callback_query(ObservationStates.choosing_energy, F.data.startswith(OBS_ENERGY_PREFIX))
async def cb_observation_energy_selected(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.message is not None

    raw = callback.data.removeprefix(OBS_ENERGY_PREFIX) if callback.data else ""
    if raw not in {"1", "2", "3", "4", "5"}:
        await callback.answer("Выберите оценку кнопкой.")
        return

    await callback.answer()
    score = int(raw)
    await state.update_data(score=score)
    await state.set_state(ObservationStates.confirming_save)
    await callback.message.answer("Сохранить запись?", reply_markup=observation_confirm_keyboard())


@router.callback_query(ObservationStates.choosing_energy, F.data == OBS_ENERGY_SKIP)
async def cb_observation_energy_skip(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.message is not None
    await callback.answer()
    await state.update_data(score=None)
    await state.set_state(ObservationStates.confirming_save)
    await callback.message.answer("Сохранить запись?", reply_markup=observation_confirm_keyboard())


@router.callback_query(ObservationStates.confirming_save, F.data == OBS_CONFIRM_CANCEL)
async def cb_observation_confirm_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.message is not None
    await callback.answer()
    await state.set_state(ObservationStates.in_menu)
    await callback.message.answer("Запись отменена.", reply_markup=observation_menu_keyboard())


@router.callback_query(ObservationStates.confirming_save, F.data == OBS_CONFIRM_SAVE)
async def cb_observation_confirm_save(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.from_user is not None
    assert callback.message is not None
    await callback.answer()

    data = await state.get_data()
    observer_role = data.get("observer_role")
    entry_kind = data.get("entry_kind")
    note_text = data.get("note_text")
    score = data.get("score")

    if (
        observer_role not in {"teen", "parent"}
        or not isinstance(entry_kind, str)
        or not isinstance(note_text, str)
    ):
        await state.clear()
        await callback.message.answer(
            "Состояние записи потеряно. Нажмите 'Добавить наблюдение' ещё раз.",
            reply_markup=observation_menu_keyboard(),
        )
        return

    if score is not None and (not isinstance(score, int) or score < 1 or score > 5):
        await state.clear()
        await callback.message.answer(
            "Состояние записи потеряно. Нажмите 'Добавить наблюдение' ещё раз.",
            reply_markup=observation_menu_keyboard(),
        )
        return

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, callback.from_user)
        try:
            await create_observation_entry(
                session,
                user_id=user.id,
                observer_role=observer_role,
                entry_kind=entry_kind,
                text=note_text,
                score=score,
            )
        except ValueError:
            await state.clear()
            await callback.message.answer(
                "Не удалось сохранить запись. Проверьте, что семейная связь активна, и попробуйте снова.",
                reply_markup=observation_menu_keyboard(),
            )
            return

    await state.set_state(ObservationStates.in_menu)
    await callback.message.answer(
        OBS_TEXTS["saved_note"],
        reply_markup=observation_menu_keyboard(),
    )


@router.message(F.text == OBS_MY_TEXT)
async def msg_observation_my_records(message: Message, state: FSMContext) -> None:
    user, _ = await _ensure_diary_access(message, state)
    if user is None:
        return

    async with AsyncSessionLocal() as session:
        entries = await get_user_observation_entries(session, user_id=user.id, limit=5)

    await message.answer(
        _render_my_entries_text(entries),
        reply_markup=observation_my_records_keyboard(),
    )


@router.callback_query(F.data.startswith(OBS_MY_LIMIT_PREFIX))
async def cb_observation_my_records_limit(callback: CallbackQuery, state: FSMContext) -> None:
    assert callback.from_user is not None
    assert callback.message is not None

    raw = callback.data.removeprefix(OBS_MY_LIMIT_PREFIX) if callback.data else ""
    if raw not in {"5", "10"}:
        await callback.answer("Некорректный лимит.")
        return

    await callback.answer()
    limit = int(raw)
    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, callback.from_user)
        entries = await get_user_observation_entries(session, user_id=user.id, limit=limit)

    await callback.message.answer(
        _render_my_entries_text(entries),
        reply_markup=observation_my_records_keyboard(),
    )


@router.message(F.text == OBS_OVERVIEW_TEXT)
async def msg_observation_overview(message: Message, state: FSMContext) -> None:
    user, _ = await _ensure_diary_access(message, state)
    if user is None:
        return

    async with AsyncSessionLocal() as session:
        _, entries = await get_family_observation_entries(session, user_id=user.id)

    await message.answer(build_overview_text(entries), reply_markup=observation_menu_keyboard())


@router.message(F.text == OBS_WEEKLY_TEXT)
async def msg_observation_weekly(message: Message, state: FSMContext) -> None:
    user, _ = await _ensure_diary_access(message, state)
    if user is None:
        return

    async with AsyncSessionLocal() as session:
        _, entries = await get_family_observation_entries(session, user_id=user.id, days=7)

    await message.answer(build_weekly_summary_text(entries), reply_markup=observation_menu_keyboard())
