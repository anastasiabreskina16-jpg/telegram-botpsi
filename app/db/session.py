import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.db.models import Base

log = logging.getLogger(__name__)

engine = create_async_engine(settings.database_url, pool_pre_ping=True, echo=False)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if conn.dialect.name == "postgresql":
            await conn.exec_driver_sql(
                """
                ALTER TABLE pair_test_sessions
                ADD COLUMN IF NOT EXISTS ai_report TEXT,
                ADD COLUMN IF NOT EXISTS ai_report_generated BOOLEAN DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS phase2_report_sent BOOLEAN DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS teen_index INTEGER NOT NULL DEFAULT 0,
                ADD COLUMN IF NOT EXISTS parent_index INTEGER NOT NULL DEFAULT 0,
                ADD COLUMN IF NOT EXISTS teen_completed BOOLEAN NOT NULL DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS parent_completed BOOLEAN NOT NULL DEFAULT FALSE
                """
            )
            await conn.exec_driver_sql(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS display_name VARCHAR(128),
                ADD COLUMN IF NOT EXISTS family_title VARCHAR(32)
                """
            )
            await conn.exec_driver_sql(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS points INTEGER NOT NULL DEFAULT 0,
                ADD COLUMN IF NOT EXISTS level INTEGER NOT NULL DEFAULT 1,
                ADD COLUMN IF NOT EXISTS streak_days INTEGER NOT NULL DEFAULT 0,
                ADD COLUMN IF NOT EXISTS last_activity TIMESTAMPTZ
                """
            )
            await conn.exec_driver_sql(
                """
                ALTER TABLE pair_test_answers
                ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'waiting',
                ADD COLUMN IF NOT EXISTS locked BOOLEAN NOT NULL DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS reminder_sent BOOLEAN NOT NULL DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS timeout_triggered BOOLEAN NOT NULL DEFAULT FALSE
                """
            )
            await conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS user_activity (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    pair_id INTEGER NOT NULL REFERENCES pair_test_sessions(id) ON DELETE CASCADE,
                    last_action_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_question_at INTEGER,
                    reminder_stage INTEGER NOT NULL DEFAULT 0,
                    is_finished BOOLEAN NOT NULL DEFAULT FALSE,
                    reminders_sent_today INTEGER NOT NULL DEFAULT 0,
                    reminder_day TIMESTAMPTZ,
                    UNIQUE (pair_id, user_id)
                )
                """
            )
            await conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS user_behavior (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
                    last_seen_at TIMESTAMPTZ,
                    last_answer_at TIMESTAMPTZ,
                    avg_response_time INTEGER,
                    active_hours_json JSONB,
                    last_notification_at TIMESTAMPTZ,
                    notification_count_today INTEGER NOT NULL DEFAULT 0,
                    notification_day TIMESTAMPTZ
                )
                """
            )
            await conn.exec_driver_sql(
                """
                ALTER TABLE user_behavior
                ADD COLUMN IF NOT EXISTS visit_count INTEGER NOT NULL DEFAULT 0,
                ADD COLUMN IF NOT EXISTS answer_count INTEGER NOT NULL DEFAULT 0,
                ADD COLUMN IF NOT EXISTS return_count INTEGER NOT NULL DEFAULT 0,
                ADD COLUMN IF NOT EXISTS completion_count INTEGER NOT NULL DEFAULT 0
                """
            )
            await conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS user_segments (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
                    segment VARCHAR(32) NOT NULL DEFAULT 'ghost',
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            await conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS user_scores (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
                    score INTEGER NOT NULL DEFAULT 0,
                    engagement_score INTEGER NOT NULL DEFAULT 0,
                    completion_score INTEGER NOT NULL DEFAULT 0,
                    return_score INTEGER NOT NULL DEFAULT 0,
                    consistency_score INTEGER NOT NULL DEFAULT 5,
                    last_calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        else:
            log.warning("Skipping pair_test_sessions hardening migration for non-PostgreSQL dialect: %s", conn.dialect.name)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
