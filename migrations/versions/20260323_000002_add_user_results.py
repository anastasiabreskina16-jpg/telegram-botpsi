"""add user_results table

Revision ID: 20260323_000002
Revises: 20260323_000001
Create Date: 2026-03-23 00:00:02
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260323_000002"
down_revision = "20260323_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("pair_session_id", sa.Integer(), nullable=True),
        sa.Column("teen_scores", sa.JSON(), nullable=True),
        sa.Column("parent_scores", sa.JSON(), nullable=True),
        sa.Column("diff", sa.JSON(), nullable=True),
        sa.Column("ai_report", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_user_results_user_id", "user_results", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_results_user_id", table_name="user_results")
    op.drop_table("user_results")
