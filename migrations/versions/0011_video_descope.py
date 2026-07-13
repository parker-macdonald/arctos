"""Video descope: drop unused livestream capture columns.

Removes the field-level livestream camera column and the per-point stream
offset columns that only the removed livestream/recording capture path
wrote. Existing footage playback does not depend on these: match-scoped
cameras and their ``camera_timepoints`` anchors, ``matches.camera_stream_starts``,
and ``points.footage`` are all retained.

Revision ID: 0011_video_descope
Revises: 0010_normalize_match_names
Create Date: 2026-07-13
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0011_video_descope"
down_revision: Union[str, Sequence[str], None] = "0010_normalize_match_names"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("fields") as batch:
        batch.drop_column("camera")
    with op.batch_alter_table("points") as batch:
        batch.drop_column("camera_index")
        batch.drop_column("stream_timestamp")


def downgrade() -> None:
    with op.batch_alter_table("points") as batch:
        batch.add_column(sa.Column("stream_timestamp", sa.Float(), nullable=True))
        batch.add_column(sa.Column("camera_index", sa.Integer(), nullable=True))
    with op.batch_alter_table("fields") as batch:
        batch.add_column(sa.Column("camera", sa.Text(), nullable=True))
