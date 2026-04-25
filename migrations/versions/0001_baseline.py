"""Baseline — declare the current schema as the alembic starting point.

This revision is intentionally a no-op. It exists so that an existing
Arctos database (created historically via ``db.create_all()``) can be
brought under Alembic management with::

    uv run alembic stamp head

after which every subsequent schema change is shipped as a real, versioned
migration on top of this baseline.

Why an empty migration instead of generating a full ``CREATE TABLE`` script
for the existing schema?

* Production databases already contain the schema; running a generated
  ``CREATE TABLE`` upgrade against them would error out.
* The existing schema is documented by the SQLAlchemy models themselves
  (``app/models/``), which are the source of truth for ``--autogenerate``
  diffs going forward.
* New empty databases (CI, fresh dev clones) are still bootstrapped by the
  application's start-up ``db.create_all()`` call; Alembic is layered on
  top of that bootstrap, not in place of it.

After this baseline, the workflow is:

1. ``make db-baseline`` (one-shot per database) stamps this revision.
2. Edit ``app/models/*`` to declare the new schema.
3. ``make db-revision MSG="describe_change"`` autogenerates a migration.
4. Review the generated file, write a real docstring describing *why* the
   change is being made, then ``make db-migrate``.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-04-24
"""

from __future__ import annotations

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op: see module docstring."""
    pass


def downgrade() -> None:
    """No-op: cannot downgrade past the initial baseline."""
    pass
