from __future__ import annotations

import builtins
import logging

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ReplyKeyboardRemove

from app.db.session import AsyncSessionLocal
from app.handlers.start import _send_family_invite
from app.keyboards.family import (
    FAMILY_INVITE_CALLBACK,
    family_status_keyboard,
)
from app.keyboards.role import role_keyboard
from app.services.family_service import get_family_for_user, get_family_status_for_user
from app.services.progress_service import format_progress_display
from app.services.result_service import (
    build_progress_text,
    build_result_text,
    compare_results,
    get_last_result,
    get_previous_result,
)
from app.services.test_service import cancel_test_session, get_active_test_session
from app.services.user_service import get_or_create_user
from app.states.registration import RegistrationStates
from app.texts import START_TEXTS

log = logging.getLogger(__name__)
router = Router(name="menu")


@router.callback_query()
async def handle_all_callbacks(call: CallbackQuery, state: FSMContext) -> None:
    builtins.print("CALLBACK:", call.data)
    if call.data is None:
        await call.answer()
        return

    # Telegram requires callback acknowledgement to prevent stuck spinner.
    await call.answer()

    data = call.data
    if data in {"invite_teen", FAMILY_INVITE_CALLBACK}:
        await _handle_invite(call)
        return

    if data == "my_result":
        await _handle_result(call)
        return

    if data == "my_progress":
        await _handle_progress(call)
        return

    if data == "family_status":
        await _handle_family_status(call)
        return

    if data == "refresh_role":
        await _handle_refresh_role(call, state)
        return

    log.info("[MENU_CALLBACK] unhandled callback: %s", data)


async def _handle_invite(call: CallbackQuery) -> None:
    if call.message is None or call.from_user is None:
        return
    await _send_family_invite(call.message, call.from_user)


async def _handle_result(call: CallbackQuery) -> None:
    if call.message is None or call.from_user is None:
        return

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, call.from_user)
        result = await get_last_result(session, user.id)
        previous_result = await get_previous_result(session, user.id)

    if result is None:
        await call.message.answer("У тебя пока нет результатов.\n\nПройди тест, чтобы получить анализ 👇")
        return

    delta = compare_results(
        current=result.diff,
        previous=previous_result.diff if previous_result is not None else None,
    )
    progress_text = build_progress_text(delta)
    await call.message.answer(build_result_text(result) + "\n\n" + progress_text)


async def _handle_progress(call: CallbackQuery) -> None:
    if call.message is None or call.from_user is None:
        return

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, call.from_user)

    await call.message.answer(format_progress_display(user))


async def _handle_family_status(call: CallbackQuery) -> None:
    if call.message is None or call.from_user is None:
        return

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, call.from_user)
        if user.role is None:
            await call.message.answer(START_TEXTS["need_role"])
            return
        family_status = await get_family_status_for_user(session, user_id=user.id)

    await call.message.answer(
        family_status.status_text,
        reply_markup=family_status_keyboard(
            role=family_status.role,
            has_family_link=family_status.has_family_link,
        ),
    )


async def _handle_refresh_role(call: CallbackQuery, state: FSMContext) -> None:
    if call.message is None or call.from_user is None:
        return

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, call.from_user)

        if user.role is None:
            await state.clear()
            await state.set_state(RegistrationStates.waiting_for_role)
            await call.message.answer("Выберите роль:", reply_markup=ReplyKeyboardRemove())
            await call.message.answer(START_TEXTS["choose_role"], reply_markup=role_keyboard())
            return

        linked_family = await get_family_for_user(session, user_id=user.id)
        if linked_family is not None:
            family_status = await get_family_status_for_user(session, user_id=user.id)
            await call.message.answer(
                "Сейчас роль нельзя изменить, потому что у вас активна семейная связь. Сначала отмените связь, потом выберите новую роль.",
                reply_markup=family_status_keyboard(
                    role=user.role,
                    has_family_link=family_status.has_family_link,
                ),
            )
            return

        active_session = await get_active_test_session(session, user_id=user.id)
        if active_session is not None:
            await cancel_test_session(session, session_id=active_session.id)

    await state.clear()
    await state.set_state(RegistrationStates.waiting_for_role)
    await call.message.answer("Обновим роль.", reply_markup=ReplyKeyboardRemove())
    await call.message.answer(START_TEXTS["choose_role"], reply_markup=role_keyboard())
