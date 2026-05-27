"""Add optional shortname column to team_registrations.

Revision ID: 0008_team_registration_shortname
Revises: 0007_add_pending_team_registration_status
Create Date: 2026-05-13
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0008_team_registration_shortname"
down_revision: Union[str, Sequence[str], None] = "0007_add_pending_team_registration_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "team_registrations",
        sa.Column("shortname", sa.String(length=12), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("team_registrations", "shortname")
