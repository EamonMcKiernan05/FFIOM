"""add is_admin to users

Revision ID: 01ac1b46405a
Revises: f3a1c9d2e4b5
Create Date: 2026-07-25 22:56:57.016446

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '01ac1b46405a'
down_revision: Union[str, None] = 'f3a1c9d2e4b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('is_admin', sa.Boolean(), nullable=True, server_default='0'))


def downgrade() -> None:
    op.drop_column('users', 'is_admin')
