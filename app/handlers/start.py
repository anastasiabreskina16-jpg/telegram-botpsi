import html
import logging
from pathlib import Path

from aiogram import F, Router, Dispatcher
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message, ReplyKeyboardRemove, User as TgUser
from aiogram.utils.deep_linking import decode_payload
import asyncio

from app.db.session import AsyncSessionLocal
from app.keyboards.family import (
    FAMILY_CONFIRM_PREFIX,
    FAMILY_DECLINE_PREFIX,
    FAMILY_INVITE_CALLBACK,
    FAMILY_INVITE_PARENT_TEXT,
    FAMILY_PSYCHOLOGIST_TEXT,
    FAMILY_INVITE_TEEN_TEXT,
    FAMILY_UNLINK_CANCEL_CALLBACK,
    FAMILY_UNLINK_CONFIRM_CALLBACK,
    FAMILY_UNLINK_TEXT,
    FAMILY_STATUS_TEXT,
    MAIN_MENU_RESULT_TEXT,
    MAIN_MENU_TEST_TEXT,
    PROGRESS_MENU_TEXT,
    family_confirm_keyboard,
    psychologist_link_keyboard,
    family_unlink_confirm_keyboard,
    family_status_keyboard,
)
from app.keyboards.main_menu import RESTART_TEST_CALLBACK, result_keyboard
from app.keyboards.post_summary import (
    POST_SUMMARY_EXTENDED_PREFIX,
    POST_SUMMARY_MENU_PREFIX,
    POST_SUMMARY_RESTART_PREFIX,
    post_summary_keyboard,
)
from app.keyboards.mini_test import MINI_TEST_CALLBACK_PREFIX, mini_test_keyboard
from app.keyboards.mode import MODE_PAIR, MODE_PERSONAL, mode_keyboard
from app.keyboards.role import (
    PARENT_FAMILY_TITLES,
    ROLE_CALLBACK_PREFIX,
    ROLE_LABELS,
    ROLE_REFRESH_TEXT,
    TEEN_FAMILY_TITLES,
    family_title_keyboard,
    role_keyboard,
)
from app.services.family_service import (
    cancel_family_invite,
    create_family_invite,
    get_family_for_user,
    get_family_status_for_user,
    get_linked_family_for_teen,
    get_testable_invite_by_token,
    link_family_by_token,
    unlink_family,
)
from app.services.openai_service import generate_ai_report, generate_expanded_ai_report
from app.services.report_service import (
    build_report_stub,
    get_answers_for_session,
    get_last_completed_session,
    render_expanded_report_text,
    render_report_text,
)
from app.services.segment_service import track_user_event
from app.services.result_service import (
    build_progress_text,
    build_result_text,
    compare_results,
    get_last_result,
    get_previous_result,
)
from app.services.progress_service import (
    award_test_completion,
    award_return_activity,
    format_level_up_message,
    format_progress_display,
    format_streak_milestone,
)
from app.services.test_service import (
    PARENT_TEST_QUESTIONS,
    TEEN_TEST_QUESTIONS,
    cancel_test_session,
    cancel_test_session_inplace,
    complete_test_session,
    complete_test_session_inplace,
    count_answers_for_session,
    create_test_session,
    get_questions_for_role,
    get_questions_for_test_kind,
    get_active_test_session,
    get_test_session_by_id,
    restart_test_session,
    save_answer,
    save_answer_inplace,
)
from app.services.user_service import (
    VALID_ROLES,
    get_or_create_user,
    get_user_by_id,
    get_user_role,
    set_user_role,
    update_user_profile_meta,
)
from app.states.registration import RegistrationStates
from app.texts import START_TEXTS, TEXTS

log = logging.getLogger(__name__)
router = Router(name="start")

_TEEN_MINI_TEST_IMAGE_DIR = Path(__file__).resolve().parents[2] / "assets" / "teen_test"
_PARENT_MINI_TEST_IMAGE_DIR = Path(__file__).resolve().parents[2] / "assets" / "parent_test"

def _build_teen_mini_test_image_map() -> dict[int, str]:
    if not _TEEN_MINI_TEST_IMAGE_DIR.exists():
        log.warning("Teen images folder missing: %s", _TEEN_MINI_TEST_IMAGE_DIR)
        return {}
    return {
        idx: path.name
        for idx, path in enumerate(sorted(_TEEN_MINI_TEST_IMAGE_DIR.glob("*")))
    }


_TEEN_MINI_TEST_IMAGE_MAP = _build_teen_mini_test_image_map()

def _build_parent_mini_test_image_map() -> dict[int, str]:
    if not _PARENT_MINI_TEST_IMAGE_DIR.exists():
        log.warning("Parent images folder missing: %s", _PARENT_MINI_TEST_IMAGE_DIR)
        return {}
    return {
        idx: path.name
        for idx, path in enumerate(sorted(_PARENT_MINI_TEST_IMAGE_DIR.glob("*")))
    }


_PARENT_MINI_TEST_IMAGE_MAP = _build_parent_mini_test_image_map()


def _safe_html_text(value: str | None) -> str:
    return html.escape((value or "").strip())


def _get_mini_test_image_path(
    question_index: int,
    *,
    role: str | None,
    test_kind: str | None,
) -> Path | None:
    if test_kind == "parent_personal" or (test_kind is None and role == "parent"):
        filename = _PARENT_MINI_TEST_IMAGE_MAP.get(question_index)
        if not filename:
            return None
        path = _PARENT_MINI_TEST_IMAGE_DIR / filename
        return path if path.exists() else None

    if test_kind == "teen_personal" or (test_kind is None and role == "teen"):
        filename = _TEEN_MINI_TEST_IMAGE_MAP.get(question_index)
        if not filename:
            return None
        path = _TEEN_MINI_TEST_IMAGE_DIR / filename
        return path if path.exists() else None

    return None


async def _send_mini_test_question(
    message: Message,
    question_index: int,
    *,
    role: str | None,
    test_kind: str | None = None,
) -> None:
    if test_kind:
        questions = get_questions_for_test_kind(test_kind)
    else:
        questions = get_questions_for_role(role)

    question = questions[question_index]
    question_text = question["text"]
    options = question["options"]
    keyboard = mini_test_keyboard(options)

    image_path = _get_mini_test_image_path(
        question_index,
        role=role,
        test_kind=test_kind,
    )

    # Teen personal questions are embedded into images, so do not send duplicate text.
    if test_kind == "teen_personal" or (test_kind is None and role == "teen"):
        if image_path is not None:
            await message.answer_photo(
                photo=FSInputFile(str(image_path)),
                reply_markup=keyboard,
            )
            return

        await message.answer(
            START_TEXTS["image_load_failed"],
            reply_markup=keyboard,
        )
        return

    if image_path is not None:
        await message.answer_photo(
            photo=FSInputFile(str(image_path)),
            reply_markup=keyboard,
        )
        return

    await message.answer(
        question_text,
        reply_markup=keyboard,
    )


async def _start_test_for_user(message: Message, state: FSMContext, tg_user: TgUser) -> None:
    await state.clear()
    async with AsyncSessionLocal() as session:
        db_user, _ = await get_or_create_user(session, tg_user)
        if db_user.role is None:
            await state.clear()
            await message.answer(START_TEXTS["need_role"])
            return

        if db_user.role not in {"teen", "parent"}:
            await state.clear()
            await state.set_state(RegistrationStates.waiting_for_role)
            await message.answer(
                "Личный тест доступен только для роли подростка или родителя.",
                reply_markup=mode_keyboard(role=db_user.role),
            )
            return

        new_session = await restart_test_session(
            session,
            user_id=db_user.id,
            role_snapshot=db_user.role,
            test_kind="parent_personal" if db_user.role == "parent" else "teen_personal",
        )

    kind = "parent_personal" if db_user.role == "parent" else "teen_personal"

    await state.set_state(RegistrationStates.answering_test)
    await state.update_data(
        mode=db_user.role,
        test_session_id=new_session.id,
        user_id=db_user.id,
        question_index=0,
        role_snapshot=db_user.role,
        test_kind=kind,
    )
    await message.answer(START_TEXTS["test_restart"])
    await _send_mini_test_question(
        message,
        question_index=0,
        role=db_user.role,
        test_kind=kind,
    )


