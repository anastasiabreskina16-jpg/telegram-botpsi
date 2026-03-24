from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── User ──────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # Plain string: "teen" | "parent" | None  — no enum
    role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Optional profile metadata for human-friendly messages.
    # Existing databases should add these columns manually if migrations are not used.
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    family_title: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Gamification fields
    points: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    streak_days: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    last_activity: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=_now, nullable=False
    )

    test_sessions: Mapped[list["TestSession"]] = relationship(
        "TestSession", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User telegram_id={self.telegram_id} role={self.role!r}>"


# ── TestSession (stub) ─────────────────────────────────────────────────────────

class TestSession(Base):
    __tablename__ = "test_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role_snapshot: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # teen_personal | parent_personal — nullable for backward compat with existing rows
    test_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="test_sessions")
    answers: Mapped[list["Answer"]] = relationship(
        "Answer", back_populates="session", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_test_sessions_user_id", "user_id"),)

    def __repr__(self) -> str:
        return f"<TestSession id={self.id} user_id={self.user_id} status={self.status!r}>"


# ── Answer (stub) ──────────────────────────────────────────────────────────────

class Answer(Base):
    __tablename__ = "answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("test_sessions.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    question_code: Mapped[str] = mapped_column(String(64), nullable=False)
    answer_value: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session: Mapped["TestSession"] = relationship("TestSession", back_populates="answers")

    __table_args__ = (
        Index("ix_answers_session_id", "session_id"),
        Index("ix_answers_user_id", "user_id"),
    )

    def __repr__(self) -> str:
        return f"<Answer id={self.id} session_id={self.session_id}>"


# ── FamilyLink (MVP) ─────────────────────────────────────────────────────────

class FamilyLink(Base):
    __tablename__ = "family_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    teen_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    invite_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_family_links_parent_user_id", "parent_user_id"),
        Index("ix_family_links_teen_user_id", "teen_user_id"),
    )

    def __repr__(self) -> str:
        return f"<FamilyLink id={self.id} status={self.status!r}>"


# ── PairTestSession ───────────────────────────────────────────────────────────

class PairTestSession(Base):
    __tablename__ = "pair_test_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pair_code: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    family_link_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("family_links.id", ondelete="SET NULL"), nullable=True
    )
    parent_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    teen_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # pending | active | parent_done | teen_done | completed | cancelled | expired
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ai_report: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_report_generated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    phase2_report_sent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    teen_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    parent_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    teen_completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    parent_completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    answers: Mapped[list["PairTestAnswer"]] = relationship(
        "PairTestAnswer", back_populates="pair_session", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_pair_test_sessions_parent_user_id", "parent_user_id"),
        Index("ix_pair_test_sessions_teen_user_id", "teen_user_id"),
        Index("ix_pair_test_sessions_pair_code", "pair_code"),
    )

    def __repr__(self) -> str:
        return f"<PairTestSession id={self.id} code={self.pair_code!r} status={self.status!r}>"


# ── UserResult (MVP Step 1) ─────────────────────────────────────────────────

class UserResult(Base):
    __tablename__ = "user_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pair_session_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    teen_scores: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    parent_scores: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    diff: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ai_report: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_user_results_user_id", "user_id"),)

    def __repr__(self) -> str:
        return f"<UserResult id={self.id} user_id={self.user_id}>"


# ── PairTestAnswer ────────────────────────────────────────────────────────────

class PairTestAnswer(Base):
    __tablename__ = "pair_test_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pair_test_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("pair_test_sessions.id", ondelete="CASCADE"), nullable=False
    )
    family_link_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("family_links.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    # waiting | partial | completed | timeout
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="waiting", server_default="waiting"
    )
    # Guards against duplicate transition triggers from concurrent handlers.
    locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    question_id: Mapped[int] = mapped_column(Integer, nullable=False)
    block_id: Mapped[int] = mapped_column(Integer, nullable=False)
    answer_value: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reminder_sent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    timeout_triggered: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    pair_session: Mapped["PairTestSession"] = relationship(
        "PairTestSession", back_populates="answers"
    )

    __table_args__ = (
        Index("ix_pair_test_answers_session_id", "pair_test_session_id"),
        Index("ix_pair_test_answers_user_id", "user_id"),
    )

    def __repr__(self) -> str:
        return f"<PairTestAnswer id={self.id} q={self.question_id} role={self.role!r}>"


