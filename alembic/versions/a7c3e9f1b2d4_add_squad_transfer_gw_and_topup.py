"""add squad transfer-in gameweek + budget top-up columns

Tracks which gameweek a player was transferred into a user's squad and the
cumulative budget top-up already credited for that player's price rises, so
the +0.1m-per-0.2m-rise budget mechanic can be applied idempotently each GW.

Revision ID: a7c3e9f1b2d4
Revises: f3a1c9d2e4b5
Create Date: 2026-08-18 00:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7c3e9f1b2d4"
down_revision: Union[str, None] = "f3a1c9d2e4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "squad_players",
        sa.Column("transferred_in_gw", sa.Integer(), nullable=True),
    )
    op.add_column(
        "squad_players",
        sa.Column("budget_topup_awarded", sa.Float(), nullable=True, server_default="0.0"),
    )


def downgrade() -> None:
    op.drop_column("squad_players", "budget_topup_awarded")
    op.drop_column("squad_players", "transferred_in_gw")
