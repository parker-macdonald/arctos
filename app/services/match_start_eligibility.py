"""
Match start eligibility: single source of truth for "can start" and blocking reasons.

Used by match detail API, start-match GET/POST, and MatchService.start_match.
"""

from __future__ import annotations

from typing import List, Tuple

from app.domain.enums import MatchStatus, RegistrationStatus, ScheduleType
from app.utils.helpers import can_head_ref_match


def get_allowed_refs_display(tournament_url: str, match=None) -> Tuple[str, List[str]]:
    """
    Return (label, list of ref identifiers or descriptions) for display in block reasons.

    Returns:
        (label, items) e.g. ("Explicit list", ["player1", "player2"]) or
        ("Reffing teams for this match", ["team-a", "team-b"]) or
        ("All registered players", []) when allow_anyone (list can be long, so empty or summary).
    """
    from models import Tournament, PlayerRegistration

    tournament = Tournament.query.get(tournament_url)
    if not tournament:
        return "Unknown", []

    if tournament.head_refs_allowed_list:
        allowed_list = [
            ref.strip()
            for ref in tournament.head_refs_allowed_list.split(",")
            if ref.strip()
        ]
        return "Explicit list", allowed_list

    if tournament.head_refs_allow_reffing_teams and match and match.refs:
        ref_teams = [t.strip() for t in match.refs.split(",") if t.strip()]
        return "Reffing teams for this match", ref_teams

    if tournament.head_refs_allow_anyone:
        return "All registered players", []

    return "None configured", []


def _get_user_display(tournament_url: str, user) -> Tuple[str, str]:
    """Return (username, team_id or empty string) for the user."""
    if user is None:
        return "Unknown", ""
    user_id = getattr(user, "id", None) or getattr(user, "player", None)
    if not user_id:
        return "Unknown", ""
    from models import Player, PlayerRegistration

    player = Player.query.get(user_id) if hasattr(Player, "query") else None
    if not player:
        return str(user_id), ""
    name = getattr(player, "name", None) or user_id
    reg = (
        PlayerRegistration.query.filter_by(
            event=tournament_url,
            player=user_id,
            status=RegistrationStatus.CONFIRMED,
        ).first()
        if tournament_url
        else None
    )
    team_id = getattr(reg, "team", None) or ""
    return name, team_id or ""


def _reason_field_busy(tournament_url: str, match) -> str | None:
    """If another match is IN_PROGRESS on same field, return reason string; else None."""
    from models import Match, Tag

    field = getattr(match, "field", None)
    if not field or not str(field).strip():
        return None
    other = (
        Match.query.filter_by(
            event=tournament_url,
            field=field,
            status=MatchStatus.IN_PROGRESS,
        )
        .filter(Match.uuid != match.uuid)
        .first()
    )
    if not other:
        return None
    return f"Another match is in progress on this field: {getattr(other, 'name', other.uuid)}."


def _reasons_teams_refs(match) -> List[str]:
    """Reasons for teams or refs not resolved."""
    reasons = []
    if not getattr(match, "team1", None) or not getattr(match, "team2", None):
        reasons.append("Teams not yet determined.")
    refs_initial = (getattr(match, "refs_initial", None) or "").strip()
    if refs_initial:
        refs = (getattr(match, "refs", None) or "").split(",")
        refs_initial_list = [r.strip() for r in refs_initial.split(",")]
        if len(refs) != len(refs_initial_list) or any(not r.strip() for r in refs):
            reasons.append("Ref teams not yet available.")
    return reasons


