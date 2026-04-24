"""Schema-level tests for the additive Phase 1 changes.

These tests exercise the constraints added by the additive schema migration
through the live ORM models, verifying that:

* The six normalised join tables exist and accept valid rows.
* Their UNIQUE constraints reject duplicate (parent, child) pairs.
* Their FOREIGN KEY columns are enforced.
* The mutual-exclusivity CHECKs on TeamRegistration / PlayerRegistration / TO
  reject "both set" and "both NULL" rows.
* The new email-uniqueness constraints reject duplicates but allow multiple
  NULLs (SQL-standard ``UNIQUE`` semantics).
* The monetary type change preserves exact decimal values through the ORM.

The tests use the in-process test database fixture (``test_db``) which calls
``db.create_all()`` against the current model metadata — so what is being
verified here is that the *models* declare the right constraints, which the
alembic migration mirrors. The migration itself is smoke-tested separately
during development by running ``alembic upgrade head`` against a fresh DB.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import sqlalchemy as sa

from app.domain.enums import TeamRegistrationStatus, WinnerSide
from models import (
    TO,
    CameraTimepoint,
    FieldCamera,
    HeadRefAllowList,
    MatchCameraStreamStart,
    MatchPlayer,
    MatchReferee,
    PlayerRegistration,
    Team,
    TeamRegistration,
    db,
)


# ---------------------------------------------------------------------------
# Normalised tables — happy path: rows insert and round-trip through the ORM.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_headref_allowlist_round_trips(test_db, tournament, head_ref_player):
    """HeadRefAllowList accepts a valid (event, player_id) pair and round-trips."""
    db.session.add(HeadRefAllowList(event=tournament.url, player_id=head_ref_player.id))
    db.session.commit()
    row = HeadRefAllowList.query.filter_by(event=tournament.url, player_id=head_ref_player.id).one()
    assert row.event == tournament.url
    assert row.player_id == head_ref_player.id


@pytest.mark.unit
def test_headref_allowlist_rejects_duplicate(test_db, tournament, head_ref_player):
    """Two HeadRefAllowList rows with the same (event, player_id) raise IntegrityError."""
    db.session.add(HeadRefAllowList(event=tournament.url, player_id=head_ref_player.id))
    db.session.commit()
    db.session.add(HeadRefAllowList(event=tournament.url, player_id=head_ref_player.id))
    with pytest.raises(sa.exc.IntegrityError):
        db.session.commit()
    db.session.rollback()


@pytest.mark.unit
def test_headref_allowlist_rejects_orphan_player(test_db, tournament):
    """HeadRefAllowList.player_id has FK enforcement — bogus IDs are rejected."""
    db.session.add(HeadRefAllowList(event=tournament.url, player_id="ghost_player"))
    with pytest.raises(sa.exc.IntegrityError):
        db.session.commit()
    db.session.rollback()


# ---------------------------------------------------------------------------
# match_referees / match_players — exercise the slot/side invariants.
# ---------------------------------------------------------------------------


def _make_match(test_db, tournament_url, name="M"):
    """Helper: build a minimal Match row and flush so its uuid is available."""
    from models import Match

    m = Match(
        name=name,
        event=tournament_url,
        schedule_type="STATIC",
        set_type="SETS",
        nominal_length=60,
    )
    db.session.add(m)
    db.session.flush()
    return m


@pytest.mark.unit
def test_match_referees_unique_per_slot(test_db, tournament, seeded_teams):
    """Two MatchReferee rows on the same (match_uuid, slot) raise IntegrityError."""
    m = _make_match(test_db, tournament.url)
    db.session.add(MatchReferee(match_uuid=m.uuid, slot=0, team_id="team1", initial="team1"))
    db.session.commit()
    db.session.add(MatchReferee(match_uuid=m.uuid, slot=0, team_id="team2", initial="team2"))
    with pytest.raises(sa.exc.IntegrityError):
        db.session.commit()
    db.session.rollback()


@pytest.mark.unit
def test_match_players_unique_per_player(test_db, tournament, player, seeded_teams):
    """A single MatchPlayer per (match_uuid, player_id) — the same player on both sides is rejected."""
    m = _make_match(test_db, tournament.url)
    db.session.add(MatchPlayer(match_uuid=m.uuid, player_id=player.id, side=WinnerSide.TEAM1))
    db.session.commit()
    db.session.add(MatchPlayer(match_uuid=m.uuid, player_id=player.id, side=WinnerSide.TEAM2))
    with pytest.raises(sa.exc.IntegrityError):
        db.session.commit()
    db.session.rollback()


# ---------------------------------------------------------------------------
# field_cameras / match_camera_stream_starts / camera_timepoints — slot/seq
# invariants.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_field_cameras_unique_per_slot(test_db, tournament):
    """FieldCamera enforces UNIQUE(field_id, slot)."""
    from models import Field

    field = Field.query.filter_by(event=tournament.url, name="Field 1").one()
    db.session.add(FieldCamera(field_id=field.id, slot=0, stream_url="rtmp://example/0"))
    db.session.commit()
    db.session.add(FieldCamera(field_id=field.id, slot=0, stream_url="rtmp://other/0"))
    with pytest.raises(sa.exc.IntegrityError):
        db.session.commit()
    db.session.rollback()


@pytest.mark.unit
def test_match_camera_stream_starts_unique_per_slot(test_db, tournament):
    """MatchCameraStreamStart enforces UNIQUE(match_uuid, camera_slot)."""
    m = _make_match(test_db, tournament.url)
    db.session.add(MatchCameraStreamStart(match_uuid=m.uuid, camera_slot=0, stream_start="2026-01-01T00:00:00Z"))
    db.session.commit()
    db.session.add(MatchCameraStreamStart(match_uuid=m.uuid, camera_slot=0, stream_start="2026-01-01T01:00:00Z"))
    with pytest.raises(sa.exc.IntegrityError):
        db.session.commit()
    db.session.rollback()


@pytest.mark.unit
def test_camera_timepoints_unique_per_sequence(test_db, tournament):
    """CameraTimepoint enforces UNIQUE(camera_uuid, sequence)."""
    from models import Camera, Field

    field = Field.query.filter_by(event=tournament.url, name="Field 1").one()
    cam = Camera(
        match_uuid="not-a-real-match",
        event=tournament.url,
        field=field.id,
        name="cam1",
    )
    # Camera.match_uuid would normally have FK; for this test we sidestep the
    # FK by inserting via a direct execute that bypasses the session's
    # validation. Simpler: just create a real Match.
    m = _make_match(test_db, tournament.url, name="for_camera")
    cam.match_uuid = m.uuid
    db.session.add(cam)
    db.session.flush()

    db.session.add(CameraTimepoint(camera_uuid=cam.uuid, sequence=0, time_world="t0", time_video=0.0))
    db.session.commit()
    db.session.add(CameraTimepoint(camera_uuid=cam.uuid, sequence=0, time_world="t1", time_video=1.0))
    with pytest.raises(sa.exc.IntegrityError):
        db.session.commit()
    db.session.rollback()


# ---------------------------------------------------------------------------
# Mutual-exclusivity CHECK constraints.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_team_registration_rejects_both_event_and_league(test_db, tournament, team):
    """TeamRegistration with both event and league_id set must fail the CHECK constraint."""
    db.session.add(
        TeamRegistration(
            event=tournament.url,
            league_id="some-league",
            team=team.id,
            pseudonym="X",
            status=TeamRegistrationStatus.CONFIRMED,
        )
    )
    with pytest.raises(sa.exc.IntegrityError):
        db.session.commit()
    db.session.rollback()


@pytest.mark.unit
def test_team_registration_rejects_neither_event_nor_league(test_db, team):
    """TeamRegistration with neither event nor league_id set must fail the CHECK."""
    db.session.add(
        TeamRegistration(
            team=team.id,
            pseudonym="X",
            status=TeamRegistrationStatus.CONFIRMED,
        )
    )
    with pytest.raises(sa.exc.IntegrityError):
        db.session.commit()
    db.session.rollback()


@pytest.mark.unit
def test_player_registration_rejects_both_event_and_league(test_db, tournament, player):
    """PlayerRegistration mutual-exclusivity CHECK rejects both-set."""
    db.session.add(
        PlayerRegistration(
            event=tournament.url,
            league_id="some-league",
            player=player.id,
            jersey_number="1",
        )
    )
    with pytest.raises(sa.exc.IntegrityError):
        db.session.commit()
    db.session.rollback()


@pytest.mark.unit
def test_to_rejects_neither_event_nor_league(test_db, player):
    """TO without event or league_id must fail the CHECK."""
    db.session.add(TO(user_id=player.id, user_type="player"))
    with pytest.raises(sa.exc.IntegrityError):
        db.session.commit()
    db.session.rollback()


# ---------------------------------------------------------------------------
# Email uniqueness — duplicate rejected, NULLs allowed to repeat.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_team_email_unique_rejects_duplicate(test_db):
    """Inserting two teams with the same email raises IntegrityError."""
    db.session.add(Team(id="ta", name="A", pw_hash="h", email="dup@example.com"))
    db.session.commit()
    db.session.add(Team(id="tb", name="B", pw_hash="h", email="dup@example.com"))
    with pytest.raises(sa.exc.IntegrityError):
        db.session.commit()
    db.session.rollback()


@pytest.mark.unit
def test_team_email_unique_allows_multiple_nulls(test_db):
    """Multiple teams with NULL email are allowed (SQL-standard UNIQUE)."""
    db.session.add(Team(id="t1", name="A", pw_hash="h"))
    db.session.add(Team(id="t2", name="B", pw_hash="h"))
    db.session.commit()
    assert Team.query.filter(Team.email.is_(None)).count() >= 2


# ---------------------------------------------------------------------------
# Monetary precision — exact decimal round-trip through the ORM.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_amount_paid_is_decimal(test_db, tournament, team):
    """TeamRegistration.amount_paid round-trips as Decimal, not float."""
    reg = TeamRegistration(
        event=tournament.url,
        team=team.id,
        pseudonym="X",
        status=TeamRegistrationStatus.CONFIRMED,
        amount_paid=Decimal("12.34"),
    )
    db.session.add(reg)
    db.session.commit()

    fetched = TeamRegistration.query.get(reg.id)
    assert fetched.amount_paid == Decimal("12.34")
    assert isinstance(fetched.amount_paid, Decimal)
