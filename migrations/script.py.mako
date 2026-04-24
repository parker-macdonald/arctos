"""${message}

REPLACE THIS PLACEHOLDER with a paragraph (>=20 chars) explaining WHY this
migration exists, not just what SQL it runs. A docstring like
"Add headref_allowlist table" is insufficient; prefer something like
"Normalise Tournament.head_refs_allowed_list (comma-separated player IDs)
into a proper join table with FK enforcement and a unique constraint."

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, Sequence[str], None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
