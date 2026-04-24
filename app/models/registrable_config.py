"""SQLAlchemy model for shared registration configuration (RegistrableConfig)."""

from __future__ import annotations

from app.models.base import db
from app.models.constants import LONG_URL_LEN, SHA256_HEX_LEN


class RegistrableConfig(db.Model):  # type: ignore[misc]
    """Shared registration configuration for standalone tournaments and leagues.

    Standalone tournaments (``league_id`` is null) own their own config;
    league tournaments inherit the league's config.  Fee constraints are
    enforced at the database level.

    Attributes:
        id: Auto-increment primary key.
        team_reg_fee: Registration fee charged per team (≥ 0). Stored as
            an exact ``DECIMAL(10, 2)`` value — never as a binary float —
            so monetary arithmetic does not accumulate IEEE-754 rounding
            errors across many payments.
        player_reg_fee: Registration fee charged per player (≥ 0). Same
            ``DECIMAL(10, 2)`` storage rationale as ``team_reg_fee``.
        payment_info: Free-text payment instructions shown to registrants.
        registration_open: Deprecated global toggle; prefer the per-type
            toggles below.
        team_registration_open: Whether team registration is currently
            accepting new entries.
        player_registration_open: Whether individual player registration is
            currently open.
        terms_link: URL to the tournament's terms and conditions page.
        waiver_filepath: Server-relative path to the uploaded waiver file.
        waiver_sha256: SHA-256 hex digest of the waiver file bytes.
        n_max_teams: Cap on the number of registered teams, or ``None``.
        max_team_size_roster: Maximum players on a team's full roster.
        max_team_size_field: Maximum players allowed on the field at once.
    """

    __tablename__ = "registrable_configs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    team_reg_fee = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    player_reg_fee = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    payment_info = db.Column(db.Text)
    # Deprecated: use team_registration_open / player_registration_open instead.
    # Kept for backward compatibility and migration scripts.
    registration_open = db.Column(db.Boolean, default=False, nullable=False)
    # Separate toggles for team and player registration.
    team_registration_open = db.Column(db.Boolean, default=False, nullable=False)
    player_registration_open = db.Column(db.Boolean, default=False, nullable=False)
    terms_link = db.Column(db.String(LONG_URL_LEN))
    # Waiver file uploaded by TOs for this event (standalone tournament or league).
    # Stored as a relative filepath so the frontend can link consistently.
    waiver_filepath = db.Column(db.String(LONG_URL_LEN))
    # SHA-256 of the waiver file bytes (hex string).
    waiver_sha256 = db.Column(db.String(SHA256_HEX_LEN))
    n_max_teams = db.Column(db.Integer)
    max_team_size_roster = db.Column(db.Integer)
    max_team_size_field = db.Column(db.Integer)

    __table_args__ = (
        db.CheckConstraint("team_reg_fee >= 0", name="ck_registrable_config_team_reg_fee_nonneg"),
        db.CheckConstraint("player_reg_fee >= 0", name="ck_registrable_config_player_reg_fee_nonneg"),
    )
