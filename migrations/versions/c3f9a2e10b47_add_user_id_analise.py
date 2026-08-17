"""add_user_id_analise

Revision ID: c3f9a2e10b47
Revises: 6ebaf5eccbf7
Create Date: 2026-08-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3f9a2e10b47'
down_revision: Union[str, Sequence[str], None] = '6ebaf5eccbf7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('analises_financeiras', sa.Column('user_id', sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column('analises_financeiras', 'user_id')
