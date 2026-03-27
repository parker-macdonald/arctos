"""
Public waiver-serving routes.

These routes are intentionally outside of /_api so the frontend can link to a stable URL:
  - Tournament: /<tournament_url>/waiver
  - League (canonical): /leagues/<league_url>/waiver
  - League (alias): /<league_url>/waiver redirects to the canonical route
"""

from __future__ import annotations

import os

from flask import Blueprint, redirect, send_file

from models import League, Tournament
from flask import current_app

bp = Blueprint("waivers", __name__)


def _waiver_disk_path(scope_url: str) -> str:
    # Prefer any extension variant (waiver.<ext>) and fall back to legacy extensionless file.
    base_dir = os.path.join(
        current_app.root_path,
        "../static",
        "uploads",
        "waivers",
        scope_url,
    )
    if not os.path.isdir(base_dir):
        return os.path.join(base_dir, "waiver")

    # Find deterministic candidate waiver files.
    candidates = []
    for name in os.listdir(base_dir):
        if name == "waiver" or name.startswith("waiver."):
            path = os.path.join(base_dir, name)
            if os.path.isfile(path):
                candidates.append(name)
    if not candidates:
        return os.path.join(base_dir, "waiver")

    # Prefer extension files first (better content-type), then extensionless.
    candidates.sort(key=lambda n: (0 if n.startswith("waiver.") else 1, n))
    return os.path.join(base_dir, candidates[0])


@bp.route("/leagues/<league_url>/waiver", methods=["GET"])
def league_waiver(league_url: str):
    league = League.query.filter_by(url=league_url).first()
    if not league:
        return {"error": "Not found"}, 404

    file_path = _waiver_disk_path(league_url)
    if not os.path.isfile(file_path):
        return {"error": "Waiver not found"}, 404

    return send_file(file_path, as_attachment=False)


@bp.route("/<event_url>/waiver", methods=["GET"])
def event_waiver_alias(event_url: str):
    # If the slug matches a league, redirect to the canonical league URL.
    league = League.query.filter_by(url=event_url).first()
    if league:
        return redirect(f"/leagues/{event_url}/waiver", code=302)

    tournament = Tournament.query.filter_by(url=event_url).first()
    if not tournament:
        return {"error": "Not found"}, 404

    # If this tournament belongs to a league, redirect to the league's canonical waiver.
    if getattr(tournament, "league_id", None):
        return redirect(f"/leagues/{tournament.league_id}/waiver", code=302)

    file_path = _waiver_disk_path(event_url)
    if not os.path.isfile(file_path):
        return {"error": "Waiver not found"}, 404

    return send_file(file_path, as_attachment=False)

