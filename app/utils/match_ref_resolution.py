"""
Resolve match team/ref slots for API and import paths.

Invariant: `refs` and `refs_initial` use the same number of comma-separated slots.
Each slot stores a resolved team id (or empty if unresolved) in `refs` and the
display/user token in `refs_initial` (see force_start_match_api pattern).
"""

from __future__ import annotations

from app.utils.helpers import (
    resolve_match_winner_loser_ref,
    resolve_tag_to_team,
    resolve_team_name_to_id,
)


def is_explicit_team_id(val: str) -> bool:
    """Return ``True`` if *val* is a bare team ID rather than a symbolic reference.

    Symbolic references (``tag::<name>`` and strings containing ``::winner``
    or ``::loser``) return ``False``.

    Args:
        val: A team slot string from the schedule or API.

    Returns:
        ``True`` when *val* is a non-empty, non-reference team ID.
    """
    if not val or not val.strip():
        return False
    val = val.strip()
    if val.lower().startswith("tag::"):
        return False
    if "::winner" in val.lower() or "::loser" in val.lower():
        return False
    return True


def resolve_single_ref_slot(r_str: str, tournament_url: str) -> tuple[str, str]:
    """Resolve a single referee slot string to a team ID and display token.

    Resolution order:

    1. Registered pseudonym / team ID lookup via :func:`~app.utils.helpers.resolve_team_name_to_id`.
    2. Bare team ID (explicit) — returned as-is.
    3. Tag reference (``tag::<name>``) — resolved via :func:`~app.utils.helpers.resolve_tag_to_team`.

    Args:
        r_str: A single comma-slot string from ``refs`` / ``refs_initial``.
        tournament_url: Tournament URL slug for resolution context.

    Returns:
        A ``(resolved_team_id, initial_display_token)`` tuple.  *resolved_team_id*
        is empty when resolution fails; *initial_display_token* is always the
        original user-facing string.
    """
    r_str = (r_str or "").strip()
    if not r_str:
        return "", ""

    # MatchName::winner / ::loser — resolves to a team id when the referenced
    # match is already decided; otherwise stays empty and gets filled in later
    # by apply_match_dependencies. The display token always preserves the
    # user-typed reference text.
    winner_loser = resolve_match_winner_loser_ref(r_str, tournament_url)
    if winner_loser is not None or "::winner" in r_str.lower() or "::loser" in r_str.lower():
        return (winner_loser or ""), r_str

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
    """Resolve a ``team1`` / ``team2`` slot token to a team ID and display text.

    Args:
        raw: The raw token from the SPA request or TOML file, or ``None``.
        tournament_url: Tournament URL slug for resolution context.

    Returns:
        A ``(resolved_team_id, initial_display_token)`` tuple.  Both values
        are ``None`` when *raw* is empty.
    """
    raw_str = str(raw).strip() if raw is not None else ""
    if not raw_str:
        return None, None

    # Match::winner / ::loser — fill in the cached team id when the referenced
    # match has a winner; otherwise leave the cache empty and let
    # apply_match_dependencies fill it in later. Display token is always the
    # original reference text.
    winner_loser = resolve_match_winner_loser_ref(raw_str, tournament_url)
    if winner_loser is not None:
        return winner_loser, raw_str
    if "::winner" in raw_str.lower() or "::loser" in raw_str.lower():
        return None, raw_str

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
    """Resolve a ``team1`` / ``team2`` initial token to a team ID.

    Convenience wrapper around :func:`resolve_team_slot` that discards the
    display token.

    Resolution order: confirmed registration (pseudonym / ID), explicit bare
    ID, ``tag::`` reference.

    Args:
        raw: Raw token from the SPA or TOML schedule, or ``None``.
        tournament_url: Tournament URL slug for resolution context.

    Returns:
        Resolved team ID string, or ``None`` if the token cannot be resolved.
    """
    resolved, _ = resolve_team_slot(raw, tournament_url)
    return resolved


def refs_string_to_tokens(refs_value: str | None) -> list[str]:
    """Split a comma-separated refs string into per-slot tokens.

    Unlike a simple ``str.split(",")``, this function trims whitespace and
    returns an empty list for falsy / blank input.  Empty slots between
    commas are preserved as empty strings.

    Args:
        refs_value: A comma-separated refs string from a form field or API,
            or ``None``.

    Returns:
        List of stripped slot tokens, possibly containing empty strings.
    """
    if not refs_value or not str(refs_value).strip():
        return []
    return [p.strip() for p in str(refs_value).split(",")]
