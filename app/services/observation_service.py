from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ObservationEntry
from app.services.family_service import get_family_for_user

TEEN_ENTRY_KINDS: list[tuple[str, str]] = [
    ("teen_liked", "Что понравилось"),
    ("teen_success", "Что получилось"),
    ("teen_interest", "Где было интересно"),
    ("teen_bored", "Что было скучно"),
    ("teen_confidence", "Где почувствовал(а) уверенность"),
    ("teen_repeat", "Что хотелось бы повторить"),
]

PARENT_ENTRY_KINDS: list[tuple[str, str]] = [
    ("parent_initiative", "Где увидел(а) инициативу"),
    ("parent_stress", "Где заметил(а) стресс"),
    ("parent_strength", "Что у ребёнка хорошо получилось"),
    ("parent_energized", "Что его оживило"),
    ("parent_fast_engagement", "Где он быстро включился"),
    ("parent_fatigue", "Где начал уставать / раздражаться"),
]

ENTRY_KIND_LABELS: dict[str, str] = dict(TEEN_ENTRY_KINDS + PARENT_ENTRY_KINDS)
POSITIVE_KINDS = {
    "teen_liked",
    "teen_success",
    "teen_interest",
    "teen_confidence",
    "teen_repeat",
    "parent_initiative",
    "parent_strength",
    "parent_energized",
    "parent_fast_engagement",
}
TENSION_KINDS = {"teen_bored", "parent_stress", "parent_fatigue"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_categories_for_role(role: str | None) -> list[tuple[str, str]]:
    if role == "parent":
        return PARENT_ENTRY_KINDS
    return TEEN_ENTRY_KINDS


def get_label_for_kind(kind: str) -> str:
    return ENTRY_KIND_LABELS.get(kind, kind)


async def create_observation_entry(
    session: AsyncSession,
    *,
    user_id: int,
    observer_role: str,
    entry_kind: str,
    text: str,
    score: int | None,
) -> ObservationEntry:
    if observer_role not in {"teen", "parent"}:
        raise ValueError("invalid_role")

    valid_kinds = {code for code, _ in get_categories_for_role(observer_role)}
    if entry_kind not in valid_kinds:
        raise ValueError("invalid_kind")

    clean_text = text.strip()
    if not clean_text:
        raise ValueError("empty_text")

    if score is not None and (score < 1 or score > 5):
        raise ValueError("invalid_score")

    family_link = await get_family_for_user(session, user_id=user_id)
    if family_link is None:
        raise ValueError("family_required")

    if observer_role == "teen":
        subject_user_id = user_id
    else:
        if family_link.teen_user_id is None:
            raise ValueError("teen_missing")
        subject_user_id = family_link.teen_user_id

    entry = ObservationEntry(
        family_link_id=family_link.id,
        user_id=user_id,
        subject_user_id=subject_user_id,
        observer_role=observer_role,
        entry_kind=entry_kind,
        text=clean_text,
        score=score,
        is_visible_in_summary=True,
        status="active",
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


async def get_user_observation_entries(
    session: AsyncSession,
    *,
    user_id: int,
    limit: int = 5,
) -> list[ObservationEntry]:
    safe_limit = 10 if limit > 10 else max(1, limit)
    result = await session.execute(
        select(ObservationEntry)
        .where(
            ObservationEntry.user_id == user_id,
            ObservationEntry.status == "active",
        )
        .order_by(desc(ObservationEntry.created_at), desc(ObservationEntry.id))
        .limit(safe_limit)
    )
    return list(result.scalars().all())


async def get_family_observation_entries(
    session: AsyncSession,
    *,
    user_id: int,
    days: int | None = None,
) -> tuple[object | None, list[ObservationEntry]]:
    family_link = await get_family_for_user(session, user_id=user_id)
    if family_link is None:
        return None, []

    stmt = (
        select(ObservationEntry)
        .where(
            ObservationEntry.family_link_id == family_link.id,
            ObservationEntry.status == "active",
            ObservationEntry.is_visible_in_summary.is_(True),
        )
        .order_by(desc(ObservationEntry.created_at), desc(ObservationEntry.id))
    )
    if days is not None:
        cutoff = _now() - timedelta(days=days)
        stmt = stmt.where(ObservationEntry.created_at >= cutoff)

    result = await session.execute(stmt)
    return family_link, list(result.scalars().all())


def build_overview_text(entries: list[ObservationEntry]) -> str:
    if not entries:
        return "Пока недостаточно наблюдений. Добавьте несколько коротких записей, чтобы увидеть повторяющиеся паттерны."

    kind_counter = Counter(e.entry_kind for e in entries)
    top_kinds = kind_counter.most_common(4)

    teen_counter = Counter(e.entry_kind for e in entries if e.observer_role == "teen")
    parent_counter = Counter(e.entry_kind for e in entries if e.observer_role == "parent")

    positive_count = sum(1 for e in entries if e.entry_kind in POSITIVE_KINDS)
    tension_count = sum(1 for e in entries if e.entry_kind in TENSION_KINDS)

    lines = [
        "Общая картина по наблюдениям",
        "",
        f"Всего записей в анализе: {len(entries)}",
        "Что повторяется чаще всего:",
    ]
    for kind, count in top_kinds:
        lines.append(f"- {get_label_for_kind(kind)}: {count}")

    if teen_counter:
        teen_kind, teen_count = teen_counter.most_common(1)[0]
        lines.append("")
        lines.append("Что чаще отмечает подросток:")
        lines.append(f"- {get_label_for_kind(teen_kind)} ({teen_count})")

    if parent_counter:
        parent_kind, parent_count = parent_counter.most_common(1)[0]
        lines.append("")
        lines.append("Что чаще отмечает родитель:")
        lines.append(f"- {get_label_for_kind(parent_kind)} ({parent_count})")

    lines.append("")
    lines.append("Баланс сигналов:")
    lines.append(f"- Поддерживающие сигналы: {positive_count}")
    lines.append(f"- Напряжённые сигналы: {tension_count}")
    lines.append("")
    lines.append(
        "Предварительный вывод: ориентируйтесь на условия, где чаще появляются интерес, включённость и инициатива, "
        "и отдельно снижайте зоны спешки и однообразной рутины."
    )
    return "\n".join(lines)


def build_weekly_summary_text(entries: list[ObservationEntry]) -> str:
    if not entries:
        return "За последние 7 дней пока нет записей. Добавьте 2-3 коротких наблюдения, чтобы получить сводку недели."

    kind_counter = Counter(e.entry_kind for e in entries)
    top_kinds = kind_counter.most_common(3)
    high_score_kinds = Counter(
        e.entry_kind for e in entries if e.score is not None and e.score >= 4
    ).most_common(3)

    lines = [
        "Сводка за неделю",
        "",
        f"Добавлено записей: {len(entries)}",
        "Чаще всего встречалось:",
    ]
    for kind, count in top_kinds:
        lines.append(f"- {get_label_for_kind(kind)}: {count}")

    if high_score_kinds:
        lines.append("")
        lines.append("Сильные сигналы (оценка 4-5):")
        for kind, count in high_score_kinds:
            lines.append(f"- {get_label_for_kind(kind)}: {count}")

    lines.append("")
    lines.append(
        "Фокус на следующую неделю: замечайте, где подросток сам начинает действовать без напоминаний "
        "и где появляется ощущение 'хочу продолжить'."
    )
    return "\n".join(lines)