# ── ObservationEntry (MVP) ───────────────────────────────────────────────────

class ObservationEntry(Base):
    __tablename__ = "observation_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    family_link_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("family_links.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    subject_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    observer_role: Mapped[str] = mapped_column(String(10), nullable=False)
    entry_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_visible_in_summary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_observation_entries_family_link_id", "family_link_id"),
        Index("ix_observation_entries_user_id", "user_id"),
        Index("ix_observation_entries_subject_user_id", "subject_user_id"),
        Index("ix_observation_entries_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<ObservationEntry id={self.id} role={self.observer_role!r} kind={self.entry_kind!r}>"


# ── PairTask (Diary MVP) ─────────────────────────────────────────────────────

class PairTask(Base):
    __tablename__ = "pair_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    family_link_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("family_links.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    invited_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    accepted_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    task_code: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="manual", server_default="manual")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending_invite", server_default="pending_invite")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_pair_tasks_family_link_id", "family_link_id"),
        Index("ix_pair_tasks_created_by_user_id", "created_by_user_id"),
        Index("ix_pair_tasks_invited_user_id", "invited_user_id"),
        Index("ix_pair_tasks_status", "status"),
        Index("ix_pair_tasks_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<PairTask id={self.id} code={self.task_code!r} status={self.status!r}>"


class PairTaskResponse(Base):
    __tablename__ = "pair_task_responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pair_task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("pair_tasks.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    question_code: Mapped[str] = mapped_column(String(64), nullable=False)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_pair_task_responses_pair_task_id", "pair_task_id"),
        Index("ix_pair_task_responses_user_id", "user_id"),
        Index("ix_pair_task_responses_role", "role"),
    )

    def __repr__(self) -> str:
        return f"<PairTaskResponse id={self.id} task_id={self.pair_task_id} role={self.role!r}>"


# ── UserActivity (Retention) ───────────────────────────────────────────────

class UserActivity(Base):
    __tablename__ = "user_activity"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    pair_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("pair_test_sessions.id", ondelete="CASCADE"), nullable=False
    )
    last_action_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_question_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reminder_stage: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    is_finished: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    reminders_sent_today: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    reminder_day: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_user_activity_user_id", "user_id"),
        Index("ix_user_activity_pair_id", "pair_id"),
        Index("ix_user_activity_pair_user", "pair_id", "user_id", unique=True),
    )

    def __repr__(self) -> str:
        return f"<UserActivity user_id={self.user_id} pair_id={self.pair_id} stage={self.reminder_stage}>"


class UserBehavior(Base):
    __tablename__ = "user_behavior"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_answer_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    avg_response_time: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_hours_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_notification_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notification_count_today: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    notification_day: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    visit_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    answer_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    return_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    completion_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    __table_args__ = (Index("ix_user_behavior_user_id", "user_id", unique=True),)

    def __repr__(self) -> str:
        return f"<UserBehavior user_id={self.user_id} avg_response_time={self.avg_response_time}>"


class UserSegment(Base):
    __tablename__ = "user_segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    segment: Mapped[str] = mapped_column(String(32), nullable=False, default="ghost", server_default="ghost")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=_now, nullable=False
    )

    __table_args__ = (Index("ix_user_segments_user_id", "user_id", unique=True),)

    def __repr__(self) -> str:
        return f"<UserSegment user_id={self.user_id} segment={self.segment!r}>"


class UserScore(Base):
    __tablename__ = "user_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    engagement_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    completion_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    return_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    consistency_score: Mapped[int] = mapped_column(Integer, nullable=False, default=5, server_default="5")
    last_calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=_now, nullable=False
    )

    __table_args__ = (Index("ix_user_scores_user_id", "user_id", unique=True),)

    def __repr__(self) -> str:
        return f"<UserScore user_id={self.user_id} score={self.score}>"


# ── PairSession (invite / pairing) ───────────────────────────────────────────

class PairSession(Base):
    """Lightweight invite record created by a teen; parent joins via deep link."""

    __tablename__ = "pair_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Telegram user IDs (not FK) — stored as BigInteger to match Telegram's id space
    teen_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # pending → active (once parent connects)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_pair_sessions_teen_id", "teen_id"),
        Index("ix_pair_sessions_parent_id", "parent_id"),
    )

    def __repr__(self) -> str:
        return f"<PairSession id={self.id} status={self.status!r}>"
