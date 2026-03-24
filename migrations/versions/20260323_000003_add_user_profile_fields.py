"""add user profile fields

Revision ID: 20260323_000003
Revises: 20260323_000002
Create Date: 2026-03-23 00:00:03
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260323_000003"
down_revision = "20260323_000002"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns(table_name)}
    return column_name in columns


def upgrade() -> None:
    if not _has_column("users", "display_name"):
        op.add_column("users", sa.Column("display_name", sa.String(length=128), nullable=True))
    if not _has_column("users", "family_title"):
        op.add_column("users", sa.Column("family_title", sa.String(length=32), nullable=True))


def downgrade() -> None:
    if _has_column("users", "family_title"):
        op.drop_column("users", "family_title")
    if _has_column("users", "display_name"):
        op.drop_column("users", "display_name")
