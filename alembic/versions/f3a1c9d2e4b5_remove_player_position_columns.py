"""remove player position columns

Removes unreliable player position data entirely:
- players.position
- dream_team_players.position

Revision ID: f3a1c9d2e4b5
Revises: e82504a432d4
Create Date: 2026-07-24 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3a1c9d2e4b5"
down_revision: Union[str, None] = "e82504a432d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_players_position", table_name="players")
    op.drop_column("players", "position")
    op.drop_column("dream_team_players", "position")


def downgrade() -> None:
    op.add_column("dream_team_players", sa.Column("position", sa.String(3), nullable=True))
    op.add_column("players", sa.Column("position", sa.String(3), nullable=True))
    op.create_index("ix_players_position", "players", ["position"])