def _reasons_status_and_deps(tournament_url: str, match) -> List[str]:
    """Reasons when status is NOT_STARTED or TIME_FINALIZED (deps, previous, tags)."""
    from app.utils.scheduling import get_match_dependencies
    from models import Match, Tag

    reasons = []
    status = getattr(match, "status", None)
    if status not in (MatchStatus.NOT_STARTED, MatchStatus.TIME_FINALIZED):
        return reasons

    # Previous match not completed
    prev_uuid = getattr(match, "previous_match", None)
    if prev_uuid:
        prev = Match.query.filter_by(uuid=prev_uuid, event=tournament_url).first()
        if prev and prev.status not in (MatchStatus.COMPLETED, MatchStatus.SKIPPED):
            reasons.append(
                f"Previous match '{getattr(prev, 'name', prev_uuid)}' is not completed."
            )

    # Schedule dependencies not completed
    if getattr(match, "schedule_type", None) != ScheduleType.STATIC:
        try:
            deps = get_match_dependencies(match, tournament_url)
        except Exception:
            deps = []
        if deps:
            not_finished = [
                d for d in deps if d.status not in (MatchStatus.COMPLETED, MatchStatus.SKIPPED)
            ]
            if not_finished and not (getattr(match, "ready_to_start", False)):
                names = [getattr(d, "name", d.uuid) for d in not_finished]
                reasons.append(
                    f"Dependency match(es) not completed: {', '.join(names)}."
                )

    # Tags/refs not set (unresolved team1_initial, team2_initial, refs_initial)
    for attr, label in [
        ("team1_initial", "Team 1"),
        ("team2_initial", "Team 2"),
    ]:
        initial = getattr(match, attr, None) or ""
        initial = (initial or "").strip()
        if not initial:
            continue
        if initial.lower().startswith("tag::"):
            tag_name = initial[5:].strip()
            tag = Tag.query.filter_by(event=tournament_url, name=tag_name).first()
            if not tag or not getattr(tag, "team", None):
                reasons.append(f"{label} is set by tag '{tag_name}', which is not yet assigned.")
        elif "::winner" in initial or "::loser" in initial:
            base = initial.split("::")[0].strip()
            dep = Match.query.filter_by(name=base, event=tournament_url).first()
            if not dep or getattr(dep, "match_winner", None) is None:
                reasons.append(f"{label} depends on match '{base}', which is not yet completed.")

    refs_initial = (getattr(match, "refs_initial", None) or "").strip()
    if refs_initial:
        refs_list = [r.strip() for r in refs_initial.split(",")]
        refs_current = (getattr(match, "refs", None) or "").split(",")
        if len(refs_current) != len(refs_list):
            reasons.append("Ref slots not yet resolved.")
        else:
            for i, initial in enumerate(refs_list):
                if not initial:
                    continue
                current = refs_current[i].strip() if i < len(refs_current) else ""
                if current:
                    continue
                if initial.lower().startswith("tag::"):
                    tag_name = initial[5:].strip()
                    tag = Tag.query.filter_by(event=tournament_url, name=tag_name).first()
                    if not tag or not getattr(tag, "team", None):
                        reasons.append(
                            f"Ref slot {i + 1} is set by tag '{tag_name}', which is not yet assigned."
                        )
                elif "::winner" in initial or "::loser" in initial:
                    base = initial.split("::")[0].strip()
                    dep = Match.query.filter_by(name=base, event=tournament_url).first()
                    if not dep or getattr(dep, "match_winner", None) is None:
                        reasons.append(
                            f"Ref slot {i + 1} depends on match '{base}', which is not yet completed."
                        )

    return reasons


def get_can_start_and_reasons(
    tournament_url: str, match, user
) -> Tuple[bool, List[str]]:
    """
    Single source of truth: can the given user start this match, and why not if not?

    Returns:
        (can_start, block_reasons). block_reasons is empty when can_start is True.
    """
    reasons: List[str] = []

    # Match already done: no need to "start"
    status = getattr(match, "status", None)
    if status in (MatchStatus.COMPLETED, MatchStatus.SKIPPED):
        return False, []  # No reasons to show; match is over

    # User must be a player (we only support player as ref)
    from app.utils.user_helpers import is_player

    if not user or not is_player(user):
        reasons.append("You must be logged in as a player to start matches.")
        return False, reasons

    user_id = getattr(user, "id", None)
    if not user_id:
        reasons.append("Could not determine your user.")
        return False, reasons

    # 1) User perms: must be allowed to head ref
    if not can_head_ref_match(tournament_url, user_id, match=match):
        username, team_id = _get_user_display(tournament_url, user)
        team_part = f" (registered with team {team_id})" if team_id else ""
        label, allowed = get_allowed_refs_display(tournament_url, match)
        if allowed:
            allowed_str = ", ".join(allowed[:10])
            if len(allowed) > 10:
                allowed_str += f", ... ({len(allowed)} total)"
        else:
            allowed_str = label
        reasons.append(
            f"User {username}{team_part} is not a ref. Allowed refs: {label} — {allowed_str}."
        )
        return False, reasons

    # 2) Field busy: no other match IN_PROGRESS on same field
    field_reason = _reason_field_busy(tournament_url, match)
    if field_reason:
        reasons.append(field_reason)
        return False, reasons

    # 3) Status must be READY_TO_START
    if status != MatchStatus.READY_TO_START:
        if status in (MatchStatus.NOT_STARTED, MatchStatus.TIME_FINALIZED):
            reasons.extend(_reasons_status_and_deps(tournament_url, match))
            if not reasons:
                reasons.append("Schedule or dependencies not yet finalized.")
        else:
            reasons.append(f"Match status is {status}, not READY_TO_START.")
        return False, reasons

    # 4) Teams and refs must be resolved
    team_ref_reasons = _reasons_teams_refs(match)
    if team_ref_reasons:
        reasons.extend(team_ref_reasons)
        return False, reasons

    return True, []