async def _send_family_invite(message: Message, tg_user: TgUser) -> None:
    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, tg_user)
        if user.role not in {"parent", "teen"}:
            await message.answer("Сначала выберите роль через /start, чтобы отправить приглашение.")
            return

        family_status = await get_family_status_for_user(session, user_id=user.id)
        if family_status.has_family_link:
            actor_label = _format_user_with_family_title(user)
            active_text = "Семейная связь уже активна. Можно открыть статус семьи или перейти к тестам."
            if actor_label:
                active_text = (
                    f"{actor_label}, семейная связь уже активна. "
                    "Можно открыть статус семьи или перейти к тестам."
                )
            await message.answer(
                active_text,
                reply_markup=family_status_keyboard(role=user.role, has_family_link=True),
            )
            return

        invite = await create_family_invite(
            session,
            inviter_user_id=user.id,
            inviter_role=user.role,
        )

    me = await message.bot.get_me()
    if not me.username:
        await message.answer(START_TEXTS["invite_link_failed"])
        return

    deep_link = f"https://t.me/{me.username}?start=family_{invite.invite_token}"
    if user.role == "parent":
        text = "Ссылка для подростка готова. Отправьте её подростку - после подтверждения семейная связь будет создана. Ссылка действует 24 часа и используется один раз.\n"
    else:
        text = "Ссылка для родителя готова. Отправь её родителю, чтобы подключить его к семейной связи.\n"

    await message.answer(f"{text}{deep_link}")


def _extract_session_id_from_callback(data: str | None, prefix: str) -> int | None:
    if not data or not data.startswith(prefix):
        return None
    raw_id = data[len(prefix):]
    if not raw_id:
        return None
    try:
        return int(raw_id)
    except ValueError:
        return None


def _extract_token_from_callback(data: str | None, prefix: str) -> str | None:
    if not data or not data.startswith(prefix):
        return None
    token = data[len(prefix):].strip()
    if not token:
        return None
    return token


def _extract_family_token_from_start(message: Message) -> str | None:
    text = (message.text or "").strip()
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return None

    payload = parts[1].strip()
    prefix = "family_"
    if not payload.startswith(prefix):
        return None

    token = payload[len(prefix):].strip()
    if not token:
        return None

    return token


def _extract_pair_id_from_start(message: Message) -> int | None:
    """Return the PairSession.id from '/start pair_<id>' deep link, or None."""
    text = (message.text or "").strip()
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return None
    payload = parts[1].strip()
    if not payload.startswith("pair_"):
        return None
    raw = payload[5:].strip()
    if not raw.isdigit():
        return None
    return int(raw)


def _is_valid_family_title(role: str, family_title: str) -> bool:
    if role == "parent":
        return family_title in PARENT_FAMILY_TITLES
    if role == "teen":
        return family_title in TEEN_FAMILY_TITLES
    return False


def _format_user_with_family_title(user) -> str | None:
    family_title = _safe_html_text(getattr(user, "family_title", None))
    display_name = _safe_html_text(getattr(user, "display_name", None))

    if not family_title and not display_name:
        return None
    if family_title and display_name:
        titled = family_title.capitalize()
        return f"{titled} {display_name}"
    if family_title:
        return family_title.capitalize()
    return display_name


def _build_invite_confirm_text(invite, inviter_user) -> str:
    inviter_label = _format_user_with_family_title(inviter_user)
    if invite.status == "pending":
        if inviter_label:
            return (
                f"{inviter_label} приглашает вас подключиться к семейной связи. "
                "После подтверждения вы сможете проходить семейные сценарии и смотреть общие результаты."
            )
        return (
            "Родитель приглашает вас подключиться к семейной связи. "
            "После подтверждения вы сможете проходить семейные сценарии и смотреть общие результаты."
        )

    if inviter_label:
        return f"{inviter_label} приглашает вас подключиться к семейной связи."
    return "Подросток приглашает вас подключиться к семейной связи."


def _is_display_name_filled(value: str | None) -> bool:
    return bool((value or "").strip())


def _is_profile_complete_for_role(user, role: str) -> bool:
    if not _is_display_name_filled(getattr(user, "display_name", None)):
        return False
    family_title = (getattr(user, "family_title", None) or "").strip().lower()
    return _is_valid_family_title(role, family_title)


def _required_role_for_invite_status(invite_status: str) -> str | None:
    if invite_status == "pending":
        return "teen"
    if invite_status == "pending_parent":
        return "parent"
    return None


def _wrong_role_invite_message(required_role: str) -> str:
    if required_role == "teen":
        return "Роль родителя нельзя привязать как подростка по приглашению."
    return "Роль подростка нельзя привязать как родителя по приглашению."


async def _begin_profile_completion(
    message: Message,
    state: FSMContext,
    *,
    role: str,
    current_display_name: str | None,
) -> None:
    await state.clear()
    await state.update_data(
        pending_profile_completion=True,
        pending_expected_role=role,
    )

    if not _is_display_name_filled(current_display_name):
        await state.set_state(RegistrationStates.waiting_for_display_name)
        await message.answer("Введите имя или то, как к вам обращаться в боте.", reply_markup=ReplyKeyboardRemove())
        return

    await state.set_state(RegistrationStates.waiting_for_family_title)
    await message.answer(
        "Выберите, как обозначить вас в семье.",
        reply_markup=family_title_keyboard(role),
    )


async def _complete_family_link_payload(session, *, confirmer, token: str):
    invite = await get_testable_invite_by_token(session, token=token)
    if invite is None:
        raise ValueError("invite_invalid")

    required_role = _required_role_for_invite_status(invite.status)
    if required_role is None:
        raise ValueError("invite_invalid")

    if confirmer.role is None:
        confirmer.role = required_role
        await session.commit()

    linked = await link_family_by_token(
        session,
        token=token,
        accepter_user_id=confirmer.id,
        accepter_role=confirmer.role,
    )

    peer_telegram_id = None
    actor_role = "unknown"
    actor_label = None
    actor_has_family_link = False
    actor_family_status_text = ""
    peer_role = "unknown"
    peer_label = None
    peer_has_family_link = False
    peer_family_status_text = ""

    teen_user = await get_user_by_id(session, linked.teen_user_id) if linked.teen_user_id is not None else None
    parent_user = await get_user_by_id(session, linked.parent_user_id)

    if teen_user is not None and teen_user.id == confirmer.id:
        actor_role = "teen"
        actor_label = _format_user_with_family_title(teen_user)
        actor_status = await get_family_status_for_user(session, user_id=teen_user.id)
        actor_has_family_link = actor_status.has_family_link
        actor_family_status_text = actor_status.status_text
        if parent_user is not None:
            peer_telegram_id = parent_user.telegram_id
            peer_role = "parent"
            peer_label = _format_user_with_family_title(parent_user)
            peer_status = await get_family_status_for_user(session, user_id=parent_user.id)
            peer_has_family_link = peer_status.has_family_link
            peer_family_status_text = peer_status.status_text
    elif parent_user is not None and parent_user.id == confirmer.id:
        actor_role = "parent"
        actor_label = _format_user_with_family_title(parent_user)
        actor_status = await get_family_status_for_user(session, user_id=parent_user.id)
        actor_has_family_link = actor_status.has_family_link
        actor_family_status_text = actor_status.status_text
        if teen_user is not None:
            peer_telegram_id = teen_user.telegram_id
            peer_role = "teen"
            peer_label = _format_user_with_family_title(teen_user)
            peer_status = await get_family_status_for_user(session, user_id=teen_user.id)
            peer_has_family_link = peer_status.has_family_link
            peer_family_status_text = peer_status.status_text

    return {
        "peer_telegram_id": peer_telegram_id,
        "actor_role": actor_role,
        "actor_label": actor_label,
        "actor_has_family_link": actor_has_family_link,
        "actor_family_status_text": actor_family_status_text,
        "peer_role": peer_role,
        "peer_label": peer_label,
        "peer_has_family_link": peer_has_family_link,
        "peer_family_status_text": peer_family_status_text,
    }


async def _get_owned_session_or_notify(
    callback: CallbackQuery,
    *,
    session_id: int,
):
    if callback.from_user is None or callback.message is None:
        return None

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, callback.from_user)
        test_session = await get_test_session_by_id(session, session_id=session_id)

        if test_session is None or test_session.user_id != user.id:
            await callback.message.answer("Эта сессия недоступна. Пройдите тест заново.")
            return None

        return test_session, user


# ── Pair deep-link helper ──────────────────────────────────────────────────────

