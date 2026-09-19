"""convert scores to five point scale

Revision ID: f78b6ea4c216
Revises: ea39813f7c58
Create Date: 2026-09-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f78b6ea4c216'
down_revision: Union[str, Sequence[str], None] = 'ea39813f7c58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # widen first so the halved values fit during conversion
    op.alter_column(
        "ratings",
        "score",
        existing_type=sa.Integer(),
        type_=sa.Numeric(4, 1),
        existing_nullable=False,
        postgresql_using="score::numeric(4,1)",
    )
    # 10 -> 5.0, 9 -> 4.5, 7 -> 3.5, and so on
    op.execute("UPDATE ratings SET score = ROUND((score / 2.0) * 2) / 2")
    op.execute("UPDATE ratings SET score = 0.5 WHERE score < 0.5")
    op.execute("UPDATE ratings SET score = 5.0 WHERE score > 5.0")
    # now narrow to the final shape
    op.alter_column(
        "ratings",
        "score",
        existing_type=sa.Numeric(4, 1),
        type_=sa.Numeric(2, 1),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "ratings",
        "score",
        existing_type=sa.Numeric(2, 1),
        type_=sa.Numeric(4, 1),
        existing_nullable=False,
    )
    op.execute("UPDATE ratings SET score = ROUND(score * 2)")
    op.alter_column(
        "ratings",
        "score",
        existing_type=sa.Numeric(4, 1),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="score::integer",
    )
