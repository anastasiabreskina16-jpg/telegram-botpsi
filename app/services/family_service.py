from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
import builtins
import secrets

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FamilyLink, User

ValueError = builtins.ValueError

INVITE_TTL_HOURS = 24


@dataclass(slots=True)
class FamilyStatus:
    has_family_link: bool
    role: str
    linked_user_id: int | None
    linked_user_name: str | None
    status_text: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_token():
    # 16 bytes urlsafe gives a short opaque token and stays under Telegram start payload limits.
    return secrets.token_urlsafe(16)


async def create_family_invite(
    session: AsyncSession,
    *,
    inviter_user_id: int,
    inviter_role: str,
) -> FamilyLink:
    pending_statuses = {"pending", "pending_parent"}

    if inviter_role == "parent":
        linked = await get_linked_family_for_parent(session, parent_user_id=inviter_user_id)
        if linked is not None:
            raise ValueError("already_linked")

        existing_pending_result = await session.execute(
            select(FamilyLink).where(
                FamilyLink.parent_user_id == inviter_user_id,
                FamilyLink.status.in_(pending_statuses),
            )
        )
        existing_invite = existing_pending_result.scalars().first()
        if existing_invite is not None:
            return existing_invite

        invite_status = "pending"
        parent_user_id = inviter_user_id
        teen_user_id = None
    elif inviter_role == "teen":
        linked = await get_linked_family_for_teen(session, teen_user_id=inviter_user_id)
        if linked is not None:
            raise ValueError("already_linked")

        existing_pending_result = await session.execute(
            select(FamilyLink).where(
                FamilyLink.teen_user_id == inviter_user_id,
                FamilyLink.status.in_(pending_statuses),
            )
        )
        existing_invite = existing_pending_result.scalars().first()
        if existing_invite is not None:
            return existing_invite

        # Keep inviter teen ID in teen_user_id while parent is still unknown.
        invite_status = "pending_parent"
        parent_user_id = inviter_user_id
        teen_user_id = inviter_user_id
    else:
        raise ValueError("invalid_role")

    token = _new_token()
    while await get_family_invite_by_token(session, token=token) is not None:
        token = _new_token()

    invite = FamilyLink(
        parent_user_id=parent_user_id,
        teen_user_id=teen_user_id,
        invite_token=token,
        status=invite_status,
        expires_at=_now() + timedelta(hours=INVITE_TTL_HOURS),
    )
    session.add(invite)
    await session.commit()
    await session.refresh(invite)
    return invite


async def get_family_invite_by_token(session: AsyncSession, *, token) -> FamilyLink | None:
    result = await session.execute(
        select(FamilyLink).where(FamilyLink.invite_token == token)
    )
    return result.scalar_one_or_none()


async def get_testable_invite_by_token(session: AsyncSession, *, token) -> FamilyLink | None:
    invite = await get_family_invite_by_token(session, token=token)
    if invite is None:
        return None

    if invite.status not in {"pending", "pending_parent"}:
        return None

    if invite.expires_at <= _now():
        invite.status = "expired"
        await session.commit()
        return None

    return invite


async def get_linked_family_for_teen(session: AsyncSession, *, teen_user_id) -> FamilyLink | None:
    result = await session.execute(
        select(FamilyLink).where(
            FamilyLink.teen_user_id == teen_user_id,
            FamilyLink.status == "linked",
        )
    )
    return result.scalars().first()


async def get_linked_family_for_parent(session: AsyncSession, *, parent_user_id) -> FamilyLink | None:
    result = await session.execute(
        select(FamilyLink).where(
            FamilyLink.parent_user_id == parent_user_id,
            FamilyLink.status == "linked",
        )
    )
    return result.scalars().first()


