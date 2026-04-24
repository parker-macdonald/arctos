"""Utilities for controlling which users may retry failed recording finalisation."""

from __future__ import annotations

import os


#: Environment variable name containing a colon-separated list of user IDs
#: that are permitted to trigger recording re-finalisation.
RETRY_FINALIZATION_USER_IDS_ENV = "RETRY_FINALIZATION_USER_IDS"


def retry_finalization_allowed_user_ids() -> set[str]:
    """Return the set of user IDs permitted to retry recording finalisation.

    Reads the colon-separated ``RETRY_FINALIZATION_USER_IDS`` environment
    variable.

    Returns:
        Set of stripped, non-empty user ID strings.
    """
    raw = os.environ.get(RETRY_FINALIZATION_USER_IDS_ENV, "")
    return {part.strip() for part in raw.split(":") if part.strip()}


def current_user_can_retry_finalization(user) -> bool:
    """Return whether the current user is allowed to retry recording finalisation.

    Args:
        user: A Flask-Login user object, or ``None``.

    Returns:
        ``True`` if the user is authenticated and their ID appears in the
        :data:`RETRY_FINALIZATION_USER_IDS_ENV` allowlist.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False
    user_id = getattr(user, "id", None)
    if user_id is None:
        return False
    return str(user_id).strip() in retry_finalization_allowed_user_ids()
