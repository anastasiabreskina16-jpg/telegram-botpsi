"""add pair report fields

Revision ID: 20260323_000001
Revises:
Create Date: 2026-03-23 00:00:01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260323_000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pair_test_sessions", sa.Column("ai_report", sa.Text(), nullable=True))
    op.add_column(
        "pair_test_sessions",
        sa.Column("ai_report_generated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "pair_test_sessions",
        sa.Column("phase2_report_sent", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("pair_test_sessions", "phase2_report_sent")
    op.drop_column("pair_test_sessions", "ai_report_generated")
    op.drop_column("pair_test_sessions", "ai_report")