async def _handle_pair_deeplink(
    message: Message,
    state: FSMContext,
    pair_id: int,
    dispatcher: Dispatcher,
) -> None:
    """Handle /start pair_<id>: connect the parent and auto-start the pair test."""
    from app.services.pair_service import connect_parent, create_test_session_for_pair, get_pair_session
    from app.keyboards.pair_test import pair_join_confirm_keyboard, pair_phase1_score_keyboard
    from app.states.pair_test import PairTest, PairTestStates

    if message.from_user is None or message.bot is None:
        return

    tg_id = message.from_user.id

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, message.from_user)

        role = await get_user_role(session, tg_id)
        if role != "parent":
            await message.answer("Эта ссылка только для родителя.")
            return

        await message.answer("⏳ Подключаем вас...")
        await asyncio.sleep(0.5)
        await message.answer("🔍 Проверяем данные...")
        await asyncio.sleep(0.5)

        pair = await get_pair_session(session, pair_id)
        if pair is None:
            await message.answer(
                "⚠️ Приглашение устарело\n\n"
                "Попросите отправить новое"
            )
            return

        if pair.teen_id == tg_id:
            await message.answer("Вы не можете подключиться к собственной сессии.")
            return

        if pair.status == "active" and pair.parent_id == tg_id:
            await message.answer("Вы уже подключены")
            return

        try:
            pair = await connect_parent(session, pair_id, tg_id)
        except ValueError as exc:
            reason = str(exc)
            if "self_join" in reason:
                await message.answer("Вы не можете подключиться к собственной сессии.")
            elif "already_connected" in reason:
                await message.answer("К этой сессии уже подключён другой родитель.")
            elif "pair_not_found" in reason:
                await message.answer(
                    "⚠️ Приглашение устарело\n\n"
                    "Попросите отправить новое"
                )
            else:
                await message.answer("Не удалось подключиться. Попробуйте позже.")
            return

        try:
            pts = await create_test_session_for_pair(
                session,
                teen_telegram_id=pair.teen_id,
                parent_telegram_id=pair.parent_id,
            )
        except ValueError:
            await message.answer(
                "Не удалось создать сессию. Убедитесь, что оба участника зарегистрированы в боте."
            )
            return

        parent_user_id = user.id

        # Look up teen's internal user record for FSM data
        from sqlalchemy import select as _select
        from app.db.models import User as _User
        teen_row = await session.execute(
            _select(_User).where(_User.telegram_id == pair.teen_id)
        )
        teen_user = teen_row.scalar_one_or_none()
        teen_user_id = teen_user.id if teen_user else None

    # ── Set FSM state for parent (current context) ─────────────────────────
    await state.clear()
    await state.set_state(PairTestStates.waiting_phase1_score)
    await state.update_data(
        pair_session_id=pts.id,
        pair_task_id=pts.id,
        user_id=parent_user_id,
        role="parent",
        phase=1,
        question_index=0,
        phase_completed=False,
        waiting_for_other=False,
        mode="pair_test",
        fsm_phase_state=PairTest.phase_1.state,
        phase_1_sent=False,
        phase_2_sent=False,
        phase_3_selection_sent=False,
        phase_3_sent=False,
        phase_4_sent=False,
    )
    await message.answer("✅ Подключение...")
    await asyncio.sleep(0.5)
    await message.answer("✅ Готово!")
    await message.answer("👇 Начинаем", reply_markup=pair_join_confirm_keyboard())
    phase1_prompt = (
        TEXTS["phase_1"]
        + "\n"
        + "Когда я думаю о теме выбора профессии и будущего, я чувствую...\n"
        + "Выберите оценку от 1 до 10:"
    )
    await message.answer(phase1_prompt, reply_markup=pair_phase1_score_keyboard())

    # ── Set FSM state for teen and notify them ─────────────────────────────
    teen_state = dispatcher.fsm.get_context(
        bot=message.bot,
        chat_id=pair.teen_id,
        user_id=pair.teen_id,
    )
    await teen_state.clear()
    await teen_state.set_state(PairTestStates.waiting_phase1_score)
    await teen_state.update_data(
        pair_session_id=pts.id,
        pair_task_id=pts.id,
        user_id=teen_user_id,
        role="teen",
        phase=1,
        question_index=0,
        phase_completed=False,
        waiting_for_other=False,
        mode="pair_test",
        fsm_phase_state=PairTest.phase_1.state,
        phase_1_sent=False,
        phase_2_sent=False,
        phase_3_selection_sent=False,
        phase_3_sent=False,
        phase_4_sent=False,
    )
    try:
        await message.bot.send_message(
            pair.teen_id,
            "✅ Родитель подключился. Начинаем",
            reply_markup=pair_join_confirm_keyboard(),
        )
        await message.bot.send_message(
            pair.teen_id,
            phase1_prompt,
            reply_markup=pair_phase1_score_keyboard(),
        )
    except Exception:
        log.warning("Failed to notify teen about parent connection", exc_info=True)


async def _handle_joinpair_deeplink(
    message: Message,
    state: FSMContext,
    pair_test_session_id: int,
) -> None:
    """Handle /start joinpair_<id>: teen joins a parent-initiated PairTestSession."""
    from app.db.models import User as _User
    from app.keyboards.pair_test import pair_join_confirm_keyboard, pair_phase1_score_keyboard
    from app.services.pair_test_service import get_pair_session_by_id, join_pair_session
    from app.states.pair_test import PairTest, PairTestStates
    from sqlalchemy import select as _select

    if message.from_user is None or message.bot is None:
        return

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, message.from_user)

        if user.role != "teen":
            await message.answer("Эта ссылка только для подростка.")
            return

        pair_session = await get_pair_session_by_id(session, pair_session_id=pair_test_session_id)
        if pair_session is None:
            await message.answer("Приглашение устарело или уже использовано. Попросите родителя создать новое.")
            return
        if pair_session.parent_user_id == user.id:
            await message.answer("Вы не можете подключиться к собственной сессии.")
            return

        try:
            pair_session = await join_pair_session(
                session,
                pair_code=pair_session.pair_code,
                teen_user_id=user.id,
            )
        except Exception as exc:
            reason = str(exc)
            if "not_found" in reason or "not_joinable" in reason:
                await message.answer("Приглашение устарело или уже использовано. Попросите родителя создать новое.")
            elif "already_joined" in reason:
                await message.answer("К сессии уже подключен другой подросток.")
            elif "self_join" in reason:
                await message.answer("Вы не можете подключиться к собственной сессии.")
            else:
                await message.answer("Не удалось подключиться. Попробуйте ещё раз.")
            return

        parent_user_id = pair_session.parent_user_id
        parent_row = await session.execute(
            _select(_User).where(_User.id == parent_user_id)
        )
        parent = parent_row.scalar_one_or_none()

    await state.clear()
    await state.set_state(PairTestStates.waiting_phase1_score)
    await state.update_data(
        pair_session_id=pair_session.id,
        pair_task_id=pair_session.id,
        user_id=user.id,
        role="teen",
        phase=1,
        question_index=0,
        phase_completed=False,
        waiting_for_other=False,
        mode="pair_test",
        fsm_phase_state=PairTest.phase_1.state,
        phase_1_sent=False,
        phase_2_sent=False,
        phase_3_selection_sent=False,
        phase_3_sent=False,
        phase_4_sent=False,
    )

    phase1_prompt = (
        TEXTS["phase_1"]
        + "\n"
        + "Когда я думаю о теме выбора профессии и будущего, я чувствую...\n"
        + "Выберите оценку от 1 до 10:"
    )

    await message.answer("✅ Подключение успешно!", reply_markup=pair_join_confirm_keyboard())
    await message.answer(phase1_prompt, reply_markup=pair_phase1_score_keyboard())

    if parent is not None:
        try:
            await message.bot.send_message(
                parent.telegram_id,
                "✅ Подросток подключился. Начинаем!",
                reply_markup=pair_join_confirm_keyboard(),
            )
            await message.bot.send_message(
                parent.telegram_id,
                phase1_prompt,
                reply_markup=pair_phase1_score_keyboard(),
            )
        except Exception:
            log.warning("Failed to notify parent about teen joining", exc_info=True)


