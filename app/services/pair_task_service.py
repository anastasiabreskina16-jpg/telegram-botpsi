from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ObservationEntry, PairTask, PairTaskResponse, User
from app.services.family_service import get_family_for_user
from app.services.pair_task_templates import PAIR_TASK_TEMPLATES

TASK_BY_OBSERVATION_KIND = {
    "teen_interest": "interest_moments",
    "teen_liked": "what_energizes",
    "teen_repeat": "repeat_success",
    "teen_bored": "boredom_map",
    "teen_confidence": "strengths_mirror",
    "parent_initiative": "catch_initiative",
    "parent_energized": "what_energizes",
    "parent_stress": "what_helps_me",
    "parent_fatigue": "boredom_map",
}

_KNOWN_TASK_CODES = set(PAIR_TASK_TEMPLATES.keys())

TEEN_Q1_CODE = "teen_reflection_q1"
TEEN_Q2_CODE = "teen_reflection_q2"
PARENT_Q1_CODE = "parent_reflection_q1"
PARENT_Q2_CODE = "parent_reflection_q2"

LEGACY_TASK_CODE_ALIASES = {
    "three_interest_moments": "interest_moments",
    "no_advice_talk": "talk_without_advice",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _task_by_code(code: str) -> dict | None:
    canonical_code = LEGACY_TASK_CODE_ALIASES.get(code, code)
    return PAIR_TASK_TEMPLATES.get(canonical_code)


def get_reflection_questions_for_role(role: str, *, task_code: str | None = None) -> list[tuple[str, str]]:
    task_tpl = _task_by_code(task_code or "") if task_code else None
    if task_tpl is None:
        if role == "parent":
            return [(PARENT_Q1_CODE, "Что вы заметили в поведении подростка во время задачи?")]
        return [(TEEN_Q1_CODE, "Что в этой задаче получилось лучше всего?")]

    if role == "parent":
        parent_questions = task_tpl.get("parent_reflection_questions")
        if not isinstance(parent_questions, list):
            parent_questions = []

        first = parent_questions[0] if parent_questions else None
        if not isinstance(first, str) or not first.strip():
            first = "Что вы заметили в поведении подростка во время задачи?"
        questions: list[tuple[str, str]] = [(PARENT_Q1_CODE, first)]
        second = parent_questions[1] if len(parent_questions) > 1 else None
        if isinstance(second, str) and second.strip():
            questions.append((PARENT_Q2_CODE, second))
        return questions

    teen_questions = task_tpl.get("teen_reflection_questions")
    if not isinstance(teen_questions, list):
        teen_questions = []

    first = teen_questions[0] if teen_questions else None
    if not isinstance(first, str) or not first.strip():
        first = "Что в этой задаче получилось лучше всего?"
    questions = [(TEEN_Q1_CODE, first)]
    second = teen_questions[1] if len(teen_questions) > 1 else None
    if isinstance(second, str) and second.strip():
        questions.append((TEEN_Q2_CODE, second))
    return questions


def render_pair_task_text(pair_task: PairTask) -> str:
    lib_task = _task_by_code(pair_task.task_code)
    if lib_task is None:
        lib_task = {
            "short_description": pair_task.description,
            "teen_instruction": "Сделайте задачу в удобном темпе и зафиксируйте короткий результат.",
            "parent_observation_focus": "Отметьте, где подросток включался легче и где уставал меньше.",
            "steps": [
                "Согласуйте короткий план выполнения.",
                "Сделайте задачу вместе без давления.",
                "Сформулируйте 1 общий вывод.",
            ],
        }

    steps = "\n".join(f"- {step}" for step in lib_task["steps"])
    status_label = {
        "active": "активна",
        "pending_invite": "ожидает подтверждения",
        "postponed": "отложена",
        "completed": "завершена",
        "cancelled": "отменена",
    }.get(pair_task.status, pair_task.status)
    lines = [
        f"Задача: {pair_task.title}",
        f"Статус: {status_label}",
        "",
        lib_task["short_description"],
        "",
        "Что делает подросток:",
        lib_task["teen_instruction"],
        "",
        "Что наблюдает родитель:",
        lib_task["parent_observation_focus"],
        "",
        "Шаги:",
        steps,
    ]
    return "\n".join(lines)


async def get_family_context(session: AsyncSession, *, user_id: int):
    family_link = await get_family_for_user(session, user_id=user_id)
    if family_link is None:
        return None, None, None

    me = await session.scalar(select(User).where(User.id == user_id))
    if me is None:
        return family_link, None, None

    peer_id = family_link.teen_user_id if me.role == "parent" else family_link.parent_user_id
    peer_user = await session.scalar(select(User).where(User.id == peer_id)) if peer_id is not None else None
    return family_link, me, peer_user


async def get_active_pair_task(session: AsyncSession, *, family_link_id: int) -> PairTask | None:
    return await session.scalar(
        select(PairTask)
        .where(PairTask.family_link_id == family_link_id, PairTask.status == "active")
        .order_by(desc(PairTask.created_at), desc(PairTask.id))
        .limit(1)
    )


async def get_latest_pending_invite_task(session: AsyncSession, *, family_link_id: int) -> PairTask | None:
    return await session.scalar(
        select(PairTask)
        .where(
            PairTask.family_link_id == family_link_id,
            PairTask.status.in_(["pending_invite", "postponed"]),
        )
        .order_by(desc(PairTask.created_at), desc(PairTask.id))
        .limit(1)
    )


async def get_pair_task_by_id(session: AsyncSession, *, pair_task_id: int) -> PairTask | None:
    return await session.scalar(select(PairTask).where(PairTask.id == pair_task_id))


async def get_latest_completed_pair_task(session: AsyncSession, *, family_link_id: int) -> PairTask | None:
    return await session.scalar(
        select(PairTask)
        .where(PairTask.family_link_id == family_link_id, PairTask.status == "completed")
        .order_by(desc(PairTask.completed_at), desc(PairTask.id))
        .limit(1)
    )


async def _pick_task_code_for_family(
    session: AsyncSession,
    *,
    family_link_id: int,
    preferred_code: str | None,
    exclude_codes: set[str] | None = None,
) -> str:
    excluded = exclude_codes or set()
    all_codes = list(PAIR_TASK_TEMPLATES.keys())
    available_codes = [code for code in all_codes if code not in excluded]
    if not available_codes:
        available_codes = all_codes

    if preferred_code and _task_by_code(preferred_code) is not None and preferred_code not in excluded:
        return preferred_code

    history = await session.execute(
        select(PairTask.task_code)
        .where(PairTask.family_link_id == family_link_id)
        .order_by(desc(PairTask.created_at), desc(PairTask.id))
        .limit(len(all_codes) * 2)
    )
    used_codes = [row[0] for row in history.all()]

    for code in available_codes:
        if code not in used_codes:
            return code

    idx = len(used_codes) % len(available_codes)
    return available_codes[idx]


async def suggest_task_code_from_observations(session: AsyncSession, *, family_link_id: int) -> str | None:
    recent = await session.execute(
        select(ObservationEntry.entry_kind)
        .where(
            ObservationEntry.family_link_id == family_link_id,
            ObservationEntry.status == "active",
            ObservationEntry.is_visible_in_summary.is_(True),
        )
        .order_by(desc(ObservationEntry.created_at), desc(ObservationEntry.id))
        .limit(30)
    )
    kinds = [row[0] for row in recent.all()]
    if not kinds:
        return None

    top_kind = Counter(kinds).most_common(1)[0][0]
    candidate = TASK_BY_OBSERVATION_KIND.get(top_kind)
    if candidate in _KNOWN_TASK_CODES:
        return candidate
    return None


async def create_pair_task(
    session: AsyncSession,
    *,
    family_link_id: int,
    source_type: str,
    created_by_user_id: int | None = None,
    invited_user_id: int | None = None,
    preferred_code: str | None = None,
    replace_active: bool = False,
    initial_status: str = "pending_invite",
) -> PairTask:
    active = await get_active_pair_task(session, family_link_id=family_link_id)
    pending = await get_latest_pending_invite_task(session, family_link_id=family_link_id)
    excluded_codes: set[str] = set()
    if active is not None:
        if not replace_active:
            return active
        excluded_codes.add(active.task_code)
        active.status = "cancelled"
        active.completed_at = _now()
    if pending is not None:
        if not replace_active:
            return pending
        excluded_codes.add(pending.task_code)
        pending.status = "cancelled"
        pending.completed_at = _now()

    task_code = await _pick_task_code_for_family(
        session,
        family_link_id=family_link_id,
        preferred_code=preferred_code,
        exclude_codes=excluded_codes,
    )
    source = source_type if source_type in {"manual", "observation"} else "manual"
    task_tpl = _task_by_code(task_code)
    if task_tpl is None:
        fallback_code = next(iter(PAIR_TASK_TEMPLATES))
        task_tpl = PAIR_TASK_TEMPLATES[fallback_code]

    task = PairTask(
        family_link_id=family_link_id,
        created_by_user_id=created_by_user_id,
        invited_user_id=invited_user_id,
        accepted_by_user_id=None,
        task_code=task_tpl["task_code"],
        title=task_tpl["title"],
        description=task_tpl["short_description"],
        source_type=source,
        status=initial_status,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def complete_pair_task(session: AsyncSession, *, pair_task_id: int) -> PairTask | None:
    task = await session.scalar(select(PairTask).where(PairTask.id == pair_task_id))
    if task is None:
        return None
    if task.status == "completed":
        return task
    task.status = "completed"
    task.completed_at = _now()
    await session.commit()
    await session.refresh(task)
    return task


async def set_pair_task_status(session: AsyncSession, *, pair_task_id: int, status: str) -> PairTask | None:
    task = await get_pair_task_by_id(session, pair_task_id=pair_task_id)
    if task is None:
        return None

    task.status = status
    now = _now()
    if status == "completed":
        task.completed_at = now
    elif status == "active":
        task.accepted_at = now
    await session.commit()
    await session.refresh(task)
    return task


async def accept_pair_task_invite(
    session: AsyncSession,
    *,
    pair_task_id: int,
    accepter_user_id: int,
) -> PairTask | None:
    task = await get_pair_task_by_id(session, pair_task_id=pair_task_id)
    if task is None:
        return None
    if task.status not in {"pending_invite", "postponed"}:
        return task
    if task.invited_user_id is not None and task.invited_user_id != accepter_user_id:
        return None

    task.status = "active"
    task.accepted_by_user_id = accepter_user_id
    task.accepted_at = _now()
    await session.commit()
    await session.refresh(task)
    return task


async def get_pair_task_history(
    session: AsyncSession,
    *,
    family_link_id: int,
    limit: int = 10,
) -> list[PairTask]:
    safe_limit = 20 if limit > 20 else max(1, limit)
    result = await session.execute(
        select(PairTask)
        .where(PairTask.family_link_id == family_link_id)
        .order_by(desc(PairTask.created_at), desc(PairTask.id))
        .limit(safe_limit)
    )
    return list(result.scalars().all())


async def save_pair_task_response(
    session: AsyncSession,
    *,
    pair_task_id: int,
    user_id: int,
    role: str,
    question_code: str,
    answer_text: str,
) -> PairTaskResponse:
    clean_text = answer_text.strip()
    if not clean_text:
        raise ValueError("empty_text")
    if role not in {"teen", "parent"}:
        raise ValueError("invalid_role")

    response = PairTaskResponse(
        pair_task_id=pair_task_id,
        user_id=user_id,
        role=role,
        question_code=question_code,
        answer_text=clean_text,
    )
    session.add(response)
    # Persist inside текущей транзакции, финальный commit делает handler.
    await session.flush()
    return response


async def get_pair_task_responses(session: AsyncSession, *, pair_task_id: int) -> list[PairTaskResponse]:
    result = await session.execute(
        select(PairTaskResponse)
        .where(PairTaskResponse.pair_task_id == pair_task_id)
        .order_by(desc(PairTaskResponse.created_at), desc(PairTaskResponse.id))
    )
    return list(result.scalars().all())


async def get_user_answers_count(
    session: AsyncSession,
    *,
    pair_task_id: int,
    user_id: int,
) -> int:
    result = await session.execute(
        select(PairTaskResponse)
        .where(
            PairTaskResponse.pair_task_id == pair_task_id,
            PairTaskResponse.user_id == user_id,
        )
    )
    return len(result.scalars().all())


async def count_answers_for_user(
    session: AsyncSession,
    *,
    pair_task_id: int,
    user_id: int,
) -> int:
    return await get_user_answers_count(
        session,
        pair_task_id=pair_task_id,
        user_id=user_id,
    )


async def has_role_responses_for_task(
    session: AsyncSession,
    *,
    pair_task_id: int,
    role: str,
) -> bool:
    row = await session.scalar(
        select(PairTaskResponse.id)
        .where(PairTaskResponse.pair_task_id == pair_task_id, PairTaskResponse.role == role)
        .limit(1)
    )
    return row is not None


def build_pair_task_summary(*, pair_task: PairTask, responses: list[PairTaskResponse]) -> str:
    task_tpl = _task_by_code(pair_task.task_code)
    summary_hint = (
        task_tpl["summary_hint"]
        if task_tpl is not None and isinstance(task_tpl.get("summary_hint"), str)
        else "Зафиксируйте условия, где подросток легче включается, и мягко повторяйте их в следующих шагах."
    )

    if not responses:
        return (
            "Задача завершена. Добавьте короткую рефлексию, чтобы бот собрал мягкий общий итог "
            "по тому, что помогло и что стоит повторить."
        )

    role_counter = Counter(item.role for item in responses)
    top_signals = Counter(item.question_code for item in responses).most_common(2)

    lines = [
        "Краткий итог по задаче",
        "",
        f"Задача: {pair_task.title}",
        f"Ответов в рефлексии: {len(responses)}",
        f"От подростка: {role_counter.get('teen', 0)}",
        f"От родителя: {role_counter.get('parent', 0)}",
    ]

    if top_signals:
        lines.append("")
        lines.append("Что уже собрано по ответам:")
        for code, count in top_signals:
            lines.append(f"- {code}: {count}")

    lines.append("")
    lines.append(f"Мягкий вывод: {summary_hint}")
    return "\n".join(lines)
