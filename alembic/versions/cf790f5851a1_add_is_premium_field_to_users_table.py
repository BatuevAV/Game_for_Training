"""Add is_premium field to users table

Revision ID: cf790f5851a1
Revises: 75869715e493
Create Date: 2025-12-11 12:53:04.360615

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cf790f5851a1'
down_revision: Union[str, Sequence[str], None] = '75869715e493'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Добавляем поле is_premium в таблицу users
    op.add_column('users', sa.Column('is_premium', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    """Downgrade schema."""
    # Удаляем поле is_premium из таблицы users
    op.drop_column('users', 'is_premium')