@router.message(CommandStart(deep_link=True))
async def cmd_start_deeplink(
    message: Message,
    state: FSMContext,
    dispatcher: Dispatcher,
    command: CommandObject,
) -> None:
    if message.from_user is None:
        return

    print("USER:", message.from_user.id)
    print("PAYLOAD:", command.args)

    payload = (command.args or "").strip()
    print("DEBUG PAYLOAD:", payload)

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, message.from_user)
        await track_user_event(session, user_id=user.id, event="visit")
        await session.commit()

    if not payload:
        await message.answer(
            "Если вы перешли по ссылке, нажмите:\n"
            "/start pair_123"
        )
        return

    if not payload.startswith("pair_"):
        try:
            decoded = decode_payload(payload)
        except Exception:
            decoded = payload
        if decoded:
            payload = decoded
            print("DEBUG PAYLOAD:", payload)

    if payload.startswith("pair_"):
        try:
            pair_id = int(payload.split("_", 1)[1])
        except Exception:
            await message.answer("Некорректная ссылка приглашения.")
            return

        await _handle_pair_deeplink(message, state, pair_id, dispatcher)
        return

    if payload.startswith("joinpair_"):
        try:
            pair_test_session_id = int(payload.split("_", 1)[1])
        except Exception:
            await message.answer("Некорректная ссылка.")
            return

        await _handle_joinpair_deeplink(message, state, pair_test_session_id)
        return

    if payload.startswith("family_"):
        token = payload[len("family_"):]
        if not token:
            await message.answer(START_TEXTS["invite_invalid"])
            return

        async with AsyncSessionLocal() as session:
            user, _ = await get_or_create_user(session, message.from_user)
            invite = await get_testable_invite_by_token(session, token=token)

            if invite is None:
                await state.clear()
                await message.answer(START_TEXTS["invite_invalid"])
                return

            inviter_id = invite.parent_user_id if invite.status == "pending" else invite.teen_user_id
            if inviter_id == user.id:
                await state.clear()
                await message.answer(START_TEXTS["invite_invalid"])
                return

            if invite.status == "pending":
                if user.role == "parent":
                    await state.clear()
                    await message.answer("Роль родителя нельзя привязать как подростка по приглашению.")
                    return

                linked = await get_linked_family_for_teen(session, teen_user_id=user.id)
                if linked is not None:
                    await state.clear()
                    await message.answer(START_TEXTS["family_active"])
                    return
            else:
                if user.role == "teen":
                    await state.clear()
                    await message.answer("Роль подростка нельзя привязать как родителя по приглашению.")
                    return

                linked = await get_family_for_user(session, user_id=user.id)
                if linked is not None:
                    await state.clear()
                    await message.answer(START_TEXTS["family_active"])
                    return

            required_role_for_confirm = "teen" if invite.status == "pending" else "parent"
            if user.role is None:
                user.role = required_role_for_confirm
                await session.commit()

            try:
                payload = await _complete_family_link_payload(session, confirmer=user, token=token)
            except ValueError:
                await state.clear()
                await message.answer(START_TEXTS["invite_invalid"])
                return

            await state.clear()
            role_label = ROLE_LABELS.get(payload["actor_role"], payload["actor_role"])
            await message.answer(
                f"✅ Семейная связь создана!\nВаша роль: <b>{role_label}</b>.\n\n"
                f"{payload['actor_family_status_text']}",
                reply_markup=family_status_keyboard(
                    role=payload["actor_role"],
                    has_family_link=payload["actor_has_family_link"],
                ),
            )
            if payload["peer_telegram_id"] is not None:
                try:
                    await message.bot.send_message(
                        payload["peer_telegram_id"],
                        f"✅ Семейная связь создана!\n{payload['peer_family_status_text']}",
                        reply_markup=family_status_keyboard(
                            role=payload["peer_role"],
                            has_family_link=payload["peer_has_family_link"],
                        ),
                    )
                except Exception:
                    log.warning("Failed to notify peer about family link", exc_info=True)
            return

    await message.answer("Некорректная ссылка приглашения.")


# ── /start ─────────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, dispatcher: Dispatcher) -> None:
    if message.from_user is None:
        return

    family_token = _extract_family_token_from_start(message)

    async with AsyncSessionLocal() as session:
        user, created = await get_or_create_user(session, message.from_user)
        await track_user_event(session, user_id=user.id, event="visit")
        await session.commit()

        # Zero-friction auto-resume: no extra text, jump directly back to active pair flow.
        if user.role in {"teen", "parent"} and family_token is None:
            from app.services.pair_test_service import get_active_pair_session_for_user
            from app.handlers.pair_test import msg_resume_pair_test

            active_pair = await get_active_pair_session_for_user(
                session,
                user_id=user.id,
                role=user.role,
            )
            if active_pair is not None:
                await msg_resume_pair_test(message, state, dispatcher)
                return

        if family_token is not None:
            invite = await get_testable_invite_by_token(session, token=family_token)
            if invite is None:
                await state.clear()
                await message.answer(START_TEXTS["invite_invalid"])
                return

            inviter_id = invite.parent_user_id if invite.status == "pending" else invite.teen_user_id
            if inviter_id == user.id:
                await state.clear()
                await message.answer(START_TEXTS["invite_invalid"])
                return

            if invite.status == "pending":
                if user.role == "parent":
                    await state.clear()
                    await message.answer("Роль родителя нельзя привязать как подростка по приглашению.")
                    return

                linked = await get_linked_family_for_teen(session, teen_user_id=user.id)
                if linked is not None:
                    await state.clear()
                    await message.answer(START_TEXTS["family_active"])
                    return
            else:
                if user.role == "teen":
                    await state.clear()
                    await message.answer("Роль подростка нельзя привязать как родителя по приглашению.")
                    return

                linked = await get_family_for_user(session, user_id=user.id)
                if linked is not None:
                    await state.clear()
                    await message.answer(START_TEXTS["family_active"])
                    return

            required_role_for_confirm = "teen" if invite.status == "pending" else "parent"
            if user.role is None:
                user.role = required_role_for_confirm
                await session.commit()

            try:
                payload = await _complete_family_link_payload(session, confirmer=user, token=family_token)
            except ValueError:
                await state.clear()
                await message.answer(START_TEXTS["invite_invalid"])
                return

            await state.clear()
            role_label = ROLE_LABELS.get(payload["actor_role"], payload["actor_role"])
            await message.answer(
                f"✅ Семейная связь создана!\nВаша роль: <b>{role_label}</b>.\n\n"
                f"{payload['actor_family_status_text']}",
                reply_markup=family_status_keyboard(
                    role=payload["actor_role"],
                    has_family_link=payload["actor_has_family_link"],
                ),
            )
            if payload["peer_telegram_id"] is not None:
                try:
                    await message.bot.send_message(
                        payload["peer_telegram_id"],
                        f"✅ Семейная связь создана!\n{payload['peer_family_status_text']}",
                        reply_markup=family_status_keyboard(
                            role=payload["peer_role"],
                            has_family_link=payload["peer_has_family_link"],
                        ),
                    )
                except Exception:
                    log.warning("Failed to notify peer about family link", exc_info=True)
            return

        if user.role is not None:
            if user.role in VALID_ROLES:
                linked_family = await get_family_for_user(session, user_id=user.id)
                if linked_family is not None and not _is_profile_complete_for_role(user, user.role):
                    await _begin_profile_completion(
                        message,
                        state,
                        role=user.role,
                        current_display_name=user.display_name,
                    )
                    return

            active_session = await get_active_test_session(session, user_id=user.id)
            if active_session is not None:
                answer_count = await count_answers_for_session(
                    session,
                    session_id=active_session.id,
                )

                tk = active_session.test_kind or ("parent_personal" if active_session.role_snapshot == "parent" else "teen_personal")
                active_questions = get_questions_for_test_kind(tk)
                if answer_count >= len(active_questions):
                    await complete_test_session(session, session_id=active_session.id)
                    await state.clear()
                    await message.answer(
                        "Предыдущий тест был завершен автоматически из-за неконсистентного состояния. "
                        "Используйте /restart, чтобы начать заново."
                    )
                    return

                await state.set_state(RegistrationStates.answering_test)
                active_test_kind = active_session.test_kind or ("parent_personal" if active_session.role_snapshot == "parent" else "teen_personal")
                await state.update_data(
                    test_session_id=active_session.id,
                    user_id=user.id,
                    question_index=answer_count,
                    role_snapshot=active_session.role_snapshot,
                    test_kind=active_test_kind,
                )
                family_status = await get_family_status_for_user(session, user_id=user.id)
                await message.answer(
                    "Меню доступно ниже.",
                    reply_markup=family_status_keyboard(
                        role=user.role,
                        has_family_link=family_status.has_family_link,
                    ),
                )
                await message.answer("У вас есть незавершенный тест. Продолжаем.")
                await _send_mini_test_question(
                    message,
                    question_index=answer_count,
                    role=active_session.role_snapshot,
                    test_kind=active_test_kind,
                )
                return

            # Already registered — greet, show current role, offer mode selection.
            await state.clear()
            role_label = ROLE_LABELS.get(user.role, user.role)
            family_status = await get_family_status_for_user(session, user_id=user.id)
            await message.answer(
                f"С возвращением, {_safe_html_text(user.full_name) or 'друг'}! 👋\n"
                f"Ваша роль: <b>{role_label}</b>.\n"
                f"{family_status.status_text}",
                reply_markup=family_status_keyboard(
                    role=user.role,
                    has_family_link=family_status.has_family_link,
                ),
            )
            await state.set_state(RegistrationStates.waiting_for_role)
            await message.answer(
                "👇 Начинаем",
                reply_markup=mode_keyboard(role=user.role),
            )
            return

    # No role yet — ask to pick one.
    await state.set_state(RegistrationStates.waiting_for_role)
    greeting = "Добро пожаловать" if created else "Привет снова"
    await message.answer(
        f"{greeting}, {_safe_html_text(user.full_name) or 'друг'}! 👋\n{START_TEXTS['choose_role']}",
        reply_markup=role_keyboard(),
    )


