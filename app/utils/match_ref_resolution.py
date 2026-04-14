"""
Resolve match team/ref slots for API and import paths.

Invariant: `refs` and `refs_initial` use the same number of comma-separated slots.
Each slot stores a resolved team id (or empty if unresolved) in `refs` and the
display/user token in `refs_initial` (see force_start_match_api pattern).
"""

from __future__ import annotations

from app.utils.helpers import resolve_tag_to_team, resolve_team_name_to_id


def is_explicit_team_id(val: str) -> bool:
    """True if val looks like a bare team id, not a tag or match reference."""
    if not val or not val.strip():
        return False
    val = val.strip()
    if val.lower().startswith("tag::"):
        return False
    if "::winner" in val.lower() or "::loser" in val.lower():
        return False
    return True


def resolve_single_ref_slot(r_str: str, tournament_url: str) -> tuple[str, str]:
    """
    Resolve one refs column slot.

    Returns:
        (resolved_team_id_or_empty, initial_display_token)
    """
    r_str = (r_str or "").strip()
    if not r_str:
        return "", ""

    rid, rinit = resolve_team_name_to_id(r_str, tournament_url)
    # Preserve user/SPA token when registration resolves (rid, None).
    initial = rinit if rinit is not None else r_str

    resolved = ""
    if rid:
        resolved = rid
    elif is_explicit_team_id(r_str):
        resolved = r_str
    else:
        rt = resolve_tag_to_team(r_str, tournament_url)
        if rt:
            resolved = rt

    return resolved, initial


def resolve_team_slot(
    raw: str | None,
    tournament_url: str,
) -> tuple[str | None, str | None]:
    """
    Resolve one team column token while preserving the original token as initial text.

    Returns:
        (resolved_team_id_or_none, initial_display_token_or_none)
    """
    raw_str = str(raw).strip() if raw is not None else ""
    if not raw_str:
        return None, None

    team_id, _ = resolve_team_name_to_id(raw_str, tournament_url)
    if team_id:
        return team_id, raw_str
    if is_explicit_team_id(raw_str):
        return raw_str, raw_str

    resolved_tag = resolve_tag_to_team(raw_str, tournament_url)
    if resolved_tag:
        return resolved_tag, raw_str

    return None, raw_str


def resolve_refs_slots(
    tokens: list,
    tournament_url: str,
) -> tuple[str | None, str | None]:
    """
    Build parallel `refs` and `refs_initial` comma-separated strings.

    Args:
        tokens: List of per-slot strings (e.g. from JSON or split form field).
        tournament_url: Event url for resolution.

    Returns:
        (refs_csv, refs_initial_csv) or (None, None) if there are no slots.
    """
    if not tokens:
        return None, None

    ref_parts: list[str] = []
    init_parts: list[str] = []
    for r in tokens:
        r_str = str(r).strip() if r is not None else ""
        res, init = resolve_single_ref_slot(r_str, tournament_url)
        ref_parts.append(res)
        init_parts.append(init)

    refs_joined = ",".join(ref_parts)
    inits_joined = ",".join(init_parts)

    # No meaningful content
    if not any(p.strip() for p in init_parts) and not any(p.strip() for p in ref_parts):
        return None, None

    return refs_joined, inits_joined


def resolve_team_column(raw: str | None, tournament_url: str) -> str | None:
    """
    Resolve team1/team2 from an initial token (SPA / TOML).

    Order: confirmed registration (pseudonym/id), explicit bare id, tag:: resolution.
    """
    resolved, _ = resolve_team_slot(raw, tournament_url)
    return resolved


def refs_string_to_tokens(refs_value: str | None) -> list[str]:
    """Split a refs form/API string into trimmed slot tokens (empty slots preserved)."""
    if not refs_value or not str(refs_value).strip():
        return []
    return [p.strip() for p in str(refs_value).split(",")]
