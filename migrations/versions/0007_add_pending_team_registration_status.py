"""Add PENDING to TeamRegistrationStatus enum.

PENDING is a transient state used by the registration cap-enforcement
savepoint pattern. No row is committed in PENDING state at rest, but
the column's CHECK constraint must allow the value.

Revision ID: 0007_add_pending_team_registration_status
Revises: 0006_sidecomp_entry_number
Create Date: 2026-05-07
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0007_add_pending_team_registration_status"
down_revision: Union[str, Sequence[str], None] = "0006_sidecomp_entry_number"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    if is_sqlite:
        bind.exec_driver_sql("PRAGMA foreign_keys = OFF")
    try:
        new_enum = sa.Enum(
            "CONFIRMED",
            "CANCELLED",
            "PENDING",
            name="teamregistrationstatus",
        )
        with op.batch_alter_table("team_registrations") as batch:
            batch.alter_column("status", existing_type=sa.String(), type_=new_enum)
    finally:
        if is_sqlite:
            bind.exec_driver_sql("PRAGMA foreign_keys = ON")


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    if is_sqlite:
        bind.exec_driver_sql("PRAGMA foreign_keys = OFF")
    try:
        old_enum = sa.Enum(
            "CONFIRMED",
            "CANCELLED",
            name="teamregistrationstatus",
        )
        with op.batch_alter_table("team_registrations") as batch:
            batch.alter_column("status", existing_type=sa.String(), type_=old_enum)
    finally:
        if is_sqlite:
            bind.exec_driver_sql("PRAGMA foreign_keys = ON")