async def link_family_by_token(
    session: AsyncSession,
    *,
    token,
    accepter_user_id,
    accepter_role,
) -> FamilyLink:
    invite = await get_family_invite_by_token(session, token=token)
    if invite is None:
        raise ValueError("not_found")

    if invite.status not in {"pending", "pending_parent"}:
        raise ValueError("not_pending")

    if invite.status == "pending" and invite.parent_user_id == accepter_user_id:
        raise ValueError("self_link")

    if invite.status == "pending_parent" and invite.teen_user_id == accepter_user_id:
        raise ValueError("self_link")

    if invite.expires_at <= _now():
        invite.status = "expired"
        await session.commit()
        raise ValueError("expired")

    if invite.status == "pending":
        if accepter_role == "parent":
            raise ValueError("wrong_role")

        linked = await get_linked_family_for_teen(session, teen_user_id=accepter_user_id)
        if linked is not None and linked.id != invite.id:
            raise ValueError("teen_already_linked")

        parent_linked = await get_linked_family_for_parent(session, parent_user_id=invite.parent_user_id)
        if parent_linked is not None and parent_linked.id != invite.id:
            raise ValueError("parent_already_linked")

        invite.teen_user_id = accepter_user_id
    else:
        if accepter_role == "teen":
            raise ValueError("wrong_role")

        inviter_teen_id = invite.teen_user_id
        if inviter_teen_id is None:
            raise ValueError("invalid_invite")

        teen_linked = await get_linked_family_for_teen(session, teen_user_id=inviter_teen_id)
        if teen_linked is not None and teen_linked.id != invite.id:
            raise ValueError("teen_already_linked")

        parent_linked = await get_linked_family_for_parent(session, parent_user_id=accepter_user_id)
        if parent_linked is not None and parent_linked.id != invite.id:
            raise ValueError("parent_already_linked")

        invite.parent_user_id = accepter_user_id

    invite.status = "linked"
    invite.used_at = _now()
    await session.commit()
    await session.refresh(invite)
    return invite


async def cancel_family_invite(session: AsyncSession, *, token) -> FamilyLink | None:
    invite = await get_family_invite_by_token(session, token=token)
    if invite is None:
        return None

    if invite.status not in {"pending", "pending_parent"}:
        return None

    invite.status = "cancelled"
    await session.commit()
    await session.refresh(invite)
    return invite


async def get_family_for_user(session: AsyncSession, *, user_id) -> FamilyLink | None:
    result = await session.execute(
        select(FamilyLink)
        .where(
            or_(
                FamilyLink.parent_user_id == user_id,
                FamilyLink.teen_user_id == user_id,
            ),
            FamilyLink.status == "linked",
        )
        .order_by(FamilyLink.id.desc())
    )
    return result.scalars().first()


async def unlink_family(session: AsyncSession, user_id: int) -> bool:
    family_link = await get_family_for_user(session, user_id=user_id)
    if family_link is None:
        return False

    family_link.status = "cancelled"
    await session.commit()
    return True


async def get_family_status_for_user(session: AsyncSession, *, user_id: int) -> FamilyStatus:
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    role = (user.role if user is not None else None) or "unknown"
    family_link = await get_family_for_user(session, user_id=user_id)

    if family_link is None:
        if role == "parent":
            return FamilyStatus(
                has_family_link=False,
                role=role,
                linked_user_id=None,
                linked_user_name=None,
                status_text="Семейная связь пока не создана. Подключите подростка, чтобы проходить семейные сценарии и смотреть общие результаты.",
            )
        if role == "teen":
            return FamilyStatus(
                has_family_link=False,
                role=role,
                linked_user_id=None,
                linked_user_name=None,
                status_text="Семейная связь пока не создана. Подключите родителя, чтобы открыть семейные сценарии и совместные результаты.",
            )
        return FamilyStatus(
            has_family_link=False,
            role=role,
            linked_user_id=None,
            linked_user_name=None,
            status_text="Семейная связь пока недоступна. Сначала выберите роль.",
        )

    linked_user_id: int | None
    if role == "parent":
        linked_user_id = family_link.teen_user_id
    elif role == "teen":
        linked_user_id = family_link.parent_user_id
    else:
        linked_user_id = None

    if linked_user_id is None:
        return FamilyStatus(
            has_family_link=True,
            role=role,
            linked_user_id=None,
            linked_user_name=None,
            status_text="Семейная связь найдена, но данные второй стороны сейчас недоступны. Попробуйте позже или обновите статус семьи.",
        )

    linked_result = await session.execute(select(User).where(User.id == linked_user_id))
    linked_user = linked_result.scalar_one_or_none()
    if linked_user is None:
        return FamilyStatus(
            has_family_link=True,
            role=role,
            linked_user_id=linked_user_id,
            linked_user_name=None,
            status_text="Семейная связь найдена, но данные второй стороны сейчас недоступны. Попробуйте позже или обновите статус семьи.",
        )

    if role == "parent":
        status_text = "Семейная связь активна: подросток подключён. Теперь можно проходить тесты и смотреть семейные результаты."
    elif role == "teen":
        status_text = "Семейная связь активна: родитель подключён. Теперь можно проходить тесты и смотреть семейные результаты."
    else:
        status_text = "Семейная связь активна."

    return FamilyStatus(
        has_family_link=True,
        role=role,
        linked_user_id=linked_user.id,
        linked_user_name=linked_user.full_name or linked_user.username,
        status_text=status_text,
    )
