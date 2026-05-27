"""Add description and registration_open columns to sidecomps.

Adds two new columns to the ``sidecomps`` table:

- ``description``: optional free-form text describing the side competition.
- ``registration_open``: boolean gate for player self-registration. Defaults
  to ``False`` so existing comps remain closed to self-registration until a
  TO explicitly opens them. TO check-in is unaffected by this flag.

Both changes are additive; existing rows are unaffected.

Revision ID: 0005_sidecomp_open_close_description
Revises: 0004_sidecomp_registrations
Create Date: 2026-05-06
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0005_sidecomp_open_close_description"
down_revision: Union[str, Sequence[str], None] = "0004_sidecomp_registrations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    if is_sqlite:
        bind.exec_driver_sql("PRAGMA foreign_keys = OFF")
    try:
        with op.batch_alter_table("sidecomps") as batch:
            batch.add_column(sa.Column("description", sa.Text(), nullable=True))
            batch.add_column(
                sa.Column(
                    "registration_open",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("0"),
                )
            )
    finally:
        if is_sqlite:
            bind.exec_driver_sql("PRAGMA foreign_keys = ON")


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    if is_sqlite:
        bind.exec_driver_sql("PRAGMA foreign_keys = OFF")
    try:
        with op.batch_alter_table("sidecomps") as batch:
            batch.drop_column("registration_open")
            batch.drop_column("description")
    finally:
        if is_sqlite:
            bind.exec_driver_sql("PRAGMA foreign_keys = ON")
