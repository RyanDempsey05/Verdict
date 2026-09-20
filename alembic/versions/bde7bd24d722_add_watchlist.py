"""add watchlist

Revision ID: bde7bd24d722
Revises: 2c2e9b7ecc89
Create Date: 2026-09-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'bde7bd24d722'
down_revision: Union[str, Sequence[str], None] = '2c2e9b7ecc89'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "watchlist_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "item_id", name="uq_watchlist_user_item"),
    )
    op.create_index("ix_watchlist_entries_user_id", "watchlist_entries", ["user_id"])
    op.create_index("ix_watchlist_entries_item_id", "watchlist_entries", ["item_id"])


def downgrade() -> None:
    op.drop_index("ix_watchlist_entries_item_id", table_name="watchlist_entries")
    op.drop_index("ix_watchlist_entries_user_id", table_name="watchlist_entries")
    op.drop_table("watchlist_entries")