@router.message(F.text, StateFilter(None))
async def auto_resume_any_message(message: Message, state: FSMContext, dispatcher: Dispatcher) -> None:
    """Silent auto-resume for stray user messages outside active FSM screens."""
    if message.from_user is None:
        return

    text = (message.text or "").strip()
    if not text or text.startswith("/"):
        return

    current_state = await state.get_state()
    if current_state is not None:
        # Let dedicated state handlers process input.
        return

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, message.from_user)
        await track_user_event(session, user_id=user.id, event="visit")
        await session.commit()
        if user.role not in {"teen", "parent"}:
            return

        from app.services.pair_test_service import get_active_pair_session_for_user

        active_pair = await get_active_pair_session_for_user(
            session,
            user_id=user.id,
            role=user.role,
        )
        if active_pair is None:
            return

    from app.handlers.pair_test import msg_resume_pair_test

    await msg_resume_pair_test(message, state, dispatcher)


# ── Role selection callback ────────────────────────────────────────────────────

@router.callback_query(
    RegistrationStates.waiting_for_role,
    F.data.startswith(ROLE_CALLBACK_PREFIX),
)
async def cb_select_role(callback: CallbackQuery, state: FSMContext) -> None:
    print(f"🔴 DEBUG: cb_select_role CALLED with data={callback.data}")
    log.info("🔴 DEBUG: cb_select_role CALLED with data=%s", callback.data)
    if callback.from_user is None or callback.message is None:
        log.error("🔴 DEBUG: callback.from_user or callback.message is None")
        return

    role = callback.data.removeprefix(ROLE_CALLBACK_PREFIX)  # type: ignore[union-attr]
    log.info("[LIVE_CHECK] role_callback data=%s parsed_role=%s user_id=%s", callback.data, role, callback.from_user.id)
    log.info("🔴 DEBUG: role parsed as '%s'", role)

    if role not in VALID_ROLES:
        log.warning("Unknown role received: %s", role)
        await callback.answer("Неизвестная роль. Попробуйте ещё раз.")
        return

    log.info("🔴 DEBUG: role '%s' is valid, saving to DB...", role)
    async with AsyncSessionLocal() as session:
        user = await set_user_role(session, callback.from_user.id, role)
    log.info("🔴 DEBUG: user role saved, user_id=%s role=%s", user.id, user.role)
    role_label = ROLE_LABELS.get(user.role or "", user.role or "")
    log.info("🔴 DEBUG: role_label='%s'", role_label)

    await state.set_state(RegistrationStates.waiting_for_family_title)
    log.info("🔴 DEBUG: FSM state set to waiting_for_family_title")
    await state.update_data(selected_role=role, user_id=user.id)
    log.info("🔴 DEBUG: FSM data updated")
    
    try:
        await callback.message.edit_text(
            f"✅ Роль <b>{role_label}</b> сохранена!\n\nВыберите, как обозначить вас в семье.",
        )
        log.info("🔴 DEBUG: edit_text sent")
    except Exception as e:
        log.error("🔴 DEBUG: edit_text failed: %s", e)
    
    try:
        await callback.message.answer(
            "Выберите, как обозначить вас в семье.",
            reply_markup=family_title_keyboard(role),
        )
        log.info("🔴 DEBUG: answer sent")
    except Exception as e:
        log.error("🔴 DEBUG: answer failed: %s", e)

    await callback.answer()
    log.info("🔴 DEBUG: cb_select_role COMPLETED")


