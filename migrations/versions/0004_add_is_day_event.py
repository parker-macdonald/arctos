"""Add is_day_event flag to tournaments.

Adds a boolean column that opts a tournament into the day-event sign-in
flow. Existing rows backfill to ``False`` via the server default.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_add_is_day_event"
down_revision: Union[str, Sequence[str], None] = "0003_phase4_cleanup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("tournaments") as batch:
        batch.add_column(
            sa.Column(
                "is_day_event",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("tournaments") as batch:
        batch.drop_column("is_day_event")
