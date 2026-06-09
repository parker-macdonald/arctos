"""Add scheduled_start_time column to matches.

Backfilled from ``nominal_start_time`` so the ``scheduled_start_time`` becomes
the stable anchor used by time-based dependency edges, while
``nominal_start_time`` continues to be the dynamically-recomputed value.

Revision ID: 0009_match_scheduled_start_time
Revises: 0008_team_registration_shortname
Create Date: 2026-06-08
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0009_match_scheduled_start_time"
down_revision: Union[str, Sequence[str], None] = "0008_team_registration_shortname"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "matches",
        sa.Column("scheduled_start_time", sa.DateTime(), nullable=True),
    )
    op.execute("UPDATE matches SET scheduled_start_time = nominal_start_time")


def downgrade() -> None:
    op.drop_column("matches", "scheduled_start_time")
