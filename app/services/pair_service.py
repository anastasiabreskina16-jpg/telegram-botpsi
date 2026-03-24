"""Pair invite service — lightweight pairing before the actual test session.

Flow:
    1. Teen creates a PairSession   → gets a deep link to share with parent.
    2. Parent follows the link      → connect_parent() links them → status "active".
    3. create_test_session_for_pair → creates the real PairTestSession for both.
"""
from __future__ import annotations

import builtins

from aiogram.utils.deep_linking import create_start_link
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PairSession, PairTestSession, User

ValueError = builtins.ValueError


async def build_invite_link(bot, pair_id: builtins.int) -> builtins.str:
    return await create_start_link(
        bot,
        payload=f"pair_{pair_id}",
        encode=True,
    )


async def build_pair_test_invite_link(bot, pair_test_session_id: builtins.int) -> builtins.str:
    """Build a deep link for teen join flow for parent-initiated PairTestSession."""
    return await create_start_link(
        bot,
        payload=f"joinpair_{pair_test_session_id}",
        encode=True,
    )


async def create_pair_session(
    session: AsyncSession,
    teen_telegram_id: builtins.int,
) -> PairSession:
    """Create a pending pair invite initiated by a teen."""
    pair = PairSession(teen_id=teen_telegram_id, status="pending")
    session.add(pair)
    await session.commit()
    await session.refresh(pair)
    return pair


async def get_pair_session(
    session: AsyncSession,
    pair_id: builtins.int,
) -> PairSession | None:
    """Fetch a PairSession by primary key."""
    return await session.get(PairSession, pair_id)


async def connect_parent(
    session: AsyncSession,
    pair_id: builtins.int,
    parent_telegram_id: builtins.int,
) -> PairSession:
    """Link a parent to a pending PairSession and mark it active."""
    pair = await session.get(PairSession, pair_id)
    if pair is None:
        raise ValueError("pair_not_found")
    if pair.teen_id == parent_telegram_id:
        raise ValueError("self_join")
    if pair.status != "pending" or pair.parent_id is not None:
        raise ValueError("already_connected")

    pair.parent_id = parent_telegram_id
    pair.status = "active"
    await session.commit()
    await session.refresh(pair)
    return pair


async def create_test_session_for_pair(
    session: AsyncSession,
    *,
    teen_telegram_id: builtins.int,
    parent_telegram_id: builtins.int,
) -> PairTestSession:
    """Create a real PairTestSession (active) once both sides are known."""
    teen_row = await session.execute(
        select(User).where(User.telegram_id == teen_telegram_id)
    )
    teen = teen_row.scalar_one_or_none()

    parent_row = await session.execute(
        select(User).where(User.telegram_id == parent_telegram_id)
    )
    parent = parent_row.scalar_one_or_none()

    if teen is None or parent is None:
        raise ValueError("user_not_found")

    # Reuse existing service to generate the unique code and set up the session.
    from app.services.pair_test_service import (
        create_pair_session as _create_pts,
        join_pair_session as _join_pts,
    )

    pts = await _create_pts(session, parent_user_id=parent.id)
    pts = await _join_pts(session, pair_code=pts.pair_code, teen_user_id=teen.id)
    return pts
