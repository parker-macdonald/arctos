"""Rename Tournament.is_day_event to organizer_checkin_enabled.

Revision ID: 0005_rename_is_day_event
Revises: 0004_add_is_day_event
Create Date: 2026-05-06
"""

from alembic import op


revision = "0005_rename_is_day_event"
down_revision = "0004_add_is_day_event"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    if is_sqlite:
        bind.exec_driver_sql("PRAGMA foreign_keys = OFF")
    try:
        with op.batch_alter_table("tournaments") as batch_op:
            batch_op.alter_column("is_day_event", new_column_name="organizer_checkin_enabled")
    finally:
        if is_sqlite:
            bind.exec_driver_sql("PRAGMA foreign_keys = ON")


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    if is_sqlite:
        bind.exec_driver_sql("PRAGMA foreign_keys = OFF")
    try:
        with op.batch_alter_table("tournaments") as batch_op:
            batch_op.alter_column("organizer_checkin_enabled", new_column_name="is_day_event")
    finally:
        if is_sqlite:
            bind.exec_driver_sql("PRAGMA foreign_keys = ON")