@router.message(RegistrationStates.waiting_for_family_title)
async def msg_select_family_title(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    selected_title = (message.text or "").strip().lower()
    data = await state.get_data()
    if data.get("pending_invite_onboarding"):
        expected_role = data.get("pending_expected_role")
        pending_token = data.get("pending_family_token")
        pending_display_name = data.get("pending_display_name")

        if not isinstance(expected_role, str) or expected_role not in VALID_ROLES or not isinstance(pending_token, str):
            await state.clear()
            await state.set_state(RegistrationStates.waiting_for_role)
            await message.answer(START_TEXTS["choose_role"], reply_markup=role_keyboard())
            return

        if not _is_valid_family_title(expected_role, selected_title):
            await message.answer(
                "Выберите обозначение кнопкой ниже.",
                reply_markup=family_title_keyboard(expected_role),
            )
            return

        async with AsyncSessionLocal() as session:
            confirmer, _ = await get_or_create_user(session, message.from_user)

            if confirmer.role is not None and confirmer.role != expected_role:
                await state.clear()
                await message.answer(_wrong_role_invite_message(expected_role))
                return

            update_display_name: str | None = None
            if not _is_display_name_filled(confirmer.display_name):
                if not isinstance(pending_display_name, str) or not pending_display_name.strip():
                    await state.set_state(RegistrationStates.waiting_for_display_name)
                    await message.answer(START_TEXTS["name_prompt"], reply_markup=ReplyKeyboardRemove())
                    return
                update_display_name = pending_display_name.strip()

            await update_user_profile_meta(
                session,
                user_id=confirmer.id,
                display_name=update_display_name,
                family_title=selected_title,
            )

            try:
                payload = await _complete_family_link_payload(session, confirmer=confirmer, token=pending_token)
            except ValueError:
                await state.clear()
                await message.answer(START_TEXTS["invite_invalid"])
                return

        await state.clear()

        actor_success_text = "Семейная связь успешно создана."
        if payload["actor_label"]:
            actor_success_text = f"Семейная связь успешно создана, {payload['actor_label']}."

        await message.answer(
            f"{actor_success_text}\n{payload['actor_family_status_text']}",
            reply_markup=family_status_keyboard(
                role=payload["actor_role"],
                has_family_link=payload["actor_has_family_link"],
            ),
        )

        if payload["peer_telegram_id"] is not None:
            peer_success_text = "Семейная связь успешно создана."
            if payload["peer_label"]:
                peer_success_text = f"Семейная связь успешно создана, {payload['peer_label']}."
            try:
                await message.bot.send_message(
                    payload["peer_telegram_id"],
                    f"{peer_success_text}\n{payload['peer_family_status_text']}",
                    reply_markup=family_status_keyboard(
                        role=payload["peer_role"],
                        has_family_link=payload["peer_has_family_link"],
                    ),
                )
            except Exception:
                log.warning("Failed to notify user about family link", exc_info=True)
        return

    if data.get("pending_profile_completion"):
        expected_role = data.get("pending_expected_role")
        pending_display_name = data.get("pending_display_name")

        if not isinstance(expected_role, str) or expected_role not in VALID_ROLES:
            await state.clear()
            await state.set_state(RegistrationStates.waiting_for_role)
            await message.answer(START_TEXTS["choose_role"], reply_markup=role_keyboard())
            return

        if not _is_valid_family_title(expected_role, selected_title):
            await message.answer(
                "Выберите обозначение кнопкой ниже.",
                reply_markup=family_title_keyboard(expected_role),
            )
            return

        async with AsyncSessionLocal() as session:
            user, _ = await get_or_create_user(session, message.from_user)
            if user.role != expected_role:
                await state.clear()
                await message.answer(START_TEXTS["choose_role"], reply_markup=role_keyboard())
                return

            update_display_name: str | None = None
            if not _is_display_name_filled(user.display_name):
                if not isinstance(pending_display_name, str) or not pending_display_name.strip():
                    await state.set_state(RegistrationStates.waiting_for_display_name)
                    await message.answer(START_TEXTS["name_prompt"], reply_markup=ReplyKeyboardRemove())
                    return
                update_display_name = pending_display_name.strip()

            await update_user_profile_meta(
                session,
                user_id=user.id,
                display_name=update_display_name,
                family_title=selected_title,
            )
            family_status = await get_family_status_for_user(session, user_id=user.id)

        await state.clear()
        await message.answer(
            START_TEXTS["profile_saved"],
            reply_markup=family_status_keyboard(
                role=expected_role,
                has_family_link=family_status.has_family_link,
            ),
        )
        return

    selected_role = data.get("selected_role")

    if not isinstance(selected_role, str) or selected_role not in VALID_ROLES:
        await state.clear()
        await state.set_state(RegistrationStates.waiting_for_role)
        await message.answer(START_TEXTS["choose_role"], reply_markup=role_keyboard())
        return

    if not _is_valid_family_title(selected_role, selected_title):
        await message.answer(
            "Выберите обозначение кнопкой ниже.",
            reply_markup=family_title_keyboard(selected_role),
        )
        return

    await state.update_data(family_title=selected_title)
    await state.set_state(RegistrationStates.waiting_for_display_name)
    await message.answer("Как к вам обращаться в боте?", reply_markup=ReplyKeyboardRemove())
    await message.answer(START_TEXTS["name_prompt"])


@router.message(RegistrationStates.waiting_for_display_name)
async def msg_set_display_name(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    display_name = (message.text or "").strip()
    if not display_name:
        await message.answer("Имя не должно быть пустым. Введите, пожалуйста, ещё раз.")
        return
    if len(display_name) > 40:
        await message.answer("Имя слишком длинное. Введите вариант до 40 символов.")
        return

    data = await state.get_data()
    if data.get("pending_invite_onboarding"):
        expected_role = data.get("pending_expected_role")
        pending_token = data.get("pending_family_token")
        if not isinstance(expected_role, str) or expected_role not in VALID_ROLES or not isinstance(pending_token, str):
            await state.clear()
            await state.set_state(RegistrationStates.waiting_for_role)
            await message.answer(START_TEXTS["choose_role"], reply_markup=role_keyboard())
            return

        await state.update_data(pending_display_name=display_name)
        await state.set_state(RegistrationStates.waiting_for_family_title)
        await message.answer(
            "Выберите, как обозначить вас в семье.",
            reply_markup=family_title_keyboard(expected_role),
        )
        return

    if data.get("pending_profile_completion"):
        expected_role = data.get("pending_expected_role")
        if not isinstance(expected_role, str) or expected_role not in VALID_ROLES:
            await state.clear()
            await state.set_state(RegistrationStates.waiting_for_role)
            await message.answer(START_TEXTS["choose_role"], reply_markup=role_keyboard())
            return

        await state.update_data(pending_display_name=display_name)
        await state.set_state(RegistrationStates.waiting_for_family_title)
        await message.answer(
            "Выберите, как обозначить вас в семье.",
            reply_markup=family_title_keyboard(expected_role),
        )
        return

    selected_role = data.get("selected_role")
    selected_title = data.get("family_title")
    user_id = data.get("user_id")

    if not isinstance(selected_role, str) or selected_role not in VALID_ROLES:
        await state.clear()
        await state.set_state(RegistrationStates.waiting_for_role)
        await message.answer(START_TEXTS["choose_role"], reply_markup=role_keyboard())
        return
    if not isinstance(selected_title, str) or not _is_valid_family_title(selected_role, selected_title):
        await state.set_state(RegistrationStates.waiting_for_family_title)
        await message.answer(
            "Снова выберите семейное обозначение.",
            reply_markup=family_title_keyboard(selected_role),
        )
        return
    if not isinstance(user_id, int):
        await state.clear()
        await state.set_state(RegistrationStates.waiting_for_role)
        await message.answer(START_TEXTS["choose_role"], reply_markup=role_keyboard())
        return

    async with AsyncSessionLocal() as session:
        await update_user_profile_meta(
            session,
            user_id=user_id,
            display_name=display_name,
            family_title=selected_title,
        )

        user = await get_user_by_id(session, user_id=user_id)
        if user is None:
            await state.clear()
            await state.set_state(RegistrationStates.waiting_for_role)
            await message.answer(START_TEXTS["choose_role"], reply_markup=role_keyboard())
            return
        family_status = await get_family_status_for_user(session, user_id=user.id)

    await state.clear()
    await state.set_state(RegistrationStates.waiting_for_role)
    await message.answer(START_TEXTS["profile_saved"])
    await message.answer(
        START_TEXTS["menu_below"],
        reply_markup=family_status_keyboard(
            role=user.role,
            has_family_link=family_status.has_family_link,
        ),
    )
    await message.answer(
        START_TEXTS["choose_mode"],
        reply_markup=mode_keyboard(role=user.role),
    )
    return


@router.message(RegistrationStates.waiting_for_role)
async def msg_waiting_for_role_fallback(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, message.from_user)

    if user.role in VALID_ROLES:
        await message.answer(
            "Пожалуйста, выберите вариант кнопкой ниже.",
            reply_markup=mode_keyboard(role=user.role),
        )
        return

    await state.set_state(RegistrationStates.waiting_for_role)
    await message.answer(
        "Пожалуйста, выберите роль кнопкой ниже.",
        reply_markup=role_keyboard(),
    )


@router.callback_query(RegistrationStates.waiting_for_display_name)
async def cb_waiting_for_display_name_fallback(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    await callback.answer(START_TEXTS["value_text_only"], show_alert=True)
    await callback.message.answer(START_TEXTS["name_prompt"])


@router.callback_query(RegistrationStates.waiting_for_family_title)
async def cb_waiting_for_family_title_fallback(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None:
        return
    await callback.answer("Пожалуйста, используйте кнопки ниже.", show_alert=True)

    data = await state.get_data()
    role = data.get("pending_expected_role") or data.get("selected_role")

    if not isinstance(role, str) or role not in VALID_ROLES:
        async with AsyncSessionLocal() as session:
            user, _ = await get_or_create_user(session, callback.from_user)
            role = user.role if user.role in VALID_ROLES else None

    if isinstance(role, str) and role in VALID_ROLES:
        await callback.message.answer(
            "Выберите, как обозначить вас в семье, кнопкой ниже.",
            reply_markup=family_title_keyboard(role),
        )
    else:
        await state.set_state(RegistrationStates.waiting_for_role)
        await callback.message.answer(
            "Пожалуйста, выберите роль кнопкой ниже.",
            reply_markup=role_keyboard(),
        )


# ── Mode selection callbacks ───────────────────────────────────────────────────

@router.callback_query(RegistrationStates.waiting_for_role, F.data == MODE_PERSONAL)
async def cb_mode_personal(callback: CallbackQuery, state: FSMContext) -> None:
    print(f"🔴 DEBUG: cb_mode_personal CALLED with data={callback.data}")
    log.info("🔴 DEBUG: cb_mode_personal CALLED with data=%s", callback.data)
    """User picked 'Personal test' from mode screen — start personal mini-test."""
    if callback.from_user is None or callback.message is None:
        return
    log.info("[LIVE_CHECK] mode_callback mode=personal user_id=%s", callback.from_user.id)
    await callback.answer()
    await state.clear()

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, callback.from_user)
        if user.role in {"teen", "parent"}:
            kind = "parent_personal" if user.role == "parent" else "teen_personal"
            test_session = await restart_test_session(
                session,
                user_id=user.id,
                role_snapshot=user.role,
                test_kind=kind,
            )
        else:
            test_session = None

    if user.role in {"teen", "parent"} and test_session is not None:
        kind = "parent_personal" if user.role == "parent" else "teen_personal"
        await state.set_state(RegistrationStates.answering_test)
        await state.update_data(
            mode=user.role,
            test_session_id=test_session.id,
            user_id=user.id,
            question_index=0,
            role_snapshot=user.role,
            test_kind=kind,
        )
        await callback.message.edit_text(START_TEXTS["start_personal"])
        await _send_mini_test_question(
            callback.message,
            question_index=0,
            role=user.role,
            test_kind=kind,
        )
    else:
        await callback.message.edit_text(
            "Личный тест доступен только для роли подростка или родителя.",
            reply_markup=mode_keyboard(role=user.role),
        )


@router.callback_query(
    RegistrationStates.answering_test,
    F.data.startswith(MINI_TEST_CALLBACK_PREFIX),
)
async def cb_mini_test_answer(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message is None:
        return

    answer_code = callback.data.removeprefix(MINI_TEST_CALLBACK_PREFIX) if callback.data else ""

    await callback.answer()

    data = await state.get_data()
    if data.get("mode") == "pair":
        await callback.answer("Сейчас активен совместный тест. Нажмите /restart для смены режима.", show_alert=True)
        return

    test_session_id = data.get("test_session_id")
    user_id = data.get("user_id")
    question_index = data.get("question_index", 0)
    role_snapshot = data.get("role_snapshot")
    test_kind = data.get("test_kind")

    if not isinstance(test_session_id, int) or not isinstance(user_id, int) or not isinstance(question_index, int):
        await state.clear()
        await callback.message.answer(START_TEXTS["session_not_found"])
        return

    completed_session = None
    answers = None

    async with AsyncSessionLocal() as session:
        active_session = await get_active_test_session(session, user_id=user_id)
        if active_session is None or active_session.id != test_session_id:
            await state.clear()
            await callback.message.answer(START_TEXTS["active_session_not_found"])
            return

        role_for_questions = role_snapshot if isinstance(role_snapshot, str) else active_session.role_snapshot
        # Prefer test_kind from FSM state; fall back to deriving from role
        tk = test_kind or active_session.test_kind or ("parent_personal" if role_for_questions == "parent" else "teen_personal")
        questions = get_questions_for_test_kind(tk)

        if question_index < 0 or question_index >= len(questions):
            await cancel_test_session_inplace(session, session_id=test_session_id)
            await session.commit()
            await state.clear()
            await callback.message.answer(START_TEXTS["test_state_broken"])
            return

        question = questions[question_index]
        options = question.get("options", [])
        valid_codes = {code for code, _ in options}

        if answer_code not in valid_codes:
            await callback.answer("Выберите один из вариантов кнопками.")
            return

        await save_answer_inplace(
            session,
            session_id=test_session_id,
            user_id=user_id,
            question_code=question["code"],
            answer_value=answer_code,
        )

        next_index = question_index + 1
        if next_index < len(questions):
            await session.commit()
            await state.update_data(question_index=next_index)
            await callback.message.edit_reply_markup(reply_markup=None)
            await _send_mini_test_question(
                callback.message,
                question_index=next_index,
                role=role_for_questions,
                test_kind=tk,
            )
            return

        completed_session = await complete_test_session_inplace(session, session_id=test_session_id)
        await session.commit()
        answers = await get_answers_for_session(session, session_id=test_session_id)

        teen_answers = None
        if completed_session.role_snapshot == "parent":
            family_link = await get_family_for_user(session, user_id=user_id)
            teen_user_id = family_link.teen_user_id if family_link is not None else None
            if teen_user_id is not None:
                teen_session = await get_last_completed_session(session, user_id=teen_user_id)
                if teen_session is not None:
                    teen_answers = await get_answers_for_session(session, session_id=teen_session.id)

    if completed_session is None or answers is None:
        await state.clear()
        await callback.message.answer(START_TEXTS["session_not_found"])
        return

    report_stub = build_report_stub(
        answers,
        completed_session.role_snapshot,
        teen_answers=teen_answers,
    )
    final_report = report_stub

    ai_report = await generate_ai_report(
        completed_session.role_snapshot,
        answers,
        comparison_context=report_stub.get("ai_context"),
    )
    if ai_report is not None:
        ai_report["has_answers"] = True
        final_report = ai_report

    summary_text = render_report_text(final_report)

    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        summary_text,
        reply_markup=post_summary_keyboard(session_id=completed_session.id),
    )


@router.callback_query(RegistrationStates.waiting_for_role, F.data == MODE_PAIR)
async def cb_mode_pair(callback: CallbackQuery, state: FSMContext) -> None:
    print(f"🔴 DEBUG: cb_mode_pair CALLED with data={callback.data}")
    log.info("🔴 DEBUG: cb_mode_pair CALLED with data=%s", callback.data)
    """User picked 'Pair test' from mode screen."""
    if callback.message is None:
        return
    if callback.from_user is not None:
        log.info("[LIVE_CHECK] mode_callback mode=pair user_id=%s", callback.from_user.id)
    await callback.answer()
    await state.clear()
    await state.update_data(mode="pair")
    from app.handlers.pair_test import show_pair_entry
    await show_pair_entry(callback.message, state)


@router.callback_query(F.data == FAMILY_INVITE_CALLBACK)
async def cb_family_invite(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    await callback.answer()
    await _send_family_invite(callback.message, callback.from_user)


@router.message(F.text == FAMILY_INVITE_PARENT_TEXT)
async def msg_family_invite(message: Message) -> None:
    if message.from_user is None:
        return
    await _send_family_invite(message, message.from_user)


@router.message(F.text == FAMILY_INVITE_TEEN_TEXT)
async def msg_family_invite_for_teen(message: Message) -> None:
    if message.from_user is None:
        return
    await _send_family_invite(message, message.from_user)


@router.message(F.text == FAMILY_STATUS_TEXT)
async def msg_family_status(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, message.from_user)
        if user.role is None:
            await message.answer(START_TEXTS["need_role"])
            return

        linked_family = await get_family_for_user(session, user_id=user.id)
        if user.role in VALID_ROLES and linked_family is not None and not _is_profile_complete_for_role(user, user.role):
            await _begin_profile_completion(
                message,
                state,
                role=user.role,
                current_display_name=user.display_name,
            )
            return

        family_status = await get_family_status_for_user(session, user_id=user.id)

    await message.answer(
        family_status.status_text,
        reply_markup=family_status_keyboard(
            role=family_status.role,
            has_family_link=family_status.has_family_link,
        ),
    )


@router.message(F.text == MAIN_MENU_TEST_TEXT)
async def msg_main_menu_start_test(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    await _start_test_for_user(message, state, message.from_user)


@router.message(F.text == MAIN_MENU_RESULT_TEXT)
async def msg_show_last_result(message: Message) -> None:
    if message.from_user is None:
        return

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, message.from_user)
        result = await get_last_result(session, user.id)
        previous_result = await get_previous_result(session, user.id)

    if result is None:
        await message.answer(
            "У тебя пока нет результатов.\n\nПройди тест, чтобы получить анализ 👇"
        )
        return

    delta = compare_results(
        current=result.diff,
        previous=previous_result.diff if previous_result is not None else None,
    )
    progress_text = build_progress_text(delta)

    await message.answer(
        build_result_text(result) + "\n\n" + progress_text,
        reply_markup=result_keyboard(),
    )


@router.message(F.text == PROGRESS_MENU_TEXT)
async def msg_show_progress(message: Message) -> None:
    if message.from_user is None:
        return

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, message.from_user)

    await message.answer(format_progress_display(user))


@router.message(F.text == FAMILY_UNLINK_TEXT)
async def msg_family_unlink(message: Message) -> None:
    if message.from_user is None:
        return

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, message.from_user)
        family_link = await get_family_for_user(session, user_id=user.id)

    if family_link is None:
        await message.answer("Семейная связь уже отсутствует.")
        return

    await message.answer(
        "Вы точно хотите отменить семейную связь?",
        reply_markup=family_unlink_confirm_keyboard(),
    )


@router.message(F.text == FAMILY_PSYCHOLOGIST_TEXT)
async def msg_psychologist_contact(message: Message) -> None:
    await message.answer(
        "Связаться с психологом можно здесь:",
        reply_markup=psychologist_link_keyboard(),
    )


@router.callback_query(F.data == FAMILY_UNLINK_CONFIRM_CALLBACK)
async def cb_family_unlink_confirm(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return
    await callback.answer()

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, callback.from_user)
        unlinked = await unlink_family(session, user_id=user.id)
        family_status = await get_family_status_for_user(session, user_id=user.id)

    if not unlinked:
        await callback.message.answer("Семейная связь уже отсутствует.")
        return

    await callback.message.answer(
        "Семейная связь отменена. Теперь можно обновить роль или создать новую связь позже.",
        reply_markup=family_status_keyboard(
            role=family_status.role,
            has_family_link=family_status.has_family_link,
        ),
    )


@router.callback_query(F.data == FAMILY_UNLINK_CANCEL_CALLBACK)
async def cb_family_unlink_cancel(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    await callback.answer()
    await callback.message.answer("Отмена действия. Семейная связь не изменена.")


@router.message(F.text == ROLE_REFRESH_TEXT)
async def msg_refresh_role(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, message.from_user)

        if user.role is None:
            await state.clear()
            await state.set_state(RegistrationStates.waiting_for_role)
            await message.answer("Выберите роль:", reply_markup=ReplyKeyboardRemove())
            await message.answer(START_TEXTS["choose_role"], reply_markup=role_keyboard())
            return

        linked_family = await get_family_for_user(session, user_id=user.id)
        if linked_family is not None:
            family_status = await get_family_status_for_user(session, user_id=user.id)
            await message.answer(
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
    await message.answer("Обновим роль.", reply_markup=ReplyKeyboardRemove())
    await message.answer(START_TEXTS["choose_role"], reply_markup=role_keyboard())


@router.callback_query(F.data.startswith(FAMILY_CONFIRM_PREFIX))
async def cb_family_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None:
        return

    await callback.answer()

    token = _extract_token_from_callback(callback.data, FAMILY_CONFIRM_PREFIX)
    if token is None:
        await callback.message.answer(START_TEXTS["invite_invalid"])
        return

    async with AsyncSessionLocal() as session:
        confirmer, _ = await get_or_create_user(session, callback.from_user)
        invite = await get_testable_invite_by_token(session, token=token)
        if invite is None:
            await callback.message.answer(START_TEXTS["invite_invalid"])
            return
        required_role = _required_role_for_invite_status(invite.status)
        if required_role is None:
            await callback.message.answer(START_TEXTS["invite_invalid"])
            return

        if confirmer.role is not None and confirmer.role != required_role:
            await callback.message.answer(_wrong_role_invite_message(required_role))
            return

        if confirmer.role is None:
            confirmer.role = required_role
            await session.commit()

        try:
            payload = await _complete_family_link_payload(session, confirmer=confirmer, token=token)
        except ValueError:
            await callback.message.answer(START_TEXTS["invite_invalid"])
            return

    actor_success_text = "✅ Семейная связь создана!"
    role_label = ROLE_LABELS.get(payload["actor_role"], payload["actor_role"])
    actor_success_text += f"\nВаша роль: <b>{role_label}</b>."

    await callback.message.answer(
        f"{actor_success_text}\n\n{payload['actor_family_status_text']}",
        reply_markup=family_status_keyboard(role=payload["actor_role"], has_family_link=payload["actor_has_family_link"]),
    )

    if payload["peer_telegram_id"] is not None:
        peer_success_text = "Семейная связь успешно создана."
        if payload["peer_label"]:
            peer_success_text = f"Семейная связь успешно создана, {payload['peer_label']}."
        try:
            await callback.bot.send_message(
                payload["peer_telegram_id"],
                f"{peer_success_text}\n{payload['peer_family_status_text']}",
                reply_markup=family_status_keyboard(
                    role=payload["peer_role"],
                    has_family_link=payload["peer_has_family_link"],
                ),
            )
        except Exception:
            log.warning("Failed to notify user about family link", exc_info=True)


@router.callback_query(F.data.startswith(FAMILY_DECLINE_PREFIX))
async def cb_family_decline(callback: CallbackQuery) -> None:
    if callback.message is None:
        return

    await callback.answer()
    token = _extract_token_from_callback(callback.data, FAMILY_DECLINE_PREFIX)
    if token is None:
        await callback.message.answer(START_TEXTS["invite_invalid"])
        return

    async with AsyncSessionLocal() as session:
        invite = await cancel_family_invite(session, token=token)

    if invite is None:
        await callback.message.answer(START_TEXTS["invite_invalid"])
        return

    await callback.message.answer("Приглашение отклонено. При необходимости можно создать новую ссылку позже.")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return

    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, message.from_user)
        active_session = await get_active_test_session(session, user_id=user.id)
        if active_session is None:
            await message.answer("Сейчас нет активного теста.")
            return

        await cancel_test_session(session, session_id=active_session.id)

    await state.clear()
    await message.answer("Тест отменен. Вы можете начать заново командой /start.")


@router.message(Command("restart"))
async def cmd_restart(message: Message, state: FSMContext) -> None:
    if message.from_user is None:
        return
    await state.clear()
    async with AsyncSessionLocal() as session:
        user, _ = await get_or_create_user(session, message.from_user)
    await state.set_state(RegistrationStates.waiting_for_role)
    await message.answer(TEXTS["start"], reply_markup=mode_keyboard(role=user.role))


@router.callback_query(F.data.startswith(POST_SUMMARY_RESTART_PREFIX))
async def cb_post_summary_restart(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None:
        return

    await callback.answer()

    session_id = _extract_session_id_from_callback(callback.data, POST_SUMMARY_RESTART_PREFIX)
    if session_id is None:
        await callback.message.answer("Эта сессия недоступна. Пройдите тест заново.")
        return

    owned = await _get_owned_session_or_notify(callback, session_id=session_id)
    if owned is None:
        return

    await _start_test_for_user(callback.message, state, callback.from_user)


@router.callback_query(F.data == RESTART_TEST_CALLBACK)
async def cb_restart_test_from_result(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or callback.message is None:
        return

    await callback.answer()
    await state.clear()
    await callback.message.answer("Начнём заново 👇")
    await _start_test_for_user(callback.message, state, callback.from_user)


@router.callback_query(F.data.startswith(POST_SUMMARY_EXTENDED_PREFIX))
async def cb_post_summary_extended(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return

    await callback.answer()

    session_id = _extract_session_id_from_callback(callback.data, POST_SUMMARY_EXTENDED_PREFIX)
    if session_id is None:
        await callback.message.answer("Эта сессия недоступна. Пройдите тест заново.")
        return

    owned = await _get_owned_session_or_notify(callback, session_id=session_id)
    if owned is None:
        return
    test_session, _ = owned

    if test_session.status != "completed":
        await callback.message.answer("Эта сессия недоступна. Пройдите тест заново.")
        return

    async with AsyncSessionLocal() as session:
        answers = await get_answers_for_session(session, session_id=test_session.id)

    if not answers:
        await callback.message.answer(
            "Недостаточно данных для расширенного разбора. Пройдите тест заново."
        )
        return

    expanded_report = await generate_expanded_ai_report(test_session.role_snapshot, answers)
    if expanded_report is None:
        await callback.message.answer(
            "Расширенный разбор пока недоступен. Сейчас доступен базовый результат."
        )
        return

    expanded_text = render_expanded_report_text(expanded_report)
    await callback.message.answer(expanded_text)


@router.callback_query(F.data.startswith(POST_SUMMARY_MENU_PREFIX))
async def cb_post_summary_menu(callback: CallbackQuery) -> None:
    if callback.from_user is None or callback.message is None:
        return

    await callback.answer()

    session_id = _extract_session_id_from_callback(callback.data, POST_SUMMARY_MENU_PREFIX)
    if session_id is None:
        await callback.message.answer("Эта сессия недоступна. Пройдите тест заново.")
        return

    owned = await _get_owned_session_or_notify(callback, session_id=session_id)
    if owned is None:
        return

    await callback.message.answer(
        "Вы вернулись в главное меню.\n\n"
        "Доступные действия:\n"
        "- /start\n"
        "- /restart"
    )


@router.message(RegistrationStates.answering_test)
async def handle_test_answer(message: Message, state: FSMContext) -> None:
    if message.text == ROLE_REFRESH_TEXT:
        await msg_refresh_role(message, state)
        return

    await message.answer("Выберите один из вариантов кнопкой под вопросом.")


# ───────── FALLBACK БЕЗ FSM ─────────

@router.callback_query(F.data.startswith(ROLE_CALLBACK_PREFIX))
async def cb_select_role_stateless(callback: CallbackQuery, state: FSMContext):
    print(f"🟡 DEBUG: cb_select_role_stateless CALLED with data={callback.data}")
    log.info("🟡 DEBUG: cb_select_role_stateless CALLED with data=%s", callback.data)
    if callback.from_user is None or callback.message is None:
        return

    role = (callback.data or "").replace(ROLE_CALLBACK_PREFIX, "")
    if callback.from_user is not None:
        log.info("[LIVE_CHECK] role_stateless data=%s parsed_role=%s user_id=%s", callback.data, role, callback.from_user.id)
    if role not in VALID_ROLES:
        await callback.answer("Ошибка роли", show_alert=True)
        return

    await state.set_state(RegistrationStates.waiting_for_role)
    await state.update_data(selected_role=role)

    await cb_select_role(callback, state)


@router.callback_query(F.data.in_({MODE_PERSONAL, MODE_PAIR}))
async def cb_mode_stateless(callback: CallbackQuery, state: FSMContext):
    print(f"🟡 DEBUG: cb_mode_stateless CALLED with data={callback.data}")
    log.info("🟡 DEBUG: cb_mode_stateless CALLED with data=%s", callback.data)
    if callback.message is None:
        return
    if callback.from_user is not None:
        log.info("[LIVE_CHECK] mode_stateless data=%s user_id=%s", callback.data, callback.from_user.id)

    await state.set_state(RegistrationStates.waiting_for_role)

    if callback.data == MODE_PERSONAL:
        await cb_mode_personal(callback, state)
    else:
        await cb_mode_pair(callback, state)
