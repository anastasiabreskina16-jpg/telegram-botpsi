from aiogram.types import User as TgUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User

VALID_ROLES: frozenset[str] = frozenset({"teen", "parent"})


async def get_or_create_user(session: AsyncSession, tg_user: TgUser) -> tuple[User, bool]:
    """Return (user, created). Lookup by telegram_id."""
    result = await session.execute(
        select(User).where(User.telegram_id == tg_user.id)
    )
    user = result.scalar_one_or_none()

    if user is not None:
        updated = False
        if user.username != tg_user.username:
            user.username = tg_user.username
            updated = True
        if user.full_name != tg_user.full_name:
            user.full_name = tg_user.full_name
            updated = True
        if updated:
            await session.commit()
        return user, False

    user = User(
        telegram_id=tg_user.id,
        username=tg_user.username,
        full_name=tg_user.full_name,
        role=None,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user, True


async def set_user_role(session: AsyncSession, telegram_id: int, role: str) -> User:
    """Persist the chosen role and return the updated user."""
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    user = result.scalar_one()
    user.role = role
    await session.commit()
    await session.refresh(user)
    return user


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(
        select(User).where(User.id == user_id)
    )
    return result.scalar_one_or_none()


async def update_user_display_name(session: AsyncSession, user_id: int, display_name: str) -> None:
    user = await get_user_by_id(session, user_id=user_id)
    if user is None:
        return

    if user.display_name != display_name:
        user.display_name = display_name
        await session.commit()


async def get_user_role(session: AsyncSession, telegram_id: int) -> str | None:
    """Return the stored role for the given Telegram user ID, or None."""
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()
    return user.role if user is not None else None


async def update_user_family_title(session: AsyncSession, user_id: int, family_title: str) -> None:
    user = await get_user_by_id(session, user_id=user_id)
    if user is None:
        return

    if user.family_title != family_title:
        user.family_title = family_title
        await session.commit()


async def update_user_profile_meta(
    session: AsyncSession,
    user_id: int,
    display_name: str | None = None,
    family_title: str | None = None,
) -> None:
    user = await get_user_by_id(session, user_id=user_id)
    if user is None:
        return

    updated = False
    if display_name is not None:
        if user.display_name != display_name:
            user.display_name = display_name
            updated = True
    if family_title is not None:
        if user.family_title != family_title:
            user.family_title = family_title
            updated = True

    if updated:
        await session.commit()
