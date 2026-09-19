"""add invite code

Revision ID: 70bf4f1989cb
Revises: f78b6ea4c216
Create Date: 2026-09-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '70bf4f1989cb'
down_revision: Union[str, Sequence[str], None] = 'f78b6ea4c216'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("invite_code", sa.String(length=16), nullable=True))
    op.create_unique_constraint("uq_users_invite_code", "users", ["invite_code"])


def downgrade() -> None:
    op.drop_constraint("uq_users_invite_code", "users", type_="unique")
    op.drop_column("users", "invite_code")
