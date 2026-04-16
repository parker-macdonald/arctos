from __future__ import annotations

import os


RETRY_FINALIZATION_USER_IDS_ENV = "RETRY_FINALIZATION_USER_IDS"


def retry_finalization_allowed_user_ids() -> set[str]:
    raw = os.environ.get(RETRY_FINALIZATION_USER_IDS_ENV, "")
    return {part.strip() for part in raw.split(":") if part.strip()}


def current_user_can_retry_finalization(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    user_id = getattr(user, "id", None)
    if user_id is None:
        return False
    return str(user_id).strip() in retry_finalization_allowed_user_ids()
